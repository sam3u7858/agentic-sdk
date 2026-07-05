# 工具註冊與 SDK 教學

當你寫好一個自訂工具（繼承自 `BaseTool`）後，你需要將它「註冊」到系統中，Agent 才能在對話中看到並使用它。

## 基本註冊流程：ToolExecutor

所有的工具管理都由 `ToolExecutor` 負責。

```python
from src.ai_core.tool_executor import ToolExecutor
from my_tools import MyAwesomeTool

executor = ToolExecutor()

# 方法 A：註冊單一工具
executor.register_tool(MyAwesomeTool())

# 方法 B：批量註冊
executor.register_tools([
    MyAwesomeTool(),
    AnotherTool()
])
```

## 在 Agent 框架中整合

最推薦的整合方式是修改 `src/agent_factory.py` 裡的 `create_agent_components` 函式。

### 範例：將新工具加入工廠（含網站拓樸、DOM 抓取與安全 HTTP）
1. 開啟 `src/agent_factory.py`。
2. 匯入你的工具類別。
3. 在 `tool_factories` 中加入工具 key 與 factory。
4. （可選）若要允許 readonly 子代理呼叫，加入 `default_allowed_tools`。

```python
# src/agent_factory.py (部分截取)
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

## 進階：動態註冊

如果你不想修改 `agent_factory`，你也可以在取得 `components` 後再動態加入工具：

```python
components = create_agent_components("demo")
runtime = components["runtime"]

# 透過 runtime 取得內部的 executor 並註冊
runtime.tool_executor.register_tool(DynamicTool())

# 現在 runtime.run() 就會包含這個新工具了
runtime.run("請使用動態工具幫我執行任務")
```

## Worker 子代理與 `readonly_subagent` 的差異

- **`readonly_subagent`**：子 runtime 僅能使用白名單內的**唯讀／研究型**工具；**禁止遞迴**呼叫自己；適合長文閱讀、網頁摘要等。
- **`html_worker_subagent`**：獨立類別與**獨立工具表**；子代理可透過 `write_workspace_file` **只寫入 `output/`**，並以 `read_worker_scoped_file` **讀取 `templates/` 與 `output/`**。同樣**禁止**遞迴呼叫 `html_worker_subagent`（亦不得呼叫 `readonly_subagent`）。主代理仍應只讀 template 的 `meta.json`，把 `base.html` 編修交給 worker。

## 疑難排解
- **模型沒呼叫工具**：請檢查 `description` 是否夠清楚，或是否在 `parameters` 中遺漏了必要參數。
- **名稱重複**：`ToolExecutor` 是以工具的 `name` 作為 Key。如果註冊了同名的工具，後者會直接蓋掉前者。

---
- 回到：[Agent 建構者指南](05-builder-guide.md)
- 查看 SDK：[`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
