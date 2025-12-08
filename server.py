"""
WebSocket 接收端（服务端）示例
- 接收客户端通过 WebSocket 发送的 JPEG 二进制帧
- 将收到的最新帧保存到单槽（latest_frame），并在独立显示线程中用 OpenCV 展示

运行（在项目环境中）：
uvicorn server:app --host 0.0.0.0 --port 9000

然后启动客户端发送帧到 ws://localhost:9000/ws/stream
按 'q' 关闭服务端预览窗口（服务仍在运行）
"""

import threading
import time
from typing import Optional
from contextlib import asynccontextmanager

import numpy as np
import asyncio
import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在应用启动时开启显示线程（守护线程），在退出时无需特殊清理
    t = threading.Thread(target=_display_loop, daemon=True)
    t.start()
    try:
        try:
            yield
        except asyncio.CancelledError:
            # FastAPI/uvicorn may cancel the lifespan during shutdown; exit quietly
            return
    finally:
        # thread is daemon; it will exit with the process
        pass


app = FastAPI(lifespan=lifespan)

# 单槽保存最新帧
_latest_lock = threading.Lock()
_latest_frame_bytes: Optional[bytes] = None
_latest_frame_id = 0
# 网络统计（累计接收字节数）
_network_lock = threading.Lock()
_network_total_bytes = 0
# 接收消息计数（用于 recv FPS 统计）
_recv_lock = threading.Lock()
_recv_total_count = 0


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket):
    """WebSocket 接收器：接收二进制 JPEG 消息并覆盖最新帧槽"""
    await websocket.accept()
    global _latest_frame_bytes, _latest_frame_id
    try:
        while True:
            data = await websocket.receive_bytes()
            with _latest_lock:
                _latest_frame_bytes = data
                _latest_frame_id += 1
            # 累计收到的字节数（线程安全）和消息计数
            with _network_lock:
                global _network_total_bytes
                _network_total_bytes += len(data)
            with _recv_lock:
                global _recv_total_count
                _recv_total_count += 1
    except WebSocketDisconnect:
        # 客户端断开连接
        return
    except asyncio.CancelledError:
        # Server/application is shutting down; exit quietly
        return
    except Exception:
        return


@app.websocket("/ws/view")
async def ws_view(websocket: WebSocket):
    """
    浏览器/查看器专用的 WebSocket 端点

    说明：该端点为只发（server -> viewer）通道，向连接的浏览器推送最近保存的 JPEG 二进制帧。
    - 每隔固定间隔检查是否有最新帧；仅当帧 ID 变化时才发送，以避免重复发送相同的数据
    - 该端点与上传端 `/ws/stream` 分离，浏览器不应连接到上传端（否则不会接收帧）
    """
    await websocket.accept()
    prev_id = -1
    try:
        while True:
            # 以约 30 FPS 的频率检查并发送最新帧（如果有更新）
            await asyncio.sleep(0.033)
            with _latest_lock:
                data = _latest_frame_bytes
                fid = _latest_frame_id
            if data is None:
                # 尚无任何上传帧，继续等待
                continue
            # 仅当有新帧时发送，避免重复占用带宽
            if fid != prev_id:
                try:
                    await websocket.send_bytes(data)
                    prev_id = fid
                except WebSocketDisconnect:
                    # 观看端断开连接，结束循环
                    break
                except Exception:
                    # 其他网络/发送错误，终止
                    break
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        # Application server is shutting down; exit without traceback
        return
    except Exception:
        return


