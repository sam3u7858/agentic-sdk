# Practice 1: Discord Bot Agent

In this exercise, we will build an expert Agent specialized in writing Discord Bots using `discord.py`. This Agent requires no external APIs; it relies entirely on a custom "Expert Prompt" and a "Standard Operating Procedure (Skill)".

## 1. Create a System Prompt

First, create `discord_expert.md` under the `prompts/` folder:

```markdown
You are a top-tier Python and Discord.py developer.
Your goal is to provide complete, executable Discord Bot code based on user requirements.
You heavily emphasize code security (e.g., never hardcode tokens) and the correct use of asynchronous code.

Currently available skills:
$available_skills
```

## 2. Create a Skill

Create a folder named `discord_dev` under the `skills/` directory.

**`skills/discord_dev/meta.json`**:
```json
{
  "name": "discord_dev",
  "description": "Provides standard architectures and common command templates for discord.py bots.",
  "required_tools": []
}
```

**`skills/discord_dev/instructions.md`**:
```markdown
When writing Discord Bot code, you must follow this standard structure:

1. Use `discord.ext.commands.Bot` instead of the base `Client`.
2. Always load the Token via `os.getenv("DISCORD_TOKEN")`.
3. Provide a template with an `on_ready` event and at least one `!ping` test command.

Template structure:
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

## 3. Assemble and Run

Finally, write a runner script `run_discord_agent.py`:

```python
from src.agent_factory import create_agent_components

# Load components
components = create_agent_components("discord-bot-session")
runtime = components["runtime"]
prompt_manager = components["prompt_manager"]
skill_registry = components["skill_registry"]
llm = components["llm"]

# Swap the system prompt to our expert setting
expert_prompt = prompt_manager.load_prompt(
    "discord_expert", 
    available_skills=skill_registry.get_skill_summaries()
)
llm.set_system_prompt(expert_prompt)

# Execute task
print("🤖 Discord Bot Expert is online!")
task = "Help me write a Discord Bot. Besides the basic ping, it should have a !hello command that returns the user's name."
print(f"User request: {task}\n")

result = runtime.run(task)
print(result)
```

Upon running, you'll see the Agent not only writes the correct code but strictly adheres to the architecture defined in your Skill!