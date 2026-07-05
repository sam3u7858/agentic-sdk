# 執行迴圈、工具與紀錄

這一篇用「閱讀者視角」說明 **AgentRuntime** 如何與 **ToolExecutor**、**LocalChatHistory** 協作。

## 資料流（簡化）

1. 使用者訊息寫入 history。
2. 模型根據完整 history 產生回覆；若包含 **tool_calls**，runtime 會先記錄 assistant 內容，再逐一執行工具。
3. 每個工具結果以 `role=tool`（或專案約定的格式）寫回 history。
4. 迴圈持續直到：
   - 偵測到 **結束標記**（final markers），或
   - 偵測到 **需要使用者補充** 的標記（ask-user markers），或
   - 達到 **max_steps**。

## 為什麼要以 history 為中心？

- JSON 檔案讓你能 **重播** 一整次推理與工具呼叫。
- Web UI 與 CLI 若都走同一組 factory/runtime，行為較不會分叉。

## 工具（Tools）與技能（Skills）

- **工具**：可執行、會改變外部狀態或讀取檔案（例如掃描工作區、讀取 materials）。
- **技能**：多為 **SOP 文字**；透過 `lookup_skill` 類工具取出後，供模型依指示產出，**不應**被當成可呼叫的程式工具。

**Orchestrator（主代理）與 HTML Worker**：主代理用 `list_video_templates` / `read_video_template` 只看到 **`meta.json`** 與摘要，避免把完整 HTML 塞進對話上下文；版型與大段 HTML 的修改透過 **`html_worker_subagent`** 在獨立子 runtime 完成，寫入僅限 **`output/`**，以縮小權限面積並節省 token。

**模板 SOP 與技能 SOP**：可重複使用的 HTML／視覺規格放在 `templates/<id>/`（例如 `system_prompt.md`）；跨專案的操作守則放在 `skills/<name>/`，由 `SkillRegistry` 載入摘要、`lookup_skill` 按需載入全文。

## SDK 文件怎麼讀？

- 先看模組頁頂端的 **閱讀指南（Reader guide）**（多語說明）。
- 再點進各 **Symbol** 看簽名、參數與行為備註；需要範例時參考 JSON 內的 `examples`。

## 相關條目

- `src.agent_factory`：組裝堆疊。
- `src.ai_core.runtime`：`AgentRuntime` 主迴圈。
- `src.ai_core.tool_executor`：工具註冊與執行。
- `src.ai_core.history`：`LocalChatHistory` 儲存格式與行為。
