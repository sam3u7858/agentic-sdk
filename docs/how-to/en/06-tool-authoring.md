# Tool Authoring

Tools are the Agent's "hands," allowing the model to go beyond text-only conversations and actually execute code or read external data. In this framework, developing tools is very intuitive.

## Inheriting from BaseTool

All tools must inherit from `src.ai_core.tool_executor.BaseTool` and implement these four members:

### 1. name
**ID for the model.** Only alphanumeric characters and underscores are allowed. Example: `search_database`.

### 2. description
**Guide for the model.** This is the most critical part! You need to tell the model "when to call this tool." Example: "Use this tool when the user asks about order status."

### 3. parameters
**JSON Schema.** Defines what parameters your tool accepts, their types, and which are required. The model uses this definition to generate call instructions.

### 4. execute()
**Actual Python logic.** This is where you write your code.
- **Input**: Matches the key-value pairs defined in `parameters`.
- **Output**: Must return a **plain string**. If your result is an object or list, JSON dump it or convert it to readable text first.

## Example: Weather Lookup Tool

```python
from src.ai_core.tool_executor import BaseTool

class GetWeatherTool(BaseTool):
    @property
    def name(self):
        return "get_weather"

    @property
    def description(self):
        return "Gets the current weather for a specified city."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g., Taipei"}
            },
            "required": ["city"]
        }

    def execute(self, city: str, **kwargs):
        # Simulated API call
        return f"The weather in {city} is: Sunny, 25 degrees."
```

## Important Notes
- **Error Handling**: If `execute()` fails, catch the exception and return an error message string (e.g., `Error: City not found`) instead of letting the program crash. Models usually try to fix it or report it to the user.
- **Security**: Remember, the model generates parameters. If your tool deletes files or executes SQL, make sure to validate inputs properly!

---
- Next: [Skill Authoring](07-skill-authoring.md)
- Register your tool: [Tool Registration SDK](09-tool-registration-sdk.md)
- View SDK: [`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
