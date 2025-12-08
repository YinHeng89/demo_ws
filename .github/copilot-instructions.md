# Copilot 指令 — WebSocket + JPEG Demo

目标：帮助 AI 代码代理快速理解项目用途、主要组件、运行/调试流程以及代码中的可改动点。

- **项目类型**：单仓库演示工程，包含一个 FastAPI 服务端（`server.py`）和一个 OpenCV 客户端（`client.py`），通过 WebSocket 交换 JPEG 二进制帧。
- **主要文件**:
  - `server.py`：FastAPI 应用，暴露 `/ws/stream`（上传端）和 `/ws/view`（浏览/下发端）两个 WebSocket 路径；使用独立线程显示最新帧，保存在单槽 `latest_frame`。
  - `client.py`：摄像头/屏幕采集、使用 OpenCV 编码（`cv2.imencode`）并通过 WebSocket 持续发送；使用 `asyncio.Queue` 做发送缓冲。
  - `requirements.txt`：运行依赖（`fastapi`, `uvicorn[standard]`, `websockets`, `opencv-python`, `numpy`）。
  - `start_demo.bat`：Windows 启动脚本（便捷，但无必需性，命令行优先）。
  - `README.md`：快速上手命令与设计说明，优先参考。

快速上手（开发者命令）

```
# 安装依赖
python -m pip install -r requirements.txt

# 启动服务端 (在一个终端)
uvicorn server:app --host 0.0.0.0 --port 9000

# 启动客户端 (另一个终端)
python client.py --uri ws://localhost:9000/ws/stream --fps 5
```

关键设计/约定（对代码改动很重要）

- 单槽（single-slot）最新帧：`server.py` 按全局变量 `_latest_frame_bytes` 保存最新收到的二进制帧。任何处理逻辑（检测/保存）应以读取该槽为入口，避免直接修改这一同步约束。
- 上传/观看分离：不要把浏览器端直接连接到 `/ws/stream`；浏览器应连接 `/ws/view`。上传端负责写入单槽；观看端按帧 ID 变化发送最新帧。
- 显示线程：服务端使用守护线程（daemon）做 OpenCV 窗口显示；线程与 FastAPI 生命周期绑定（见 `lifespan`）。修改生命周期时注意不要阻塞事件循环。
- 编码路径：客户端在后台线程池中执行 `cv2.imencode`（通过 `run_in_executor`）以避免阻塞 asyncio 事件循环——保持此模式或等效异步实现。
- 发送缓冲：`asyncio.Queue(maxsize=4)` 作为短时缓冲。网络阻塞时策略是丢弃最旧帧以优先发送最新帧；如果改为可靠队列或持久化，请同时调整客户端和服务端的预期行为。
- Windows 摄像头：`client.py` 默认用 `cv2.CAP_DSHOW` 尝试启用 DirectShow；可在跨平台修改后退到默认后端。

常见修改点与注意事项

- 想添加检测/持久化：在服务端读取 `_latest_frame_bytes` 并在独立线程/任务里处理，避免在 WebSocket handler 内做耗时计算。
- 想改为多消费者/多房间：当前实现以单一全局槽为核心，若改为多流或多房间，需要重构为基于连接 ID 的缓冲或消息总线。
- 调整帧发送策略：修改 `client.py` 中队列大小或丢弃策略时同步调整服务端统计/展示逻辑。

调试提示（基于仓库已发现的行为）

- 若连接失败：检查 `uvicorn` 是否运行（`uvicorn server:app ...`），并确认 `--host/--port` 与客户端 `--uri` 对应。
- 若 OpenCV 窗口不出现：Windows 下注意 GUI 线程限制；服务端使用守护线程做显示，通常可用，但复杂 GUI 改动请在主线程验证。
- 网络/性能排查：查看服务端 `_network_total_bytes` 与 `_recv_total_count` 的更新以判断带宽与消息率；客户端可通过 `--fps`/`--width`/`--height`/`--quality` 调低负载。

搜索与修改小贴士

- 查找 WebSocket 端点：搜索 `@app.websocket("/ws/stream")` 与 `@app.websocket("/ws/view")`。
- 查找编码逻辑：在 `client.py` 搜索 `imencode`、`run_in_executor`、`asyncio.Queue`。

当你作为 AI 代理修改代码时，请保持接口稳定（端点路径 `/ws/stream` 和 `/ws/view`）除非同时更新 README 与调用脚本。

如需我合并现有 `.github/copilot-instructions.md` 或把此内容更紧凑、或翻译成中文/英文不同版本，请告诉我需要保留或删除的段落。
