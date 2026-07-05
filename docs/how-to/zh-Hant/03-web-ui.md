# Web 除錯介面

`web_app.py` 提供一個 **Agent Debug UI**，方便在本機觀察對話、事件流與背景執行結果。

## 啟動

在專案根目錄執行（依你的環境調整指令）：

```bash
python web_app.py
```

預設埠號請見 `web_app.py` 末尾的 `app.run(..., port=...)`。

## 畫面區塊

- **左側**：對話列表（來自 `LocalChatHistory` 掃描結果）。
- **中間**：訊息與輸入框；可設定 `max_steps`；**TODO 面板**與 `manage_todo_list` 同源（`chat_history/todos/<conversation_id>.json`），並監聽 SSE `todo_updated`。
- **右側**：**Debug Stream**，透過 **Server-Sent Events (SSE)** 推送 runtime 事件。

## API 速查

| 用途 | 方法與路徑 |
|------|------------|
| 主畫面 | `GET /` |
| 建立或延續對話執行 | `POST /api/chat` |
| 讀取對話 JSON | `GET /api/conversations/<id>` |
| 讀取 TODO 狀態（與工具同源） | `GET /api/conversations/<id>/todos` |
| 事件串流 | `GET /api/stream/<id>` |

`POST /api/chat` 若未帶 `conversation_id`，伺服器會建立新 id 並在背景執行 `AgentRuntime`。

## 與 SDK 文件的對應

瀏覽器文件中的 **`web_app`** 模組條目，描述上述路由與背景 worker 的責任切割。

## 下一步

- [執行迴圈、工具與紀錄](04-architecture.md) 說明 runtime 與 history 如何配合。
