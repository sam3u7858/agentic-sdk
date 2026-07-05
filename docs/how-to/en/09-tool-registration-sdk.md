# Tool Registration SDK Guide

Once you've written a custom tool (inheriting from `BaseTool`), you need to "register" it with the system so the Agent can see and use it during a conversation.

## Basic Registration: ToolExecutor

All tool management is handled by the `ToolExecutor`.

```python
from src.ai_core.tool_executor import ToolExecutor
from my_tools import MyAwesomeTool

executor = ToolExecutor()

# Method A: Register a single tool
executor.register_tool(MyAwesomeTool())

# Method B: Batch registration
executor.register_tools([
    MyAwesomeTool(),
    AnotherTool()
])
```

## Integration in the Agent Framework

The recommended way to integrate is to modify the `create_agent_components` function in `src/agent_factory.py`.

### Example: Adding New Tools to the Factory (Topology + DOM + Safe HTTP)
1. Open `src/agent_factory.py`.
2. Import your tool class.
3. Add your tool key and factory in `tool_factories`.
4. (Optional) Add it to `default_allowed_tools` for readonly sub-agents.

```python
# src/agent_factory.py (partial snippet)
from src.tools.web_topology_spider import WebTopologySpiderTool
from src.tools.dom_skeleton_xray import DOMSkeletonXrayTool
from src.tools.page_dom_scraper import PageDOMScraperTool
from src.tools.http_request import HttpRequestTool

def create_agent_components(conversation_id, ...):
    # ...
    tool_factories = {
        "scan_workspace": lambda: ScanWorkspaceTool(root_dir=str(PROJECT_ROOT)),
        "lookup_skill": lambda: LookupSkillTool(skill_registry=skill_registry),
        "web_topology_spider": lambda: WebTopologySpiderTool(),
        "dom_skeleton_xray": lambda: DOMSkeletonXrayTool(),
        "scrape_page_dom": lambda: PageDOMScraperTool(),
        "http_request": lambda: HttpRequestTool(),
    }

    sub_allowed = [
        "web_search",
        "scan_workspace",
        "read_workspace_file",
        "summarize_workspace_file",
        "web_topology_spider",
        "dom_skeleton_xray",
        "scrape_page_dom",
        "http_request",
    ]

    tool_executor = ToolExecutor()
    for name in selected_tool_names:
        factory = tool_factories.get(name)
        if factory:
            tool_executor.register_tool(factory())
    # ...
```

## Advanced: Dynamic Registration

If you don't want to modify `agent_factory`, you can also add tools dynamically after getting the `components`:

```python
components = create_agent_components("demo")
runtime = components["runtime"]

# Access the internal executor via runtime and register
runtime.tool_executor.register_tool(DynamicTool())

# Now runtime.run() will include this new tool
runtime.run("Please use the dynamic tool to perform the task")
```

## Troubleshooting
- **Model not calling the tool**: Check if the `description` is clear enough or if mandatory fields are missing in `parameters`.
- **Name conflict**: `ToolExecutor` uses the tool's `name` as a key. Registering a tool with a duplicate name will overwrite the previous one.

---
- Back to: [Agent Builder Guide](05-builder-guide.md)
- View SDK: [`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
