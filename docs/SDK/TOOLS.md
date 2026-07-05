# Agent 工具 SDK 總覽

本頁列出透過 `create_agent_components()` 註冊、可供主模型呼叫的 **工具（BaseTool）**，並對應到 `docs/SDK/` 內的機讀說明檔（`sdk.reference.v1` JSON）。啟動 `web_app.py` 後可在 **`/docs`** 以側欄瀏覽相同內容。

## 工具一覽（註冊名稱 → 類別）

| 註冊名稱                           | Python 類別                     | 原始檔                                      | SDK 文件                                                               |
| ---------------------------------- | ------------------------------- | ------------------------------------------- | ---------------------------------------------------------------------- |
| `scan_workspace`                   | `ScanWorkspaceTool`             | `src/tools/workspace_scout.py`              | [WorkspaceScout-py.json](WorkspaceScout-py.json)                       |
| `lookup_skill`                     | `LookupSkillTool`               | `src/tools/skill_manager.py`                | [SkillManager-py.json](SkillManager-py.json)                           |
| `list_materials`                   | `ListMaterialsTool`             | `src/tools/materials_manager.py`            | [MaterialsManager-py.json](MaterialsManager-py.json)                   |
| `read_material`                    | `ReadMaterialTool`              | 同上                                        | 同上                                                                   |
| `summarize_material`               | `SummarizeMaterialTool`         | 同上                                        | 同上                                                                   |
| `read_workspace_file`              | `ReadWorkspaceFileTool`         | `src/tools/workspace_reader.py`             | [WorkspaceReader-py.json](WorkspaceReader-py.json)                     |
| `summarize_workspace_file`         | `SummarizeWorkspaceFileTool`    | 同上                                        | 同上                                                                   |
| `web_topology_spider`              | `WebTopologySpiderTool`         | `src/tools/web_topology_spider.py`          | [WebTopologySpider-py.json](WebTopologySpider-py.json)                 |
| `dom_skeleton_xray`                | `DOMSkeletonXrayTool`           | `src/tools/dom_skeleton_xray.py`            | [DOMSkeletonXray-py.json](DOMSkeletonXray-py.json)                     |
| `scrape_page_dom`                  | `PageDOMScraperTool`            | `src/tools/page_dom_scraper.py`             | [PageDOMScraper-py.json](PageDOMScraper-py.json)                       |
| `http_request`                     | `HttpRequestTool`               | `src/tools/http_request.py`                 | [HttpRequest-py.json](HttpRequest-py.json)                             |
| `summarize_url_with_secondary_llm` | `URLSecondaryLLMSummarizerTool` | `src/tools/url_secondary_llm_summarizer.py` | [URLSecondaryLLMSummarizer-py.json](URLSecondaryLLMSummarizer-py.json) |
| `web_search`                       | `SandboxWebSearchTool`          | `src/tools/web_search.py`                   | [WebSearch-py.json](WebSearch-py.json)                                 |
| `readonly_subagent`                | `ReadonlySubAgentTool`          | `src/tools/readonly_subagent.py`            | [ReadonlySubagent-py.json](ReadonlySubagent-py.json)                   |
| `manage_todo_list`                 | `ManageTodoListTool`            | `src/tools/orchestrator_tools.py`           | [OrchestratorTools-py.json](OrchestratorTools-py.json)                 |
| `list_video_templates`             | `ListVideoTemplatesTool`        | 同上                                        | 同上                                                                   |
| `read_video_template`              | `ReadVideoTemplateTool`         | 同上                                        | 同上                                                                   |
| `find_images`                      | `FindImagesTool`                | `src/tools/image_find.py`                   | [ImageFind-py.json](ImageFind-py.json)                                 |
| `analyze_image`                    | `AnalyzeImageTool`              | `src/tools/vision_tools.py`                 | [VisionTools-py.json](VisionTools-py.json)                             |
| `screenshot_and_review_html`       | `ScreenshotReviewHtmlTool`      | 同上                                        | 同上                                                                   |
| `html_worker_subagent`             | `HtmlWorkerSubAgentTool`        | `src/tools/html_worker_subagent.py`         | [HtmlWorkerSubagent-py.json](HtmlWorkerSubagent-py.json)               |

`web_search` 僅在 `create_agent_components(..., enable_web_search_tool=True)`（預設）時註冊。

**說明**：`WriteWorkspaceFileTool` / `ReadWorkerScopedFileTool` 類別定義於 `src/tools/worker_files.py`（[WorkerFiles-py.json](WorkerFiles-py.json)），**預設只掛在 `html_worker_subagent` 的子工具表**。若要在 **主** runtime 直接使用，請在 `create_agent_components` 的 `tool_factories` 內另行註冊對應 factory 與名稱。

## 各工具用途摘要

