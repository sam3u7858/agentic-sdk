# 演習 2：株価情報の定時取得エージェント

この演習では、エージェントに「手」（カスタム Tool）を取り付け、インターネット経由で実際の株価を取得できるようにし、無限ループに入れて定時実行させます。

## 1. 株価検索ツールの開発

プロジェクト内に `my_tools.py`（または `src/tools/` の下）を作成し、ダミーAPIツールを実装します（ここでは乱数でシミュレートしますが、実際には Yahoo Finance API などに置き換え可能です）。

```python
import random
from src.ai_core.tool_executor import BaseTool

class GetStockTool(BaseTool):
    @property
    def name(self):
        return "get_stock_price"

    @property
    def description(self):
        return "指定されたティッカーシンボルの現在の価格と変動率を取得します。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "ティッカーシンボル（例: AAPL）"}
            },
            "required": ["symbol"]
        }

    def execute(self, symbol: str, **kwargs):
        # 実際には requests.get(...) などを呼び出す
        base_price = 150 if "AAPL" in symbol else 100
        current_price = base_price + random.uniform(-5, 5)
        change_percent = ((current_price - base_price) / base_price) * 100
        
        return f"{symbol} の現在の株価: {current_price:.2f}, 変動率: {change_percent:.2f}%"
```

## 2. ツールの登録とスケジューラループの作成

メインプログラム `run_stock_agent.py` を作成します。

```python
import time
from src.agent_factory import create_agent_components
from my_tools import GetStockTool

def run_scheduler():
    # 1. エージェントの初期化
    components = create_agent_components("stock-monitor")
    runtime = components["runtime"]
    
    # 2. 新しいツールをエージェントの実行器に登録
    runtime.tool_executor.register_tool(GetStockTool())
    
    print("📈 株価監視エージェントが起動しました！ 5秒ごとにチェックします（テスト用に短縮）。")
    
    # 3. 無限ループの起動
    iteration = 1
    while True:
        print(f"\n--- 第 {iteration} 回チェック ---")
        task = (
            "get_stock_price ツールを使って AAPL の株価をチェックしてください。"
            "変動率の絶対値が 3% を超える場合は [警告] から始めて報告し、それ以外は単に [正常] と価格を報告してください。"
        )
        
        # 無限ループを避けるため max_steps=5 に制限
        result = runtime.run(task, max_steps=5)
        print(result)
        
        iteration += 1
        time.sleep(5)  # 実際は 3600 (1時間) などに変更

if __name__ == "__main__":
    run_scheduler()
```

このスクリプトを実行すると、エージェントが疲れを知らない監視員となり、警告を発するかどうかを自動で判断するようになります。