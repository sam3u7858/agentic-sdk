# 實戰練習一：生成 Discord Bot 的 Agent

在這個練習中，我們將打造一個專門幫你寫 Discord Bot (使用 `discord.py`) 的專家 Agent。這個 Agent 的特點是不需要任何外部 API 抓取資料，完全依賴我們賦予它的「專家提示詞」與「標準作業流程 (Skill)」。

## 1. 建立系統提示詞 (Prompt)

首先，在 `prompts/` 資料夾下新增 `discord_expert.md`：

```markdown
你是頂尖的 Python 與 Discord.py 開發者。
你的目標是根據使用者的需求，提供完整、可執行的 Discord Bot 程式碼。
你非常重視程式碼的安全性（例如不要把 Token 硬寫在程式碼中）以及非同步 (async) 的正確用法。

目前可用的技能清單：
$available_skills
```

## 2. 建立技能 (Skill)

在 `skills/` 資料夾下建立一個名為 `discord_dev` 的資料夾。

**`skills/discord_dev/meta.json`**:
```json
{
  "name": "discord_dev",
  "description": "提供 discord.py 機器人的標準架構與常見指令範本。",
  "required_tools": []
}
```

**`skills/discord_dev/instructions.md`**:
```markdown
當你需要撰寫 Discord Bot 程式碼時，請務必遵循以下標準結構：

1. 使用 `discord.ext.commands.Bot` 而不是基礎的 `Client`。
2. 總是透過 `os.getenv("DISCORD_TOKEN")` 來讀取 Token。
3. 提供一個帶有 `on_ready` 事件與至少一個 `!ping` 測試指令的範本。

範本結構如下：
\`\`\`python
import os
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
\`\`\`
```

## 3. 組合與執行

最後，編寫一個啟動腳本 `run_discord_agent.py`：

```python
from src.agent_factory import create_agent_components

# 載入元件
components = create_agent_components("discord-bot-session")
runtime = components["runtime"]
prompt_manager = components["prompt_manager"]
skill_registry = components["skill_registry"]
llm = components["llm"]

# 抽換系統提示詞為我們剛寫好的專家設定
expert_prompt = prompt_manager.load_prompt(
    "discord_expert", 
    available_skills=skill_registry.get_skill_summaries()
)
llm.set_system_prompt(expert_prompt)

# 執行任務
print("🤖 Discord Bot 專家已上線！")
task = "幫我寫一個 Discord Bot，除了基本的 ping，還要有一個 !hello 指令會回傳使用者的名字。"
print(f"使用者要求：{task}\n")

result = runtime.run(task)
print(result)
```

執行後，你會發現 Agent 不僅寫出了正確的程式碼，還嚴格遵守了你在 Skill 中規定的架構！