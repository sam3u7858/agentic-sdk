# Starting from Zero: Build and Customize Your First Agent

This guide will take you from the very beginning, teaching you how to use this framework to create an Agent that can think, execute tasks, and report progress. We assume you haven't read any previous content—this is a standalone, detailed manual.

---

## Step 0: Preparation

Before writing code, you need to tell the Agent where to call the Large Language Model (LLM).

1. **Create Env File**: Create a `.env` file in the project root.
2. **Fill in Settings**:
   ```text
   GEMINI_KEY=YOUR_GEMINI_API_KEY
   GEMINI_MODEL=gemini-3.1-flash-lite-preview
   ```

---

## Step 1: Create an Agent Instance

The framework provides an "automated assembly line" function: `create_agent_components`. It handles model configuration, prompt loading, and tool registration in one go.

### Basic Code Structure
```python
from src.agent_factory import create_agent_components

# 1. Initialize Agent components
# 'my-agent' is the conversation ID; logs will be saved as my-agent.json
components = create_agent_components("my-agent")

# 2. Get the execution loop object (Runtime)
runtime = components["runtime"]

# 3. Execute task
task = input("Enter your command: ")
result = runtime.run(task)
print(result)
```

---

## Step 2: Customizing Model Parameters and Content

If you want to adjust the model's behavior (e.g., make it more creative) or change its personality, refer to the following methods.

### 1. Customize Model Parameters (Temperature, Provider)
You can now pass LLM settings directly into `create_agent_components(...)`, so you do **not** need to edit `src/agent_factory.py` just to test a different model setup.

```python
# Pass model settings during initialization:
components = create_agent_components(
    "my-agent",
    provider="gemini", # Can also be "openai" or "local"
    model="gemini-3.1-pro",
    api_key="YOUR_API_KEY",
    request_options={
        "temperature": 0.7,  # 0.0 for stability, 1.0 for creativity
        "max_tokens": 2048
    }
)
```

If you use an OpenAI-compatible provider such as `"openai"` or `"local"`, also pass `lm_api_url`:

```python
components = create_agent_components(
    "my-agent",
    provider="openai",
    model="gpt-4o-mini",
    api_key="YOUR_OPENAI_KEY",
    lm_api_url="https://api.openai.com/v1",
    request_options={
        "temperature": 0.2,
        "max_tokens": 2048
    }
)
```

The default behavior is still the same:
- `provider="gemini"`
- `model` falls back to `GEMINI_MODEL`
- `api_key` falls back to `GEMINI_KEY`

### 2. Custom Prompt Management
The Agent's "personality" is determined by Markdown files in the `prompts/` folder.
- **Where to change?**: Edit `prompts/system_core.md`.
- **Dynamic Substitution**: Use `$user_name` in Markdown, and call `load_prompt(..., user_name="Alex")` in code to automatically replace it. This allows you to switch identities based on the user.

### 3. Custom Skills (The Manual)
Skills are the Agent's "mental notes," stored in the `skills/` folder.
- **Structure**: Each folder represents a skill (e.g., `skills/web_search/`), containing `meta.json` (name) and `instructions.md` (detailed steps).
- **Automation**: You don't need to manually register skills in code. Just add the folder, and the Agent will automatically use the `lookup_skill` tool to read the manual when needed.

### 4. Automatic Tools (The Toolbox)
Tools are the Agent's "hands," allowing it to write files, scan directories, or crawl the web.
- **Development**: Write a Python class inheriting from `BaseTool`.
- **Registration**: Add your tool instance to `tool_executor.register_tools([...])` inside `create_agent_components`.

---

## Step 3: Real-time Progress Reporting

When executing complex tasks, a blank screen can be anxious. You can customize a reporter function to print what the Agent is doing.

```python
def my_reporter(event):
    etype = event.get("type")
    if etype == "step_started":
        print(f"🌀 Agent is thinking (Step {event['step']})...")
    elif etype == "tool_requested":
        print(f"🛠️  Model decided to call tool: {event['tool_name']}")
    elif etype == "run_finished":
        print("✅ Task successfully completed.")

# Pass this function to the factory
components = create_agent_components("demo-session", event_handler=my_reporter)
runtime = components["runtime"]
runtime.run("Scan the project directory and generate a summary")
```

---

## Advanced Practice Examples

If you want to take it to the next level, try these three project exercises:

### 1. Discord Bot Agent
- **Task**: An assistant that generates complete Discord.py code based on requirements.
- **How**: Add a `discord_dev` skill in `skills/` with common templates, and create `discord_expert.md` in `prompts/` as its soul.

### 2. Scheduled Stock Checker Agent
- **Task**: Automatically check stock prices every hour.
- **How**: Create a `GetStockTool` inheriting from `BaseTool`, and use a `while` loop in your main script to call `runtime.run("Check NVDA price")` every hour.

### 3. Reddit Crawler & Video Script Agent
- **Task**: Daily crawl of Reddit top posts to generate a YouTube script.
- **How**: Write a `RedditTool` to read web content and design a `Skill` to define script formats (Hook, Body, Outro).

---
- Want to know more about low-level APIs? See: [Agent Builder Guide](05-builder-guide.md)
