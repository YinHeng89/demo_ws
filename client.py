"""
WebSocket 客户端示例

功能概述：
- 从本地摄像头捕获视频帧
- 将帧缩放为指定分辨率并按指定编码（JPEG/WebP）压缩
- 将编码后的二进制帧通过 WebSocket 发送到后端上传端（/ws/stream）
- 本地在窗口中预览发送的帧，并在画面上叠加发送队列与帧率信息

运行示例：
    python client.py --uri ws://localhost:9000/ws/stream --fps 5 --width 640 --height 480 --format jpg --quality 80

依赖：
    websockets, opencv-python, numpy

实现要点：
- 尝试使用 Windows 的 DirectShow(`cv2.CAP_DSHOW`) 打开摄像头并请求分辨率/帧率（驱动可能忽略）
- 使用线程池 (`run_in_executor`) 做同步的图像编码，避免阻塞 asyncio 事件循环
- 使用 `asyncio.Queue` 做发包队列，发送任务在后台异步消费，确保网络抖动时不会立即阻塞采集
"""

import argparse
import asyncio
import sys
import cv2
import numpy as np
import websockets
import time
from typing import Optional


async def send_frames(uri: str, fps: float = 5.0, quality: int = 80, device: int = 0, width: int = 640, height: int = 480, fmt: str = 'jpg', screen: bool = False, monitor_index: Optional[int] = None):
    interval = 1.0 / max(1.0, fps)

    cap = None
    sct = None
    monitor = None
    actual_w = actual_h = actual_fps_prop = 0

    if screen:
        # 屏幕捕获路径（使用 mss）
        try:
            import mss
        except Exception:
            print('屏幕捕获需要包 `mss`，请先运行: pip install mss')
            return
        try:
            sct = mss.mss()
            monitors = sct.monitors
            # monitor_index: None -> 使用主显示器 monitors[1]
            mi = monitor_index if monitor_index and 1 <= monitor_index < len(monitors) else 1
            monitor = monitors[mi]
            actual_w = monitor['width']
            actual_h = monitor['height']
            actual_fps_prop = fps
            # 当选择屏幕捕获时，如果用户未显式传入 width/height，使用显示器分辨率作为有效分辨率
            try:
                width = int(actual_w)
                height = int(actual_h)
            except Exception:
                pass
            print(f'Screen capture selected: monitor {mi} {actual_w}x{actual_h} @ {fps}fps')
            print(f'Effective capture resolution set to: {width}x{height}')
        except Exception as e:
            print('无法初始化屏幕捕获:', e)
            return
    else:
        # 尝试使用 Windows DirectShow 后端以便能设置 CAP_PROP_FPS
        try:
            cap = cv2.VideoCapture(device, cv2.CAP_DSHOW)
        except Exception:
            cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            print("无法打开摄像头")
            return

        # 尝试向摄像头请求分辨率和期望FPS（驱动可能忽略）
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
        except Exception:
            pass

        # 打印摄像头报告的实际参数，便于调试
        actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps_prop = cap.get(cv2.CAP_PROP_FPS)
        print(f'Camera opened: {int(actual_w)}x{int(actual_h)} @ {actual_fps_prop:.2f} (requested {width}x{height}@{fps})')

    try:
        async with websockets.connect(uri, max_size=None) as ws:
            print(f"Connected to {uri}")
            
            # 发送队列（将编码后的 bytes 放入队列，由后台任务负责实际发送）
            send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4)
            
            # 统计
            sent_count = 0
            # fps统计（生产/编码侧）
            last_fps_time = time.time()
            produced_in_interval = 0
            actual_fps = 0.0

            stop_event = asyncio.Event()
            
            async def sender_task():
                nonlocal sent_count
                try:
                    while not stop_event.is_set():
                        data = await send_queue.get()
                        try:
                            await ws.send(data)
                            sent_count += 1
                        except Exception as e:
                            print('Send error:', e)
                            break
                finally:
                    stop_event.set()

            sender = asyncio.create_task(sender_task())

            loop = asyncio.get_running_loop()
            try:
                next_frame_time = time.time()
                while not stop_event.is_set():
                    now = time.time()
                    # capture: camera or screen
                    if screen:
                        try:
                            img = sct.grab(monitor)
                            frame = np.array(img)
                            # mss on Windows -> BGRA
                            if frame.shape[2] == 4:
                                try:
                                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                                except Exception:
                                    frame = frame[:, :, :3]
                        except Exception as e:
                            print('屏幕读取失败:', e)
                            break
                    else:
                        ret, frame = cap.read()
                        if not ret:
                            print("读取帧失败")
                            break

                    # resize to configured resolution for stable bandwidth
                    frame_resized = cv2.resize(frame, (width, height))

                    # encode in threadpool to avoid blocking event loop
                    ext = '.' + fmt.lower().lstrip('.')
                    params = None
                    if ext in ('.jpg', '.jpeg'):
                        params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                    elif ext == '.webp':
                        params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
                    else:
                        params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]

                    try:
                        # 在后台线程中执行 imencode，某些 OpenCV 构建对参数签名不同做兼容处理
                        success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized, params)
                    except TypeError:
                        # 部分 OpenCV 版本不接受 params 参数
                        success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized)

                    if not success:
                        # skip frame
                        pass
                    else:
                        data = buf.tobytes()
                        # 尝试非阻塞放入队列，若满则丢弃最旧一帧以让新帧入队
                        try:
                            send_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            try:
                                _ = send_queue.get_nowait()
                            except Exception:
                                pass
                            try:
                                send_queue.put_nowait(data)
                            except Exception:
                                # 最后无论如何跳过放入
                                pass

                        # 生产/编码统计
                        produced_in_interval += 1

                    # 更新生产侧 FPS 每秒
                    now2 = time.time()
                    elapsed = now2 - last_fps_time
                    if elapsed >= 1.0:
                        actual_fps = produced_in_interval / elapsed
                        produced_in_interval = 0
                        last_fps_time = now2

                    # 不显示原始画面；在单独的状态窗口中展示推流相关信息
                    status_h, status_w = 220, 640
                    status = np.zeros((status_h, status_w, 3), dtype=np.uint8)
                    y = 30
                    dy = 26
                    cv2.putText(status, f"URI: {uri}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                    y += dy
                    if screen:
                        cv2.putText(status, f"Screen (reported): {int(actual_w)}x{int(actual_h)} @ {actual_fps_prop:.2f}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                    else:
                        cv2.putText(status, f"Camera (reported): {int(actual_w)}x{int(actual_h)} @ {actual_fps_prop:.2f}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                    y += dy
                    cv2.putText(status, f"Requested: {width}x{height} @ {fps}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                    y += dy
                    cv2.putText(status, f"Produced FPS: {actual_fps:.1f}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 1)
                    y += dy
                    qsize = send_queue.qsize()
                    last_size = getattr(send_queue, '_last_put_size', 0)
                    cv2.putText(status, f"Queue size: {qsize}    Sent: {sent_count}    LastEnqueued: {last_size}B", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,0), 1)
                    y += dy
                    cv2.putText(status, f"Format: {fmt}    Quality: {quality}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                    y += dy
                    cv2.putText(status, "Press 'Q' to quit", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150,150,150), 1)

                    cv2.imshow('Client Status', status)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break

                    # 精确调度下一帧时间以尽量贴合目标 FPS
                    next_frame_time += interval
                    to_sleep = next_frame_time - time.time()
                    if to_sleep > 0:
                        await asyncio.sleep(to_sleep)
                    else:
                        # 如果编码耗时较长，重置下一个时间点
                        next_frame_time = time.time()
            except Exception as e:
                print('WebSocket error during send loop:', e)
            finally:
                stop_event.set()
                try:
                    sender.cancel()
                except Exception:
                    pass
                if cap is not None:
                    cap.release()
                cv2.destroyAllWindows()
    except ConnectionRefusedError:
        print(f"Connection refused: unable to connect to {uri}")
        return
    except Exception as e:
        print('WebSocket error:', e)
        return
        # 发送队列（将编码后的 bytes 放入队列，由后台任务负责实际发送）
        send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=4)

        # 统计
        sent_count = 0
        # fps统计（生产/编码侧）
        last_fps_time = time.time()
        produced_in_interval = 0
        actual_fps = 0.0

        stop_event = asyncio.Event()

        async def sender_task():
            nonlocal sent_count
            try:
                while not stop_event.is_set():
                    data = await send_queue.get()
                    try:
                        await ws.send(data)
                        sent_count += 1
                    except Exception as e:
                        print('Send error:', e)
                        break
            finally:
                stop_event.set()

        sender = asyncio.create_task(sender_task())

        loop = asyncio.get_running_loop()
        try:
            next_frame_time = time.time()
            while not stop_event.is_set():
                now = time.time()
                # capture
                ret, frame = cap.read()
                if not ret:
                    print("读取帧失败")
                    break

                # resize to configured resolution for stable bandwidth
                frame_resized = cv2.resize(frame, (width, height))

                # encode in threadpool to avoid blocking event loop
                ext = '.' + fmt.lower().lstrip('.')
                params = None
                if ext in ('.jpg', '.jpeg'):
                    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                elif ext == '.webp':
                    params = [int(cv2.IMWRITE_WEBP_QUALITY), quality]
                else:
                    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]

                try:
                    # 在后台线程中执行 imencode，某些 OpenCV 构建对参数签名不同做兼容处理
                    success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized, params)
                except TypeError:
                    # 部分 OpenCV 版本不接受 params 参数
                    success, buf = await loop.run_in_executor(None, cv2.imencode, ext, frame_resized)
                except asyncio.CancelledError:
                    # 编码任务被取消（例如 Ctrl+C 导致 asyncio 取消），优雅退出循环
                    print('Encoding cancelled, shutting down send loop')
                    break

                if not success:
                    # skip frame
                    pass
                else:
                    data = buf.tobytes()
                    # 尝试非阻塞放入队列，若满则丢弃最旧一帧以让新帧入队
                    try:
                        send_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        try:
                            _ = send_queue.get_nowait()
                        except Exception:
                            pass
                        try:
                            send_queue.put_nowait(data)
                        except Exception:
                            # 最后无论如何跳过放入
                            pass

                    # 生产/编码统计
                    produced_in_interval += 1

                # 更新生产侧 FPS 每秒
                now2 = time.time()
                elapsed = now2 - last_fps_time
                if elapsed >= 1.0:
                    actual_fps = produced_in_interval / elapsed
                    produced_in_interval = 0
                    last_fps_time = now2

                # 不显示原始画面；在单独的状态窗口中展示推流相关信息
                status_h, status_w = 220, 640
                status = np.zeros((status_h, status_w, 3), dtype=np.uint8)
                y = 30
                dy = 26
                cv2.putText(status, f"URI: {uri}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                y += dy
                cv2.putText(status, f"Camera (reported): {int(actual_w)}x{int(actual_h)} @ {actual_fps_prop:.2f}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                y += dy
                cv2.putText(status, f"Requested: {width}x{height} @ {fps}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                y += dy
                cv2.putText(status, f"Produced FPS: {actual_fps:.1f}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 1)
                y += dy
                qsize = send_queue.qsize()
                last_size = getattr(send_queue, '_last_put_size', 0)
                cv2.putText(status, f"Queue size: {qsize}    Sent: {sent_count}    LastEnqueued: {last_size}B", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,0), 1)
                y += dy
                cv2.putText(status, f"Format: {fmt}    Quality: {quality}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1)
                y += dy
                cv2.putText(status, "Press 'q' to quit", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150,150,150), 1)

                cv2.imshow('Client Status', status)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

                # 精确调度下一帧时间以尽量贴合目标 FPS
                next_frame_time += interval
                to_sleep = next_frame_time - time.time()
                if to_sleep > 0:
                    await asyncio.sleep(to_sleep)
                else:
                    # 如果编码耗时较长，重置下一个时间点
                    next_frame_time = time.time()
        except Exception as e:
            print('WebSocket 错误:', e)
        finally:
            stop_event.set()
            try:
                sender.cancel()
            except Exception:
                pass
            cap.release()
            cv2.destroyAllWindows()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--uri', type=str, default='ws://localhost:9000/ws/stream')
    parser.add_argument('--fps', type=float, default=30.0)
    parser.add_argument('--quality', type=int, default=80)
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--height', type=int, default=480)
    parser.add_argument('--format', type=str, default='jpg', choices=['jpg', 'jpeg', 'webp'], help='Encoding format: jpg (default) or webp')
    parser.add_argument('--screen', action='store_true', help='Use screen capture instead of camera')
    parser.add_argument('--monitor', type=int, default=None, help='Monitor index for mss (1 = primary)')
    args = parser.parse_args()

    # 显示当前数据来源与请求分辨率（便于调试）
    if getattr(args, 'screen', False):
        print(f'Client starting: using SCREEN capture (monitor={args.monitor})')
    else:
        print(f'Client starting: using CAMERA device {args.device}')
    # 显示传入的请求分辨率/帧率，便于确认 start 脚本是否传参成功
    print(f'Requested resolution: {args.width}x{args.height} @ {args.fps}fps')

    try:
        asyncio.run(send_frames(args.uri, args.fps, args.quality, args.device, args.width, args.height, args.format, screen=args.screen, monitor_index=args.monitor))
    except KeyboardInterrupt:
        # 用户按 Ctrl+C，中断为正常退出，不显示长 traceback
        print('\nInterrupted by user, exiting.')
        sys.exit(0)
