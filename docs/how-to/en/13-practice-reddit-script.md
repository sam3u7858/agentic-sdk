# Practice 3: Reddit Crawler & Video Script Agent

This exercise is a comprehensive application combining a **Tool (web crawling)** and a **Skill (structured script writing)** to build an automated content generation pipeline.

## 1. Develop the Reddit Crawler Tool

Create a tool using `requests` to read Reddit's JSON API.

```python
import requests
from src.ai_core.tool_executor import BaseTool

class RedditCrawlerTool(BaseTool):
    @property
    def name(self):
        return "crawl_reddit_tech"

    @property
    def description(self):
        return "Fetch the top 3 hot post titles from Reddit's r/technology."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {}, # No parameters needed
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
                
            return "Latest tech news:\n" + "\n".join(posts)
        except Exception as e:
            return f"Fetch failed: {str(e)}"
```

## 2. Create the Script Writer Skill

Create the skill in `skills/shorts_script_writer/`:

**`meta.json`**:
```json
{
  "name": "shorts_script_writer",
  "description": "Convert tech news into a 60-second YouTube Shorts script format."
}
```

**`instructions.md`**:
```markdown
When writing a YouTube Shorts script, strictly follow this format:

[Hook (0-5s)]
Grab the audience's attention in one sentence! (e.g., "You won't believe...")

[Body (5-45s)]
Introduce the key points of the fetched tech news in a conversational tone.

[Outro (45-60s)]
Prompt the audience to comment and subscribe.
```

## 3. Integrate the Workflow

Create `run_content_agent.py`:

```python
from src.agent_factory import create_agent_components
from my_tools import RedditCrawlerTool

# 1. Init
components = create_agent_components("reddit-content-creator")
runtime = components["runtime"]

# 2. Register Crawler Tool
runtime.tool_executor.register_tool(RedditCrawlerTool())

# 3. Give Combined Task
task = (
    "Please use crawl_reddit_tech to fetch today's latest tech news. "
    "Then read the shorts_script_writer skill and turn the news into a YouTube Shorts script."
)

print("🎬 Content Creator Agent is working...")
result = runtime.run(task, max_steps=15)

print("\n=== Final Output ===")
print(result)
```

In this scenario, the model will actively call `crawl_reddit_tech`, then call `lookup_skill` to read `shorts_script_writer`, and finally merge both to output a polished video script!