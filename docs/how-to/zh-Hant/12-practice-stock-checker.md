# 實戰練習二：定時撈股票資訊的 Agent

在這個練習中，我們將為 Agent 安裝一雙「手」（自訂 Tool），讓它能夠連上網路獲取真實的股票報價，並將它放進一個無限迴圈中定時執行。

## 1. 開發股票查詢工具 (Tool)

在你的專案中建立一個 `my_tools.py`（或是直接放在 `src/tools/` 下），實作一個簡單的假資料 API 工具（這裡以隨機數模擬，實務上可替換為 Yahoo Finance 或 yfinance 套件）。

```python
import random
from src.ai_core.tool_executor import BaseTool

class GetStockTool(BaseTool):
    @property
    def name(self):
        return "get_stock_price"

    @property
    def description(self):
        return "取得指定股票代碼的目前價格與漲跌幅。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "股票代碼，例如 2330.TW 或 AAPL"}
            },
            "required": ["symbol"]
        }

    def execute(self, symbol: str, **kwargs):
        # 實務上這裡會是呼叫 requests.get(...) 的地方
        base_price = 1000 if "2330" in symbol else 150
        current_price = base_price + random.uniform(-50, 50)
        change_percent = ((current_price - base_price) / base_price) * 100
        
        return f"{symbol} 目前股價: {current_price:.2f}, 漲跌幅: {change_percent:.2f}%"
```

## 2. 註冊工具與建立排程迴圈

建立主程式 `run_stock_agent.py`：

```python
import time
from src.agent_factory import create_agent_components
from my_tools import GetStockTool

def run_scheduler():
    # 1. 初始化 Agent
    components = create_agent_components("stock-monitor")
    runtime = components["runtime"]
    
    # 2. 將新工具註冊進 Agent 的執行器中
    runtime.tool_executor.register_tool(GetStockTool())
    
    print("📈 股票監控 Agent 已啟動！每隔 5 秒檢查一次（為方便測試縮短時間）。")
    
    # 3. 啟動無限迴圈
    iteration = 1
    while True:
        print(f"\n--- 第 {iteration} 次檢查 ---")
        task = (
            "請使用 get_stock_price 工具檢查 2330.TW 的股價。"
            "如果漲跌幅絕對值大於 3%，請用 [警告] 開頭回報；否則簡單回報 [正常] 與價格即可。"
        )
        
        # 限制 max_steps=5 避免模型無窮迴圈
        result = runtime.run(task, max_steps=5)
        print(result)
        
        iteration += 1
        time.sleep(5)  # 實務上可改為 3600 (一小時)

if __name__ == "__main__":
    run_scheduler()
```

執行這個腳本，你就會看到 Agent 成為一個不知疲倦的監控員，自動決定是否要發出警告。