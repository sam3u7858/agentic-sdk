# Web 服務 HTTP API 說明

本文件描述 `web_app.py`（Flask）對外提供的 **頁面路由** 與 **JSON / SSE API**。核心推論仍由 `AgentRuntime` 執行；Web 層負責輸入輸出、對話儲存與除錯用事件流。

**預設服務位址**：啟動後監聽埠號見 `web_app.py` 末尾的 `app.run(..., port=...)`（目前為 `15220`）。以下範例以 `http://127.0.0.1:15220` 為例。

**相關文件**：

- 操作與畫面說明：[how-to/zh-Hant/03-web-ui.md](how-to/zh-Hant/03-web-ui.md)
- 模組層級說明與閱讀順序：[SDK/WebApp-py.json](SDK/WebApp-py.json)

---

## 頁面（HTML）

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/` | Agent Debug UI 主畫面（模板 `index.html`）。 |
| `GET` | `/docs` | SDK 文件首頁（瀏覽 `docs/SDK/*.json`）。 |
| `GET` | `/docs/module/<module_id>` | 指定模組的 SDK 文件。 |
| `GET` | `/docs/symbol/<symbol_id>` | 指定符號的 SDK 文件。 |
| `GET` | `/docs/how-to` | How-to 文件，預設導向繁體首篇。 |
| `GET` | `/docs/how-to/<lang>` | 語系索引；`lang` 為 `zh-Hant`、`en`、`ja`。 |
| `GET` | `/docs/how-to/<lang>/<slug>` | 單篇 Markdown（檔名不含 `.md` 的 `slug`）。 |

若 `docs/SDK` 無可用 JSON，`GET /docs` 會回傳 **404**。

---

## REST API（JSON）

除特別註明外，成功回應的 `Content-Type` 為 `application/json`。

### `GET /api/conversations`

列出 `LocalChatHistory`（目錄 `chat_history`）內已知對話的摘要，供側欄列表使用。

**回應**：JSON 陣列，每個元素形例如下：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `conversation_id` | string | 對話 ID。 |
| `created_at` | string \| null | 建立時間（若歷史檔中有記錄）。 |
| `message_count` | number | 訊息則數。 |
| `preview` | string | 最後一則訊息內容前 120 字，供預覽。 |

### `GET /api/conversations/<conversation_id>`

讀取完整對話 JSON（與磁碟上儲存結構一致），並附加執行時快取的模型資訊。

**成功**：`200`，本體為對話物件，並保證包含：

| 欄位 | 說明 |
|------|------|
| `runtime_meta` | 物件，內含至少 `provider`、`model`（來自最近一次 `POST /api/chat` 排程時寫入的設定，執行完成後可能與實際後端一致）。 |

**失敗**：若 ID 不存在，`404`，本體為 `{"error": "Conversation not found"}`。

### `GET /api/conversations/<conversation_id>/todos`

讀取與 `manage_todo_list` 工具相同的 TODO 狀態檔：`chat_history/todos/<conversation_id>.json`。

**成功**：`200`，本體含 `items`（陣列）與 `updated_at`（字串或 `null`）。檔案不存在時回傳空清單。

**事件**：Agent 執行中若工具透過 runtime 送出 `todo_updated`，SSE 串流會帶有 `type: "todo_updated"` 與 `todo_snapshot`。

### `POST /api/chat`

在**背景執行緒**中啟動或延續一次 Agent 執行；請求立即回傳，不等待執行結束。

**`Content-Type`**：`application/json`

**請求本體欄位**：

| 欄位 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `prompt` | 是 | — | 使用者本輪輸入文字；空白則 `400`。 |
| `max_steps` | 否 | `12` | 自主迴圈步數上限（整數）。 |
| `conversation_id` | 否 | 新建立 | 若省略，伺服器會產生新 ID（格式 `web_` + 12 位 hex）。若帶入既有 ID，則延續該對話。 |
| `enable_google_search_grounding` | 否 | `false` | 為 `true` 時啟用 Google 搜尋 grounding，並透過 `request_options` 傳入底層。 |
| `enable_web_search_tool` | 否 | 見下 | 是否註冊 Web 搜尋相關工具。若 `enable_google_search_grounding` 為 `true`，預設為 `false`，避免重複搜尋管道；否則預設為 `true`。 |
| `google_search_exclude_domains` | 否 | — | 若為**字串陣列**，會一併放入 `request_options`。 |

**成功**：`200`，本體例如：

```json
{
  "conversation_id": "web_xxxxxxxxxxxx",
  "runtime_meta": {
    "provider": "gemini",
    "model": "gemini-3-flash-preview"
  }
}
```

`runtime_meta` 在回應當下取自環境變數解析（`LLM_PROVIDER`、`GEMINI_MODEL` 或 `OPENAI_MODEL`）；實際載入後的模型可能以 SSE 中的 `run_started` 為準。

**錯誤**：`400`，本體 `{"error": "prompt is required"}`。

---

## Server-Sent Events：`GET /api/stream/<conversation_id>`

以 **SSE** 推送該對話本次執行期間的事件；瀏覽器可用 `EventSource` 訂閱。

**`Content-Type`**：`text/event-stream`

**行為摘要**（與 `docs/SDK/WebApp-py.json` 的 runtime_notes 一致）：

- 開頭送出 `retry: 1000`。
- 資料列格式為 `data: <JSON>\n\n`，JSON 為單一事件物件。
- 等待期間可能送出註解行 `: keep-alive`。
- 背景執行標記為完成後，送出終止事件：`event: done` 且 `data: {}`，然後關閉串流。

### 事件物件共通欄位

- 多數由 `AgentRuntime._emit_event` 產生的事件會包含：`type`、`conversation_id`、`timestamp`（ISO 8601 字串）。
- 由 `web_app` 在背景 worker 直接發布的事件（`run_started`、`run_finished`、worker 的 `error`）**不一定**帶有 `timestamp`，格式以實際 JSON 為準。

### `type` 一覽（實務上會透過 SSE 收到）

**整合層（`web_app`）**

| `type` | 說明 |
|--------|------|
| `run_started` | 背景執行已建立元件；含 `provider`、`model`（由實際 LLM backend 偵測）。 |
| `run_finished` | 執行結束；`content` 為 `runtime.run(...)` 回傳字串。 |
| `error` | 背景執行未捕捉例外；`content` 為錯誤訊息字串。 |

**執行層（`AgentRuntime`，節錄常見類型）**

| `type` | 說明 |
|--------|------|
| `task_started` | 任務開始；含 `user_message`、`max_steps`。 |
| `step_started` | 新一步開始；含 `step`。 |
| `assistant_content_preview` | 助理文字預覽；含 `step`、`preview`。 |
| `grounding_citations` | Grounding / 搜尋引用；含 `step`、`citations`、`web_search_queries` 等。 |
| `tool_requested` | 模型要求呼叫工具；含 `step`、`tool_name`、`arguments_json`。 |
| `tool_progress` | 工具執行中的進度（由工具透過 `_runtime_event_handler` 推送）。 |
| `todo_updated` | `manage_todo_list` 等工具透過 handler 送出 `phase=todo_updated` 時，runtime 轉發；含 `todo_snapshot`。 |
| `tool_result` | 工具結果；含 `step`、`tool_name`、`content`、`preview` 等。 |
| `tool_result_compressed` / `assistant_content_compressed` | 壓縮節流相關中繼資訊。 |
| `assistant_update` | 無工具呼叫時的助理更新；含 `is_final`、`is_user_handoff`。 |
| `final_answer` | 標記為最終回答（內容含結束標記後）。 |
| `awaiting_user` | 等待使用者回覆（手勢標記）。 |
| `intermediate_update` | 非最終、非手勢的中繼更新。 |
| `error` | 達步數上限等執行層錯誤；含 `step`、`content`。 |

工具或自訂程式碼也可能送出其他形狀的物件；前端除錯時以 `type` 與實際 JSON 為準。

---

## 限制與實作備註

1. **事件儲存為程序內記憶體**：`RuntimeEventStore` 不重啟持久化；重新整理頁面後若要舊串流需重新訂閱，且重啟伺服器後記憶體內事件即消失。
2. **對話內容持久化**：仍由 `LocalChatHistory` 寫入 `chat_history/`，與 SSE 是否連線無關。
3. **無內建驗證**：預設為本機除錯用途；若對外部署請自行加上驗證、HTTPS 與流量限制。

---

## 最小呼叫範例（Python）

```python
import requests

BASE = "http://127.0.0.1:15220"
resp = requests.post(
    f"{BASE}/api/chat",
    json={"prompt": "請用一句話自我介紹", "max_steps": 4},
    timeout=30,
)
resp.raise_for_status()
conversation_id = resp.json()["conversation_id"]
print("conversation_id:", conversation_id)
```

接著以 SSE 客戶端訂閱 `GET /api/stream/{conversation_id}`，並以 `GET /api/conversations/{conversation_id}` 輪詢或重新載入完整訊息列表即可。
