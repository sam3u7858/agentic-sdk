# Agent Builder Guide

If you are responsible for setting up the Agent system or integrating it into an existing project, this guide will show you how to "assemble" a complete operational stack.

## One-Stop Assembly: create_agent_components

To avoid repeating configurations in different places (like CLI tools and the Web UI), we provide an "assembly entry point": `create_agent_components()` in `src/agent_factory.py`.

### What does it do for you?
1. **Load Environment Variables**: Reads API keys via `load_dotenv()`.
2. **Prepare Managers**: Creates `PromptManager` (prompt management) and `SkillRegistry` (skill registration).
3. **Initialize Executor**: Creates `ToolExecutor` and **registers default tools** (e.g., workspace scanning, skill lookup).
4. **Configure Model (LLM)**: Initializes `LMWrapper` and injects the main system prompt.
5. **Connect History & Loop**: Sets up `LocalChatHistory`, `ChatSession`, and finally generates the `AgentRuntime`.

### How to Use
```python
from src.agent_factory import create_agent_components

# Provide a unique conversation ID; the system automatically creates a JSON log file.
components = create_agent_components("my-unique-id")

# Extract the components you need from the returned dictionary
runtime = components["runtime"]
system_prompt = components["system_prompt"]
```

## When to "Assemble Manually"?

While `agent_factory` is convenient, you might need to reference the code in `create_agent_components` and instantiate components yourself if you need:
- **Custom Paths**: Move the prompts folder elsewhere.
- **Custom Toolsets**: Skip default tools and only use your specific ones.
- **Model Switching**: Dynamically decide which LLM provider to use based on logic.

## Core Integration Point
After assembly, the object you'll interact with most is **`AgentRuntime`**. Simply call `runtime.run(message)`, and it will automatically handle the tedious process of chatting with the model, calling tools, and logging history.

---
- Next: [Tool Authoring](06-tool-authoring.md)
- View SDK: [`src.agent_factory`](/docs/module/src.agent_factory)