- **`scan_workspace`**：產生專案目錄樹文字，略過 `venv`、`.git`、`chat_history` 等噪音路徑。
- **`lookup_skill`**：依關鍵字模糊比對，從 `SkillRegistry` 取出技能 SOP 全文（技能為說明文件，不可當成另一個可執行工具直接呼叫）。
- **`list_materials` / `read_material` / `summarize_material`**：在 `./materials` 內列出、分段讀取與摘要素材檔（路徑鎖在 materials 根目錄內）。
- **`read_workspace_file` / `summarize_workspace_file`**：在 `workspace_scope` 所限制的子樹內唯讀讀檔與摘要（由 `create_agent_components(..., workspace_scope=...)` 決定根目錄）。
- **`web_topology_spider`**：從種子 URL 探索同網域拓樸，優先 sitemap / robots，必要時 BFS；可透過 SSE 回報進度。
- **`dom_skeleton_xray`**：抓取頁面後輸出結構骨架（保留 id/class/data-\* 等）與 selector 提示，利於設計解析器。
- **`scrape_page_dom`**：抓取完整 HTML（可選動態渲染）；預設僅 HTML，需顯式允許才可接受 JSON 或非 HTML 文字本體。
- **`http_request`**：在 SSRF 防護下送出 GET/POST 等請求，回傳 JSON 字串含 status、content-type、body（非文字本體會標記阻擋）。
- **`summarize_url_with_secondary_llm`**：抓 URL 內容後以「次要 LLM」產出短摘要／關鍵字等；可設定環境變數或走降級邏輯（見該 JSON 的 runtime_notes）。
- **`web_search`**：搜尋＋抓取頁面、去除危險 HTML 後以 Markdown 包在 `<UNTRUSTED_WEB_DATA>` 內；提供者順序可由 `WEB_SEARCH_PROVIDER_ORDER` 調整。
- **`readonly_subagent`**：在單次工具呼叫內啟動子 `AgentRuntime`，工具集為白名單交集；**禁止**遞迴呼叫 `readonly_subagent`。子對話歷史寫在 `chat_history/subagents/`。
- **`manage_todo_list`**：讀寫 `<storage_directory>/todos/<conversation_id>.json`；需由 `AgentRuntime` 注入 `_conversation_id`。變更可透過 SSE `todo_updated` 或 `GET /api/conversations/<id>/todos`（Web UI）同步。
- **`list_video_templates` / `read_video_template`**：僅讀 `templates/<id>/meta.json`（與可選 `system_prompt.md` 摘要），**不**回傳完整 `base.html`。
- **`find_images`**：委派 `ImageBackend`；預設 `HardcodedImageBackend` 回傳《Asset Reference List》風格目錄與 `[IMAGE_RESOURCE]` 範例。環境變數 `IMAGE_STATIC_BASE` 覆寫基底 URL。見 [ImageBackend-py.json](ImageBackend-py.json)。
- **`analyze_image` / `screenshot_and_review_html`**：呼叫 `LMWrapper.analyze_image_bytes`（Gemini `inlineData` 或 OpenAI-compatible vision）。截圖工具依賴 **Playwright**（`pip install` 後執行 `python -m playwright install chromium`）。
- **`html_worker_subagent`**：可寫 `output/`、讀 `templates/`/`output/` 的子 runtime；與 `readonly_subagent` **分流**；禁止遞迴。可帶 `template_id` 以附加 `templates/<id>/system_prompt.md`。
- **`write_workspace_file` / `read_worker_scoped_file`**：路徑受限（寫入僅 `output/`；讀取僅 `templates/` 或 `output/`）。

## Orchestrator 專用行為（摘要）

- 回傳精簡 JSON／短 Markdown；避免將完整 HTML 透過工具結果塞回主對話。
- 目錄級內容（例如 `find_images` 全文）建議 `save_policy=file` 或工具回傳 `history_mode: file`，行為與其他工具一致，見 `AgentRuntime._normalize_tool_result_payload`。

## 共通選用參數（大型輸出）

多數工具支援將結果改為「寫檔、對話只留引用」的模式，避免塞爆上下文：

- `save_policy`: `"inline"`（預設）或 `"file"`
- `output_target`: `"memory"` 或 `"materials"`（`save_policy=file` 時有效）
- `output_path`: 相對於目標資料夾的選填路徑

實際行為由 `AgentRuntime` 與工具回傳的 `history_mode` 等欄位共同決定；細節見各工具的 `tool_contract` 與 `runtime_notes`。

## 非 LLM 工具：網路安全輔助模組

`src/tools/network_safety.py` **不會**註冊成模型可呼叫工具，但為 `http_request`、`scrape_page_dom` 等提供 URL 驗證與標頭清理。說明見 [NetworkSafety-py.json](NetworkSafety-py.json)。

## 組裝入口

工具清單與 `workspace_scope`、`enabled_tools`、`enable_web_search_tool`、`readonly_subagent_config` 的互動，見 [AgentFactory-py.json](AgentFactory-py.json) 與原始碼 `src/agent_factory.py` 內 `create_agent_components`。
