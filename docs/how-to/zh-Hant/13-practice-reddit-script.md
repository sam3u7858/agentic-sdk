# 實戰練習三：Reddit 爬蟲與影片腳本 Agent

這個練習是最綜合的應用：結合 **Tool (爬取外部資料)** 與 **Skill (結構化腳本寫作)**，讓 Agent 完成一條自動化的內容產出工作流。

## 1. 開發 Reddit 爬蟲工具

建立一個使用 `requests` 的工具來讀取 Reddit 的 JSON API。

```python
import requests
from src.ai_core.tool_executor import BaseTool

class RedditCrawlerTool(BaseTool):
    @property
    def name(self):
        return "crawl_reddit_tech"

    @property
    def description(self):
        return "抓取 Reddit r/technology 看板的最新前 3 篇熱門文章標題。"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {}, # 這個工具不需要參數
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
                
            return "最新科技新聞：\n" + "\n".join(posts)
        except Exception as e:
            return f"讀取失敗：{str(e)}"
```

## 2. 建立腳本寫作技能

在 `skills/shorts_script_writer/` 建立技能：

**`meta.json`**:
```json
{
  "name": "shorts_script_writer",
  "description": "將科技新聞轉換為 60 秒 YouTube Shorts 短影音腳本格式。"
}
```

**`instructions.md`**:
```markdown
當你需要撰寫 YouTube Shorts 腳本時，請嚴格遵守以下格式：

【Hook 開場 (0-5秒)】
用一句話抓住觀眾注意力！(例如：「你絕對不敢相信...」)

【Body 正文 (5-45秒)】
用口語化的方式介紹剛剛抓取到的科技新聞重點。

【Outro 結尾 (45-60秒)】
引導觀眾留言討論，並要求訂閱。
```

## 3. 整合工作流

建立主程式 `run_content_agent.py`：

```python
from src.agent_factory import create_agent_components
# 假設 RedditCrawlerTool 存在 my_tools.py 中
from my_tools import RedditCrawlerTool

# 1. 初始化
components = create_agent_components("reddit-content-creator")
runtime = components["runtime"]

# 2. 註冊爬蟲工具
runtime.tool_executor.register_tool(RedditCrawlerTool())

# 3. 給予組合任務
task = (
    "請先使用 crawl_reddit_tech 工具抓取今天最新的科技新聞。\n"
    "然後閱讀 shorts_script_writer 技能，將這些新聞寫成一段 YouTube 短影音腳本。"
)

print("🎬 內容創作 Agent 開始工作...")
result = runtime.run(task, max_steps=15)

print("\n=== 最終產出 ===")
print(result)
```

在這個案例中，你會看到模型先主動呼叫 `crawl_reddit_tech`，接著再呼叫 `lookup_skill` 查詢 `shorts_script_writer`，最後融合兩者的資訊，漂亮地輸出最終腳本！