# WebSocket + JPEG Demo — 双语说明 / Bilingual README

**简要（中文）**
- 这是一个精简的演示：Server 使用 FastAPI 提供 `/ws/view` WebSocket 端点，启动时（默认）可从本地摄像头采集 JPEG 帧并广播给所有连接的 viewer。页面 `GET /viewer` 提供一个简单的 HTML 客户端用于查看实时画面。
- 只保留了一个环境变量 `LOCAL_CAPTURE`：设置为 `'0'` 可禁用采集，否则默认启用。

**Quick Summary (English)**
- Minimal demo: server exposes `/ws/view` (WebSocket) and `/viewer` (HTML viewer). On startup the server will run a background capture-and-broadcast task (unless `LOCAL_CAPTURE=0`). Clients receive JPEG frames over WebSocket.

**Files of interest / 主要文件**
- `server.py` — 精简的 FastAPI 服务，包含摄像头捕获与广播逻辑（默认启动时启用，除非 `LOCAL_CAPTURE=0`）。
- `view_ws.html` — 浏览器端演示页面（通过 `/viewer` 提供），在画布上显示接收的 JPEG 帧。
- `requirements.txt` — Python 运行依赖（例如 `fastapi`, `uvicorn`, `opencv-python`, `numpy`）。

## 快速开始 / Quick Start

建议在 PowerShell 中运行以下命令。

1) 安装依赖（建议使用虚拟环境）

```powershell
python -m pip install -r requirements.txt
```

2) 启动服务（默认绑定 `0.0.0.0:9000`）

```powershell
python .\server.py
# 或使用 uvicorn： uvicorn server:app --host 0.0.0.0 --port 9000
```

3) 在浏览器打开查看页面

- 打开： `http://127.0.0.1:9000/viewer` 来查看实时画面（页面会连接 `/ws/view` 接收 JPEG 帧）。

4) 可选：禁用本地采集（仅启动服务）

```powershell
$env:LOCAL_CAPTURE='0'; python .\server.py
```

Notes (English)
- By default the server will start a capture broadcaster unless you explicitly set `LOCAL_CAPTURE=0`.
- If you want to run the server under an external ASGI runner (uvicorn), the same environment variable controls capture.

## 兼容与变更说明 / Compatibility & Notes

- 旧版仓库中存在的上传端点 `/ws/stream` 已被移除；如果你的旧脚本或 `client.py` 仍指向 `/ws/stream`，需要改为对接新的 `/ws/view` 逻辑或弃用该客户端。
- 我们移除了 GUI 弹窗预览的线程实现（便于在无头环境运行）；页面渲染通过 `view_ws.html` 在浏览器完成。

## 小贴士 / Tips

- 若要快速在本机测试：直接运行 `python server.py`（默认开启采集）并打开 `/viewer`。
- 若在远端部署并希望禁用摄像头采集（例如服务器无摄像头），请设置 `LOCAL_CAPTURE=0`。

## 进一步改进建议 / Possible Improvements

- 支持认证/HTTPS (`wss://`)；在公网部署时请为 WebSocket 配置 TLS。
- 优化广播逻辑：当前实现逐个 await 发送给客户端，慢客户端可能影响总体延迟；可改为并发发送或加入超时/丢帧策略。
- 若需要保存或处理最后一帧，建议在服务端保存最近成功编码的 JPEG bytes 并在新连接时立即发送以改善首帧显示体验。

---

如果你要我把 README 中的示例命令改成更贴合你常用的启动方式（比如始终使用 `uvicorn` 或添加 `start_demo.bat` 的精简替代脚本），我可以继续修改。

