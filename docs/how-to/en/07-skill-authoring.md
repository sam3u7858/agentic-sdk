# Skill Authoring

If Tools are the Agent's "hands," then Skills are the Agent's "mental manual."

A Skill is not code, but a **high-quality set of Markdown instructions (SOP)**. It tells the model how to use existing tools, follow a specific style, or produce structured results.

## Skill File Structure

All skills are stored in the `skills/` folder. Each skill is a separate subfolder:

```text
skills/
  └── video_planner/
      ├── meta.json        # Skill ID card (name, intro, dependencies)
      └── instructions.md  # Core logic (specific SOP instructions)
```

### 1. meta.json
Defines how the skill is retrieved:
- `name`: Skill name (e.g., `video_planner`).
- `description`: Short description helping the model decide whether to use this skill during a search.
- `required_tools`: A list of Tools needed for this skill (currently for reference and UI labels).

### 2. instructions.md
Where you apply your Prompt Engineering. Write it like the rules you give in a regular ChatGPT conversation:
- Set the context (e.g., "You are a professional video planner...")
- Specify output formats (e.g., "Always output in JSON format...")
- Step-by-step guidance (e.g., "Step 1: Scan the workspace, Step 2: ...")

## Why use Skills?

1. **Save Context Space**: You don't need to stuff all SOPs into the System Prompt at once. The Agent uses the `lookup_skill` tool to fetch the relevant manual only when needed.
2. **Modular Management**: To teach the Agent "website translation," just add a `translator` folder without touching core code.

## Core Concept
**Skills are not executable programs!** 
The text you write in `instructions.md` is eventually "read" by the model and added to the conversation context. The model reads this manual and then **calls actual Tools according to the instructions**.

---
- Next: [Prompt Engineering](08-prompt-engineering.md)
- View SDK: [`src.ai_core.skill_registry`](/docs/module/src.ai_core.skill_registry)
