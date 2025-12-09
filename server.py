"""
极简 WebSocket JPEG 广播器
- 启动时创建后台采集与广播任务，从本地摄像头读取并编码 JPEG 帧，推送给所有连接到 `/ws/view` 的 WebSocket 客户端。
- 仅支持一个环境变量：`LOCAL_CAPTURE`。
    - 若 `LOCAL_CAPTURE` 设置为字符串 `'0'`，则禁用采集。
    - 其他任何值（或未设置）则默认启用采集。

用法：
- 正常运行：`python server.py`（默认启动采集和服务端）。
- 禁用采集：`set LOCAL_CAPTURE=0`（Windows PowerShell: `$env:LOCAL_CAPTURE='0'`）。
"""

import asyncio
import os
from typing import Set, Dict, Optional
from contextlib import asynccontextmanager

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pathlib import Path


# 配置（仅保留一个环境变量）
_LOCAL_CAPTURE_ENABLED = os.getenv("LOCAL_CAPTURE", "1") != "0"
_CAPTURE_DEVICE = 1 # 摄像头设备索引（通常为 0 或 1）   
_CAPTURE_FPS = 30.00 # 尝试设置的帧率
_CAPTURE_WIDTH = 640
_CAPTURE_HEIGHT = 480
_CAPTURE_FORMAT = "jpg"  # 简化设置
_CAPTURE_QUALITY = 40  # JPEG 质量（1-100）

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在应用启动时启动采集广播器（除非通过环境变量禁用）。
    if not _LOCAL_CAPTURE_ENABLED:
        print("检测到 LOCAL_CAPTURE=0：已禁用采集。")
        yield
        return

    stop = asyncio.Event()
    task = asyncio.create_task(_broadcast_loop(stop))
    print("采集广播器已启动；WebSocket 可通过 http://127.0.0.1:9000/viewer 访问")
    try:
        yield
    finally:
        stop.set()
        try:
            await task
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)

# 已连接的 WebSocket 客户端映射：ws -> {'queue': Queue, 'task': Task}
_clients: Dict[WebSocket, dict] = {}
_clients_lock = asyncio.Lock()

# 后台采集任务状态
_capture_task: asyncio.Task | None = None
_capture_stop: asyncio.Event | None = None


async def _broadcast_loop(stop_event: asyncio.Event):
    """Capture loop: read frames, encode, broadcast to all connected clients."""
    loop = asyncio.get_running_loop()

    def _open_cap():
        try:
            return cv2.VideoCapture(_CAPTURE_DEVICE, cv2.CAP_DSHOW)
        except Exception:
            return cv2.VideoCapture(_CAPTURE_DEVICE)

    cap = await loop.run_in_executor(None, _open_cap)
    if not cap or not cap.isOpened():
        print(f"Local capture: cannot open camera device {_CAPTURE_DEVICE}")
        return

    try:
        # 尝试设置基本属性（尽力而为）
        try:
            await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FRAME_WIDTH, _CAPTURE_WIDTH)
            await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FRAME_HEIGHT, _CAPTURE_HEIGHT)
            await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FPS, _CAPTURE_FPS)
        except Exception:
            pass

        interval = 1.0 / max(1.0, float(_CAPTURE_FPS))
        ext = "." + _CAPTURE_FORMAT.lstrip('.')
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(_CAPTURE_QUALITY)]

        while not stop_event.is_set():
            try:
                ret, frame = await loop.run_in_executor(None, cap.read)
            except Exception:
                await asyncio.sleep(0.01)
                continue
            if not ret or frame is None:
                await asyncio.sleep(0.01)
                continue

            try:
                frame_resized = await loop.run_in_executor(None, cv2.resize, frame, (_CAPTURE_WIDTH, _CAPTURE_HEIGHT))
            except Exception:
                frame_resized = frame

            try:
                success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized, params)
            except TypeError:
                success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized)
            except Exception:
                success = False

            if success:
                data = buf.tobytes()
                # 向已连接客户端广播当前帧快照：将数据非阻塞放入每个客户端的队列。
                async with _clients_lock:
                    clients_items = list(_clients.items())
                for ws, info in clients_items:
                    q: asyncio.Queue = info.get('queue')
                    if q is None:
                        continue
                    try:
                        # 非阻塞放入，若队满则丢弃旧帧后再放入（覆盖策略）
                        q.put_nowait(data)
                    except asyncio.QueueFull:
                        try:
                            _ = q.get_nowait()
                        except Exception:
                            pass
                        try:
                            q.put_nowait(data)
                        except Exception:
                            pass

            await asyncio.sleep(interval)
    finally:
        try:
            await loop.run_in_executor(None, cap.release)
        except Exception:
            pass


@app.websocket("/ws/view")
async def ws_view(websocket: WebSocket):
    """WebSocket 处理：为每个连接创建有界队列与单独发送任务，
    广播器将帧放入队列，由发送任务负责实际写入网络，避免慢客户端阻塞全局广播。"""
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)  # 保留最新帧

    async def _client_sender_loop(ws: WebSocket, q: asyncio.Queue):
        # 单独的发送任务：从队列取帧并发送，发送操作带超时保护
        try:
            while True:
                data = await q.get()
                try:
                    await asyncio.wait_for(ws.send_bytes(data), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    # 若发送失败或超时，尝试关闭连接并退出
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            return

    sender_task = asyncio.create_task(_client_sender_loop(websocket, queue))
    async with _clients_lock:
        _clients[websocket] = {'queue': queue, 'task': sender_task}

    try:
        # 保持连接直到客户端断开；不期望收到客户端消息。
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                await asyncio.sleep(0.1)
    finally:
        # 清理该客户端状态
        async with _clients_lock:
            info = _clients.pop(websocket, None)
        if info is not None:
            task = info.get('task')
            if task is not None:
                task.cancel()


@app.get('/viewer', response_class=HTMLResponse)
async def viewer_page():
    """Serve a minimal viewer HTML page to connect to `/ws/view`."""
    try:
        p = Path(__file__).parent / 'view_ws.html'
        return HTMLResponse(p.read_text(encoding='utf-8'))
    except Exception:
        return HTMLResponse('<h3>viewer page not found</h3>', status_code=404)


# 上方的 lifespan 处理器负责采集广播器的启动/关闭。


# 无 CLI 或额外端点；应用故意保持精简。


if __name__ == '__main__':
    import argparse
    try:
        import uvicorn
    except Exception:
        raise

    parser = argparse.ArgumentParser(description='Run minimal WebSocket JPEG broadcaster')
    parser.add_argument('--host', type=str, default='localhost', help='Host to bind')
    parser.add_argument('--port', type=int, default=9000, help='Port to bind')
    args = parser.parse_args()

    print(f"服务器启动于 http://{args.host}:{args.port} （WebSocket 路径：/ws/view）")
    uvicorn.run(app, host=args.host, port=args.port)

