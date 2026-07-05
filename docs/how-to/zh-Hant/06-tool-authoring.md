# 開發自訂工具 (Tool)

工具（Tool）是 Agent 的「手」，讓模型能夠走出純文字對話，真正執行程式碼或讀取外部資料。在本框架中，開發工具非常直覺。

## 繼承 BaseTool

所有工具都必須繼承自 `src.ai_core.tool_executor.BaseTool`，並實作以下四個成員：

### 1. name
**給模型看的 ID。** 只能包含英數字與下底線。例如 `search_database`。

### 2. description
**給模型看的指南。** 這是最關鍵的部分！你要告訴模型「什麼時候該呼叫這個工具」。例如：「當使用者詢問訂單狀態時使用此工具。」

### 3. parameters
**JSON Schema。** 定義你的工具接受哪些參數、類型是什麼、哪些是必填。模型會根據這個定義來產生呼叫指令。

### 4. execute()
**實際執行的 Python 程式碼。** 這裡是你寫邏輯的地方。
- **輸入**：對應 parameters 定義的 key-value 對。
- **輸出**：必須回傳**純字串**。如果你的結果是物件或清單，請先 JSON dump 或是轉成可讀文字。

## 範例：天氣查詢工具

```python
from src.ai_core.tool_executor import BaseTool

class GetWeatherTool(BaseTool):
    @property
    def name(self):
        return "get_weather"

    @property
    def description(self):
        return "取得指定城市的目前天氣。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名稱，例如：台北"}
            },
            "required": ["city"]
        }

    def execute(self, city: str, **kwargs):
        # 這裡模擬 API 呼叫
        return f"{city} 的天氣是：晴天，25度。"
```

## 注意事項
- **容錯處理**：如果 `execute()` 失敗了，建議捕捉例外並回傳錯誤訊息字串（例如 `Error: 找不到該城市`），而不是讓程式直接 crash。模型看到錯誤訊息後，通常會嘗試修正或向使用者回報。
- **安全**：請記住，模型會產生參數傳入。如果你的工具會刪除檔案或執行 SQL，請務必做好驗證！

---
- 接下來：[撰寫技能 SOP (Skill)](07-skill-authoring.md)
- 註冊你的工具：[工具註冊與 SDK 教學](09-tool-registration-sdk.md)
- 查看 SDK：[`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
