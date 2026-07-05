# Quick start

This project wires **prompts, skills, tools, chat history, and the autonomous loop (`AgentRuntime`)** into a reusable pipeline. When you are new to the repo, focus on three ideas: **environment**, **composition root**, and **execution**.

## Core concepts

- **`create_agent_components(conversation_id)`** builds `runtime`, `session`, `llm`, `tool_executor`, etc. in one place to avoid configuration drift.
- **`AgentRuntime.run(user_message, max_steps)`** runs a multi-step loop: the model may call tools; results are written back to history until a marker stops the loop or `max_steps` is hit.
- **`LocalChatHistory`** stores one JSON file per conversation under `chat_history/`. Treat it as the **source of truth** for debugging.

## Minimal mental model

1. Configure environment variables (keys, model names—see [Configuration](02-configuration.md)).
2. Call `create_agent_components("my-conv")` and keep the returned `components` dict.
3. Use `components["runtime"].run("your task", max_steps=...)`.
4. When something looks wrong, open the matching `chat_history` JSON and read the full transcript.

## Relation to the web debug UI

Running `web_app.py` drives the same runtime from the browser; SSE streams runtime events to the UI. See [Web debug UI](03-web-ui.md).

## Next

- [Configuration](02-configuration.md)
- [Runtime, tools, and history](04-architecture.md)
