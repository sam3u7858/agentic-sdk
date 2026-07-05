# 演習 1：Discord Bot 生成エージェント

この演習では、`discord.py` を使って Discord Bot を記述することに特化したエキスパートエージェントを構築します。外部 API からデータを取得する必要はなく、「エキスパートプロンプト」と「SOP（スキル）」のみに依存します。

## 1. システムプロンプトの作成

まず、`prompts/` フォルダの下に `discord_expert.md` を作成します。

```markdown
あなたはトップクラスの Python および Discord.py 開発者です。
ユーザーの要件に基づいて、完全で実行可能な Discord Bot のコードを提供することが目標です。
セキュリティ（トークンをコードに直書きしない等）と非同期（async）の正しい使用を非常に重視します。

現在利用可能なスキル：
$available_skills
```

## 2. スキル (Skill) の作成

`skills/` フォルダの下に `discord_dev` フォルダを作成します。

**`skills/discord_dev/meta.json`**:
```json
{
  "name": "discord_dev",
  "description": "discord.py ボットの標準アーキテクチャと一般的なコマンドのテンプレートを提供します。",
  "required_tools": []
}
```

**`skills/discord_dev/instructions.md`**:
```markdown
Discord Bot のコードを書く際は、必ず以下の標準構成に従ってください：

1. 基本の `Client` ではなく、`discord.ext.commands.Bot` を使用する。
2. トークンは必ず `os.getenv("DISCORD_TOKEN")` 経由で読み込む。
3. `on_ready` イベントと、少なくとも1つの `!ping` テストコマンドを含むテンプレートを提供する。

テンプレートの構成：
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

## 3. 組み立てと実行

最後に、起動スクリプト `run_discord_agent.py` を書きます。

```python
from src.agent_factory import create_agent_components

# コンポーネントをロード
components = create_agent_components("discord-bot-session")
runtime = components["runtime"]
prompt_manager = components["prompt_manager"]
skill_registry = components["skill_registry"]
llm = components["llm"]

# システムプロンプトをエキスパート設定に差し替える
expert_prompt = prompt_manager.load_prompt(
    "discord_expert", 
    available_skills=skill_registry.get_skill_summaries()
)
llm.set_system_prompt(expert_prompt)

# タスクの実行
print("🤖 Discord Bot エキスパートがオンラインです！")
task = "Discord Bot を書いてください。基本的な ping 以外に、ユーザーの名前を返す !hello コマンドを持たせてください。"
print(f"ユーザーの要求：{task}\n")

result = runtime.run(task)
print(result)
```

実行すると、エージェントが正しいコードを書くだけでなく、Skill で規定したアーキテクチャを厳格に守っていることが分かります！