# Agent 建構者指南

如果你是負責把整個 Agent 系統搭建起來、或是想在現有專案中整合的人，這篇指南會告訴你如何「組裝」出一個完整的運作堆疊。

## 一站式組裝：create_agent_components

為了避免在不同地方（例如 CLI 工具與 Web UI）重複編寫設定，我們提供了一個「組裝入口」：`src/agent_factory.py` 中的 `create_agent_components()`。

### 它幫你做了什麼？
1. **載入環境變數**：透過 `load_dotenv()` 讀取 API 金鑰。
2. **準備經理人**：建立 `PromptManager`（提示詞管理）與 `SkillRegistry`（技能註冊）。
3. **初始化執行器**：建立 `ToolExecutor` 並**註冊預設工具**（如掃描工作區、查詢技能）。
4. **設定模型 (LLM)**：初始化 `LMWrapper` 並注入主系統提示詞。
5. **串接歷史與運行迴圈**：建立 `LocalChatHistory`、`ChatSession` 並最終產生 `AgentRuntime`。

### 如何使用
```python
from src.agent_factory import create_agent_components

# 給予一個唯一的對話 ID，系統會自動建立對應的 JSON 紀錄檔
components = create_agent_components("my-unique-id")

# 從回傳的字典中取出需要的元件
runtime = components["runtime"]
system_prompt = components["system_prompt"]
```

## 什麼時候該「手動組裝」？

雖然 `agent_factory` 很方便，但如果你有以下需求，可能需要參考 `create_agent_components` 的程式碼並自行 new 元件：
- **更換存取路徑**：想把 prompts 資料夾移到其他地方。
- **自訂工具集**：不想載入預設的素材管理工具，只想用你寫的特定 Tool。
- **多模型切換**：想根據邏輯動態決定使用哪一個 LLM provider。

## 核心整合點
組裝完成後，你最常互動的物件是 **`AgentRuntime`**。只需呼叫 `runtime.run(message)`，它就會自動處理與模型對話、呼叫工具、紀錄歷史的所有繁瑣過程。

---
- 接下來：[開發自訂工具 (Tool)](06-tool-authoring.md)
- 查看 SDK：[`src.agent_factory`](/docs/module/src.agent_factory)
