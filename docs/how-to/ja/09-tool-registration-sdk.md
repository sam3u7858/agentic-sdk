# ツール登録と SDK ガイド

カスタムツール（`BaseTool` を継承したもの）を作成したら、それをシステムに「登録」する必要があります。これにより、エージェントは対話の中でそのツールを認識し、使用できるようになります。

## 基本的な登録フロー：ToolExecutor

すべてのツール管理は `ToolExecutor` が担当します。

```python
from src.ai_core.tool_executor import ToolExecutor
from my_tools import MyAwesomeTool

executor = ToolExecutor()

# 方法A：単一ツールの登録
executor.register_tool(MyAwesomeTool())

# 方法B：一括登録
executor.register_tools([
    MyAwesomeTool(),
    AnotherTool()
])
```

## エージェントフレームワークへの統合

最も推奨される統合方法は、`src/agent_factory.py` 内の `create_agent_components` 関数を修正することです。

### 例：新しいツールをファクトリに追加する（Topology + DOM + Safe HTTP）
1. `src/agent_factory.py` を開きます。
2. 作成したツールクラスをインポートします。
3. `tool_factories` にツールの key と factory を追加します。
4. （任意）readonly sub-agent で使う場合は `default_allowed_tools` に追加します。

```python
# src/agent_factory.py (一部抜粋)
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

## 応用：動的登録

`agent_factory` を修正したくない場合は、`components` を取得した後に動的にツールを追加することも可能です：

```python
components = create_agent_components("demo")
runtime = components["runtime"]

# runtime を通じて内部の executor にアクセスし登録
runtime.tool_executor.register_tool(DynamicTool())

# これで runtime.run() の実行時に新しいツールが含まれるようになります
runtime.run("動的ツールを使ってタスクを実行してください")
```

## トラブルシューティング
- **モデルがツールを呼び出さない**：`description` が十分に明確か、あるいは `parameters` で必要なパラメータが漏れていないか確認してください。
- **名前の重複**：`ToolExecutor` はツールの `name` をキーとして使用します。同名のツールを登録した場合、後のものが前のものを上書きします。

---
- 戻る：[エージェント構築ガイド](05-builder-guide.md)
- SDKを表示：[`src.ai_core.tool_executor`](/docs/module/src.ai_core.tool_executor)
