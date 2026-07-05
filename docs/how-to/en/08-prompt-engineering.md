# Prompt Engineering Tips

In this project, we treat Prompts as a resource, managed uniformly and injected dynamically through the `PromptManager`.

## Using PromptManager

All core prompts are stored as `.md` files in the `prompts/` folder.

### Example: Core System Prompt
Suppose you have `prompts/system_core.md`:
```markdown
You are $agent_name.
Your currently available skills are:
$available_skills
Please assist the user in completing tasks.
```

In your Python code, you can load and replace variables like this:
```python
prompt = prompt_manager.load_prompt(
    "system_core", 
    agent_name="Assistant No. 2",
    available_skills="- Weather Lookup\n- Coding"
)
```

## Where should I put my instructions? (Strategy)

During development, you might wonder whether a set of instructions belongs in the "System Prompt," a "Skill," or a "Tool Description"? Here is our recommendation:

| Content Type | Recommended Location | Reason |
| :--- | :--- | :--- |
| **Agent personality, basic identity, core principles** | System Prompt (`prompts/`) | This is the foundation of the Agent and must exist from the start of the conversation. |
| **Domain-specific SOPs, report formats, workflows** | Skill (`skills/`) | This information is too long and should be "looked up" only when the Agent realizes it's needed. |
| **Tool usage timing, parameter limits, return values** | Tool Description (`BaseTool.description`) | Let the model know what happens when this "button" is pressed. |

## Practical Writing Tips

1. **Variable Substitution**: Use the `$variable` syntax so the same template can adapt to different sessions or roles.
2. **Structured Output**: Explicitly request markers like `<?final>` or `<?ask_user>` in your prompt; these are key to driving `AgentRuntime` to stop or interact.
3. **Less is More**: Keep the system prompt concise and split specific details into corresponding **Skills** to effectively reduce the model's cognitive load and Token consumption.

---
- Next: [Tool Registration SDK](09-tool-registration-sdk.md)
- View SDK: [`src.ai_core.prompt_manager`](/docs/module/src.ai_core.prompt_manager)
