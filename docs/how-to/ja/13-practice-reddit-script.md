# 演習 3：Reddit クローラー & 動画台本生成エージェント

この演習は最も総合的なアプリケーションです。**Tool（外部データの取得）** と **Skill（構造化された台本執筆）** を組み合わせ、エージェントにコンテンツ制作の自動化ワークフローを完了させます。

## 1. Reddit クローラーツールの開発

`requests` を使用して Reddit の JSON API を読み取るツールを作成します。

```python
import requests
from src.ai_core.tool_executor import BaseTool

class RedditCrawlerTool(BaseTool):
    @property
    def name(self):
        return "crawl_reddit_tech"

    @property
    def description(self):
        return "Reddit の r/technology から最新のホットな投稿の上位3件のタイトルを取得します。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {}, # パラメータ不要
            "required": []
        }

    def execute(self, **kwargs):
        headers = {'User-Agent': 'Mozilla/5.0'}
        try:
            url = "https://www.reddit.com/r/technology/hot.json?limit=3"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            posts = []
            for child in data['data']['children']:
                posts.append(child['data']['title'])
                
            return "最新のテクノロジーニュース：\n" + "\n".join(posts)
        except Exception as e:
            return f"取得失敗：{str(e)}"
```

## 2. 台本執筆スキルの作成

`skills/shorts_script_writer/` にスキルを作成します。

**`meta.json`**:
```json
{
  "name": "shorts_script_writer",
  "description": "テクノロジーニュースを60秒の YouTube Shorts 台本形式に変換します。"
}
```

**`instructions.md`**:
```markdown
YouTube Shorts の台本を書く際は、以下の形式を厳守してください：

【Hook（フック） (0-5秒)】
一言で視聴者の注意を引く！（例：「絶対に信じられないでしょうが…」）

【Body（本編） (5-45秒)】
取得したテクノロジーニュースのポイントを話し言葉で紹介する。

【Outro（エンディング） (45-60秒)】
コメントでの議論を促し、チャンネル登録をお願いする。
```

## 3. ワークフローの統合

メインプログラム `run_content_agent.py` を作成します。

```python
from src.agent_factory import create_agent_components
from my_tools import RedditCrawlerTool

# 1. 初期化
components = create_agent_components("reddit-content-creator")
runtime = components["runtime"]

# 2. クローラーツールの登録
runtime.tool_executor.register_tool(RedditCrawlerTool())

# 3. 複合タスクの指示
task = (
    "まず crawl_reddit_tech を使って今日の最新テクノロジーニュースを取得してください。\n"
    "その後、shorts_script_writer スキルを読み、これらのニュースを YouTube Shorts の台本に書き起こしてください。"
)

print("🎬 コンテンツ制作エージェントが作業を開始しました...")
result = runtime.run(task, max_steps=15)

print("\n=== 最終出力 ===")
print(result)
```

このシナリオでは、モデルが自発的に `crawl_reddit_tech` を呼び出し、次に `lookup_skill` を呼び出して `shorts_script_writer` を調べ、最後に両方の情報を統合して見事な動画台本を出力する様子が見られます！