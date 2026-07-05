# 快速開始

本專案把 **提示詞、技能（Skills）、工具（Tools）、對話紀錄（History）與執行迴圈（AgentRuntime）** 組成一條可重複使用的管線。第一次使用時，建議依序理解三件事：環境、組裝入口、執行方式。

## 你會用到的核心概念

- **`create_agent_components(conversation_id)`**：一次建立 `runtime`、`session`、`llm`、`tool_executor` 等元件，避免各處各自 new 造成設定漂移。
- **`AgentRuntime.run(user_message, max_steps)`**：多步推理迴圈；模型可呼叫工具，結果寫回 history，直到標記結束或達步數上限。
- **`LocalChatHistory`**：預設把每個對話存成 `chat_history/<id>.json`，是除錯與追蹤真相來源（source of truth）。

## 最小程式流程（概念）

1. 準備環境變數（金鑰、模型名稱等，見下一篇〈設定與環境變數〉）。
2. 呼叫 `create_agent_components("my-conv")` 取得 `components`。
3. 取出 `components["runtime"]`，呼叫 `run("你的任務", max_steps=...)`。
4. 需要除錯時，打開對應的 `chat_history` JSON 檔檢視完整訊息與工具輸出。

## 與 Web 除錯 UI 的關係

執行 `web_app.py` 後可用瀏覽器操作同一套 runtime；事件流（SSE）只是把執行過程即時推到畫面上。詳見〈Web 除錯介面〉。

## 下一步

- 閱讀 [設定與環境變數](02-configuration.md)
- 需要架構全貌時閱讀 [執行迴圈、工具與紀錄](04-architecture.md)
