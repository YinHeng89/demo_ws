WebSocket + JPEG Demo

说明
- 本 demo 演示如何将本地摄像头帧编码为 JPEG，通过 WebSocket 持久连接发送到服务端，服务端展示接收到的最新帧。

目录
- `server.py`  服务端（FastAPI WebSocket 接收，显示最新帧）
- `client.py`  客户端（OpenCV 捕获，JPEG 编码并通过 WebSocket 发送）
- `requirements.txt` 运行依赖

快速开始（PowerShell）

1) 安装依赖（建议虚拟环境）

```powershell
cd FaceCaptureApp_Client\demo_ws
python -m pip install -r requirements.txt
```

2) 启动服务端（在一个终端）

```powershell
# 使用 uvicorn 启动 FastAPI
uvicorn server:app --host 0.0.0.0 --port 9000
```

3) 启动客户端（在另一个终端）

```powershell
python client.py --uri ws://localhost:9000/ws/stream --fps 5
```

可选：在单进程中让 `server.py` 直接从本地摄像头采集并供 `/ws/view` 使用（无需运行 `client.py`）。有两种方式启用：

- 环境变量方式（适用于 `uvicorn server:app`）：

```powershell
# PowerShell 示例：启用本地采集
$env:LOCAL_CAPTURE=1; $env:LOCAL_CAPTURE_FPS=5; uvicorn server:app --host 0.0.0.0 --port 9000
```

- 或直接运行 `server.py` 并传入参数（适用于双击或 `python server.py`）:

```powershell
python server.py --with-local-capture --device 0 --fps 5 --width 640 --height 480
```

4) 结果
- 服务端会弹出 `Server Preview` 窗口，显示接收到的最新帧。
- 客户端会弹出 `Client Preview` 窗口，显示本地摄像头采集的画面。
- 在任一窗口按 `q` 可关闭该窗口；服务端仍继续监听 WebSocket（关闭 preview 后可重新观察）。

注意与调整
- 如果在 Windows 上运行出现 OpenCV 窗口问题，请确保在主线程运行 GUI（当前实现以线程方式展示，一般可用）。
- 若要在远程机器上测试，请把 `--uri` 指向服务端地址（注意防火墙与网络连通性），并在公网场景使用 `wss://`（TLS）。
- 调整分辨率/质量/帧率以兼顾性能：默认 640x480, quality=80, fps=5 为良好起点。

后续改进
- 在服务端把检测逻辑接入 `latest_frame` 槽（示例已准备好 dedicated slot）；可把 `detect_with_validation()` 调用加入到独立的检测线程。
- 增加认证/token、心跳与重连逻辑，提升稳定性与安全性。

