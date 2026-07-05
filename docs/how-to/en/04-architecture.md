# Runtime, tools, and history

This page explains how **`AgentRuntime`**, **`ToolExecutor`**, and **`LocalChatHistory`** work together—written for humans, not just type signatures.

## Simplified data flow

1. The user message is appended to history.
2. The model reads the full history. If it returns **tool calls**, the runtime records assistant content, executes each tool, and appends tool results back to history.
3. The loop continues until:
   - a **final marker** is detected,
   - an **ask-user** marker requests clarification, or
   - **`max_steps`** is reached.

## Why history-first?

- JSON transcripts make it easy to **replay** reasoning and tool I/O.
- If both CLI and web use the same factory/runtime, behavior stays aligned.

## Tools vs skills

- **Tools** perform side effects or fetch data (workspace scan, read materials, etc.).
- **Skills** are usually **SOP text** loaded via something like `lookup_skill`. They guide the model but must **not** be treated as executable code tools.

**Orchestrator vs HTML worker**: the host agent should prefer `list_video_templates` / `read_video_template` (metadata only) and delegate HTML edits to **`html_worker_subagent`**, which may write **only** under **`output/`** in a separate child runtime—this keeps large HTML out of the main context and reduces side-effect surface area.

**Templates vs skills**: reusable HTML/visual instructions live under `templates/<id>/` (for example `system_prompt.md`). Cross-cutting playbooks live under `skills/<name>/` and are surfaced via `SkillRegistry` / `lookup_skill`.

## How to read the SDK JSON docs

- Start with the **Reader guide** block at the top of each module page (multi-language prose).
- Drill into **symbols** for signatures, parameters, and behavior notes; use **`examples`** when you need copy-paste starters.

## Pointers

- `src.agent_factory` — composition root.
- `src.ai_core.runtime` — autonomous loop.
- `src.ai_core.tool_executor` — registration + execution.
- `src.ai_core.history` — file layout and listing semantics.
