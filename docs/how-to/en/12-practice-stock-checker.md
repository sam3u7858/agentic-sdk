# Practice 2: Scheduled Stock Checker Agent

In this exercise, we will give the Agent "hands" (a custom Tool) so it can fetch real stock quotes from the internet, and we'll place it in an infinite loop for scheduled execution.

## 1. Develop the Stock Lookup Tool

Create `my_tools.py` (or place it in `src/tools/`) and implement a dummy API tool (using random numbers here, but practically you'd use `yfinance` or a real API).

```python
import random
from src.ai_core.tool_executor import BaseTool

class GetStockTool(BaseTool):
    @property
    def name(self):
        return "get_stock_price"

    @property
    def description(self):
        return "Get the current price and change percentage of a specific stock ticker."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Stock ticker, e.g., NVDA or AAPL"}
            },
            "required": ["symbol"]
        }

    def execute(self, symbol: str, **kwargs):
        # In reality, this would be a requests.get(...) call
        base_price = 150 if "NVDA" in symbol else 200
        current_price = base_price + random.uniform(-10, 10)
        change_percent = ((current_price - base_price) / base_price) * 100
        
        return f"{symbol} current price: {current_price:.2f}, Change: {change_percent:.2f}%"
```

## 2. Register Tool and Create Loop

Create `run_stock_agent.py`:

```python
import time
from src.agent_factory import create_agent_components
from my_tools import GetStockTool

def run_scheduler():
    # 1. Init Agent
    components = create_agent_components("stock-monitor")
    runtime = components["runtime"]
    
    # 2. Register the new tool
    runtime.tool_executor.register_tool(GetStockTool())
    
    print("📈 Stock Monitor Agent started! Checking every 5 seconds (shortened for testing).")
    
    # 3. Infinite loop
    iteration = 1
    while True:
        print(f"\n--- Check #{iteration} ---")
        task = (
            "Please use the get_stock_price tool to check the NVDA stock price. "
            "If the absolute change percentage is > 3%, report starting with [ALERT]; otherwise simply report [NORMAL] and the price."
        )
        
        # Limit max_steps=5 to prevent endless loops
        result = runtime.run(task, max_steps=5)
        print(result)
        
        iteration += 1
        time.sleep(5)  # In reality, change to 3600 (1 hour)

if __name__ == "__main__":
    run_scheduler()
```

Run this script, and your Agent becomes a tireless monitor deciding when to issue alerts!