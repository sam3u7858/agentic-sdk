# 零基礎開始：建立與自訂你的第一個 Agent

本指南將帶你從頭開始，學習如何使用本框架建立一個具備思考能力、能執行任務並回報進度的 Agent。我們假設你完全沒有看過之前的內容，這是一份獨立且詳細的開發手冊。

---

## 步驟 0：環境準備

在開始寫程式之前，你需要告訴 Agent 該去哪裡呼叫大語言模型 (LLM)。

1. **建立金鑰**：在專案根目錄建立一個 `.env` 檔案。
2. **填入設定**：
   ```text
   GEMINI_KEY=你的_GEMINI_API_金鑰
   GEMINI_MODEL=gemini-3.1-flash-lite-preview
   ```

---

## 步驟 1：建立 Agent 實例

框架提供了一個「自動化組裝線」函式：`create_agent_components`。它會幫你一次搞定模型設定、提示詞載入與工具註冊。

### 基本程式碼結構
```python
from src.agent_factory import create_agent_components

# 1. 啟動 Agent 元件
# 'my-agent' 是對話 ID，對話紀錄會存成 my-agent.json
components = create_agent_components("my-agent")

# 2. 取得執行迴圈物件 (Runtime)
runtime = components["runtime"]

# 3. 執行任務
task = input("請輸入指令：")
result = runtime.run(task)
print(result)
```

---

## 步驟 2：自訂模型參數與內容

如果你想調整模型的行為（例如讓它更具創造力）或改變它的身分，可以參考以下自訂方法。

### 1. 自訂模型參數 (Temperature, Provider)
你現在可以直接在 `create_agent_components(...)` 傳入 LLM 設定，因此**不需要**為了測試不同模型而去修改 `src/agent_factory.py` 本體。

```python
# 在初始化時直接傳入模型設定：
components = create_agent_components(
    "my-agent",
    provider="gemini", # 也可以是 "openai" 或 "local"
    model="gemini-3.1-pro",
    api_key="YOUR_API_KEY",
    request_options={
        "temperature": 0.7,  # 0.0 最穩定，1.0 最具創意
        "max_tokens": 2048
    }
)
```

如果你使用的是 OpenAI 相容的 provider，例如 `"openai"` 或 `"local"`，也要一起傳入 `lm_api_url`：

```python
components = create_agent_components(
    "my-agent",
    provider="openai",
    model="gpt-4o-mini",
    api_key="YOUR_OPENAI_KEY",
    lm_api_url="https://api.openai.com/v1",
    request_options={
        "temperature": 0.2,
        "max_tokens": 2048
    }
)
```

目前的預設行為仍然維持不變：
- `provider="gemini"`
- `model` 會回退到 `GEMINI_MODEL`
- `api_key` 會回退到 `GEMINI_KEY`

### 2. 導入自訂 Prompt (提示詞管理)
Agent 的「個性」是由 `prompts/` 資料夾下的 Markdown 檔案決定的。
- **在哪裡改？**：去 `prompts/system_core.md` 修改。
- **動態替換**：你在 Markdown 裡寫 `$user_name`，程式碼呼叫 `load_prompt(..., user_name="小明")` 時就會自動替換。這讓你可以根據不同使用者切換身分。

### 3. 自訂 Skill (技能手冊)
技能（Skill）是 Agent 的「大腦筆記」，存在 `skills/` 資料夾下。
- **結構**：一個資料夾代表一個技能（例如 `skills/web_search/`），內含 `meta.json` (名稱) 與 `instructions.md` (詳細步驟)。
- **自動化**：你完全不需要在程式碼中「註冊」技能。只要資料夾放進去，Agent 發現任務需要時，就會自動用 `lookup_skill` 工具去翻閱這本筆記。

### 4. 自動 Tool (工具箱)
工具（Tool）是 Agent 的「手」，讓它可以寫檔、掃描目錄或爬蟲。
- **開發方式**：寫一個 Python 類別繼承 `BaseTool`。
- **註冊方式**：在 `create_agent_components` 內的 `tool_executor.register_tools([...])` 加入你的工具實例。加入後，模型就能在對話中自由呼叫它。

---

## 步驟 3：即時進度回報 (Progress Reporting)

在執行複雜任務時，如果畫面一片空白會讓人很焦慮。你可以自訂一個回報函式來列印 Agent 正在做什麼。

```python
def my_reporter(event):
    etype = event.get("type")
    if etype == "step_started":
        print(f"🌀 Agent 進入第 {event['step']} 步思考...")
    elif etype == "tool_requested":
        print(f"🛠️  模型決定呼叫工具：{event['tool_name']}")
    elif etype == "run_finished":
        print("✅ 任務已成功結束。")

# 將此函式傳入工廠
components = create_agent_components("demo-session", event_handler=my_reporter)
runtime = components["runtime"]
runtime.run("幫我掃描專案目錄並整理出一份摘要")
```

---

## 進階功能實作練習範例

如果你想更上一層樓，可以試著完成以下三個專案練習：

### 1. 生成 Discord Bot Agent
- **任務**：開發一個能根據需求產出完整 Discord.py 程式碼的助手。
- **做法**：在 `skills/` 下新增 `discord_dev` 技能，放進常用的 Bot 設定範本。並在 `prompts/` 建立一個 `discord_expert.md` 作為它的靈魂。

### 2. 定時撈股票資訊的 Agent
- **任務**：每小時自動檢查台股股價。
- **做法**：開發一個繼承 `BaseTool` 的工具 `GetStockTool`，並在主程式寫一個 `while` 迴圈每隔一小時驅動一次 `runtime.run("檢查 2330 股價")`。

### 3. Reddit 自動爬蟲與影片腳本 Agent
- **任務**：每日自動抓取 Reddit 熱門文章並寫成 YouTube 腳本。
- **做法**：寫一個 `RedditTool` 來讀取 Web 內容，並設計一個 `Skill` 定義腳本的固定格式（如：開場白、正文、結尾），讓 Agent 先抓資料再寫作。

---
- 想要了解更底層的程式介面？請參考：[Agent 建構者指南](05-builder-guide.md)