def _display_loop():
    """独立线程：不断读取 latest_frame 并用 OpenCV 展示"""
    global _latest_frame_bytes, _latest_frame_id
    cv2.namedWindow("Server Preview", cv2.WINDOW_AUTOSIZE)
    last_id = 0
    # 最近一次成功解码并显示的帧（用于在解码失败时继续显示，避免闪烁）
    last_display_frame = None
    # FPS 统计
    last_fps_time = time.time()
    shown_frames = 0
    # 最近一次计算得到的 FPS 值（用于显示，即便帧变为 stale）
    last_fps_value = 0.0
    # 网络统计：上次采样时间、上次累计字节数、最近计算得到的速率 (bytes/sec)
    last_net_time = time.time()
    last_net_total = 0
    last_net_rate = 0.0
    # recv 统计
    last_recv_time = time.time()
    last_recv_total = 0
    last_recv_rate = 0.0
    try:
        while True:
            frame = None
            with _latest_lock:
                if _latest_frame_bytes is not None and _latest_frame_id != last_id:
                    nparr = np.frombuffer(_latest_frame_bytes, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    last_id = _latest_frame_id
            if frame is not None:
                # 叠加左上角文字（帧号和FPS）
                shown_frames += 1
                now = time.time()
                elapsed = now - last_fps_time
                fps = shown_frames / elapsed if elapsed > 0 else 0.0
                last_fps_value = fps
                # 网络速率计算（每1s更新一次）
                net_elapsed = now - last_net_time
                if net_elapsed >= 1.0:
                    with _network_lock:
                        current_total = _network_total_bytes
                    last_net_rate = (current_total - last_net_total) / net_elapsed
                    last_net_total = current_total
                    last_net_time = now
                # 接收帧速率（每1s更新一次）
                recv_elapsed = now - last_recv_time
                if recv_elapsed >= 1.0:
                    with _recv_lock:
                        current_recv_total = _recv_total_count
                    last_recv_rate = (current_recv_total - last_recv_total) / recv_elapsed
                    last_recv_total = current_recv_total
                    last_recv_time = now
                overlay_text = f"FPS: {fps:.1f}"
                # 附加网络使用显示（KB/s）与接收速率
                net_kb = last_net_rate / 1024.0
                overlay_text = f"Recv: {last_recv_rate:.1f}  Disp: {fps:.1f}  Net: {net_kb:.1f} KB/s"
                cv2.putText(frame, overlay_text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # 保存最近成功显示的帧，以防下一次解码失败
                try:
                    last_display_frame = frame.copy()
                except Exception:
                    last_display_frame = frame

                cv2.imshow("Server Preview", frame)
                # 按 q 退出预览
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                # 每隔1秒重置fps统计
                if elapsed >= 1.0:
                    last_fps_time = now
                    shown_frames = 0
            else:
                # 如果之前已有成功解码的帧，继续显示该帧以避免闪烁
                if last_display_frame is not None:
                    # 在旧帧上标注为（stale）提示
                    display = last_display_frame.copy()
                    net_kb = last_net_rate / 1024.0
                    cv2.putText(display, f"Recv: {last_recv_rate:.1f}  Disp: {last_fps_value:.1f}  Net: {net_kb:.1f} KB/s", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.imshow("Server Preview", display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    # 不 Sleeps 以保持响应性
                    continue

                # 无流且从未收到成功帧时显示占位画面，避免界面无响应
                h, w = 480, 640
                placeholder = np.zeros((h, w, 3), dtype=np.uint8)
                info = "Waiting for stream..."
                cv2.putText(placeholder, info, (20, int(h/2)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                cv2.putText(placeholder, "Recv: 0.0  Disp: 0.0  Net: 0.0 KB/s", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.imshow("Server Preview", placeholder)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                time.sleep(0.03)
    finally:
        cv2.destroyAllWindows()


# 启动线程逻辑已迁移到 FastAPI lifespan 处理器，见文件顶部的 lifecycle 实现。


@app.get("/")
async def index():
    return {"msg": "WebSocket JPEG demo. Connect to /ws/stream"}


if __name__ == '__main__':
    # Allow double-clicking this file to start the FastAPI/uvicorn server directly.
    # This will also trigger the FastAPI startup event which starts the OpenCV display thread.
    try:
        import uvicorn
    except Exception:
        raise
    uvicorn.run(app, host='0.0.0.0', port=9000)
