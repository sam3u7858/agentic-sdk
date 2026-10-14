import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv

from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper, resolve_default_llm_api_key
from src.ai_core.prompt_manager import PromptManager
from src.ai_core.runtime import AgentRuntime
from src.ai_core.session import ChatSession
from src.ai_core.skill_registry import SkillRegistry
from src.ai_core.tool_executor import ToolExecutor
from src.tools.materials_manager import (
    ListMaterialsTool,
    ReadMaterialTool,
    SummarizeMaterialTool,
)
from src.tools.dom_skeleton_xray import DOMSkeletonXrayTool
from src.tools.html_worker_subagent import HtmlWorkerSubAgentTool
from src.tools.http_request import HttpRequestTool
from src.tools.image_find import FindImagesTool
from src.tools.orchestrator_tools import (
    ListVideoTemplatesTool,
    ManageTodoListTool,
    ReadVideoTemplateTool,
)
from src.tools.page_dom_scraper import PageDOMScraperTool
from src.tools.readonly_subagent import ReadonlySubAgentTool
from src.tools.skill_manager import LookupSkillTool
from src.tools.url_secondary_llm_summarizer import URLSecondaryLLMSummarizerTool
from src.tools.vision_tools import AnalyzeImageTool, ScreenshotReviewHtmlTool
from src.tools.web_topology_spider import WebTopologySpiderTool
from src.tools.web_search import SandboxWebSearchTool
from src.tools.worker_files import ReadWorkerScopedFileTool, WriteWorkspaceFileTool
from src.tools.workspace_reader import ReadWorkspaceFileTool, SummarizeWorkspaceFileTool
from src.tools.workspace_scout import ScanWorkspaceTool


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def create_agent_components(
    conversation_id: str,
    *,
    storage_directory: str = "chat_history",
    event_handler=None,
    provider: str = "gemini",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    lm_api_url: Optional[str] = None,
    request_options: Optional[Dict[str, Any]] = None,
    workspace_scope: Optional[str] = None,
    enabled_tools: Optional[List[str]] = None,
    readonly_subagent_config: Optional[Dict[str, Any]] = None,
    compression_config: Optional[Dict[str, Any]] = None,
    history_memory_config: Optional[Dict[str, Any]] = None,
    enable_web_search_tool: bool = True,
    system_prompt_name: str = "system_core",
    system_prompt_vars: Optional[Dict[str, Any]] = None,
    runtime_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    load_dotenv()

    resolved_provider = provider
    resolved_model = model
    if resolved_model is None:
        if resolved_provider.lower() == "gemini":
            resolved_model = os.getenv(
                "GEMINI_MODEL", "gemini-3-flash-preview")
        else:
            raise ValueError(
                "model is required when provider is not 'gemini'.")

    resolved_api_key = resolve_default_llm_api_key(
        resolved_provider, api_key)

    resolved_lm_api_url = _strip_or_none(lm_api_url)
    if resolved_lm_api_url is None:
        resolved_lm_api_url = _strip_or_none(os.getenv("LM_API_URL"))

    prompt_manager = PromptManager(str(PROJECT_ROOT / "prompts"))
    skill_registry = SkillRegistry(
        skill_directory=str(PROJECT_ROOT / "skills"))

    scope_path = workspace_scope.strip() if workspace_scope else ""
    scan_root = (PROJECT_ROOT /
                 scope_path).resolve() if scope_path else PROJECT_ROOT

    tool_factories: Dict[str, Callable[[], Any]] = {
        "scan_workspace": lambda: ScanWorkspaceTool(root_dir=str(scan_root)),
        "lookup_skill": lambda: LookupSkillTool(skill_registry=skill_registry),
        "list_materials": lambda: ListMaterialsTool(project_root=str(PROJECT_ROOT)),
        "read_material": lambda: ReadMaterialTool(project_root=str(PROJECT_ROOT)),
        "summarize_material": lambda: SummarizeMaterialTool(project_root=str(PROJECT_ROOT)),
        "read_workspace_file": lambda: ReadWorkspaceFileTool(
            root_dir=str(PROJECT_ROOT), allowed_scope=scope_path or None
        ),
        "summarize_workspace_file": lambda: SummarizeWorkspaceFileTool(
            root_dir=str(PROJECT_ROOT), allowed_scope=scope_path or None
        ),
        "web_topology_spider": lambda: WebTopologySpiderTool(),
        "dom_skeleton_xray": lambda: DOMSkeletonXrayTool(),
        "scrape_page_dom": lambda: PageDOMScraperTool(),
        "http_request": lambda: HttpRequestTool(),
        "summarize_url_with_secondary_llm": lambda: URLSecondaryLLMSummarizerTool(),
    }
    if enable_web_search_tool:
        tool_factories["web_search"] = lambda: SandboxWebSearchTool()

    tool_factories["manage_todo_list"] = lambda: ManageTodoListTool(
        storage_directory=storage_directory,
    )
    tool_factories["list_video_templates"] = lambda: ListVideoTemplatesTool(
        str(PROJECT_ROOT),
    )
    tool_factories["read_video_template"] = lambda: ReadVideoTemplateTool(
        str(PROJECT_ROOT),
    )
    tool_factories["find_images"] = lambda: FindImagesTool()
    tool_factories["analyze_image"] = lambda: AnalyzeImageTool(
        project_root=str(PROJECT_ROOT),
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        lm_api_url=resolved_lm_api_url,
        request_options=request_options,
    )
    tool_factories["screenshot_and_review_html"] = lambda: ScreenshotReviewHtmlTool(
        project_root=str(PROJECT_ROOT),
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        lm_api_url=resolved_lm_api_url,
        request_options=request_options,
    )

    sub_cfg = readonly_subagent_config or {}
    sub_allowed = sub_cfg.get(
        "default_allowed_tools",
        [
            "web_search",
            "scan_workspace",
            "read_workspace_file",
            "summarize_workspace_file",
            "web_topology_spider",
            "dom_skeleton_xray",
            "scrape_page_dom",
            "http_request",
            "summarize_url_with_secondary_llm",
        ],
    )
    sub_tool_factories = {
        name: tool_factories[name]
        for name in sub_allowed
        if isinstance(name, str) and name in tool_factories
    }
    tool_factories["readonly_subagent"] = lambda: ReadonlySubAgentTool(
        project_root=str(PROJECT_ROOT),
        storage_directory=storage_directory,
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        lm_api_url=resolved_lm_api_url,
        request_options=request_options,
        default_allowed_tools=list(sub_allowed),
        tool_factories=sub_tool_factories,
    )

    worker_tool_factories: Dict[str, Callable[[], Any]] = {
        "write_workspace_file": lambda: WriteWorkspaceFileTool(str(PROJECT_ROOT)),
        "read_worker_scoped_file": lambda: ReadWorkerScopedFileTool(str(PROJECT_ROOT)),
        "list_video_templates": lambda: ListVideoTemplatesTool(str(PROJECT_ROOT)),
        "read_video_template": lambda: ReadVideoTemplateTool(str(PROJECT_ROOT)),
    }
    tool_factories["html_worker_subagent"] = lambda: HtmlWorkerSubAgentTool(
        project_root=str(PROJECT_ROOT),
        storage_directory=storage_directory,
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        lm_api_url=resolved_lm_api_url,
        request_options=request_options,
        default_allowed_tools=[
            "write_workspace_file",
            "read_worker_scoped_file",
            "list_video_templates",
            "read_video_template",
        ],
        tool_factories=worker_tool_factories,
    )

    selected_tool_names = enabled_tools if enabled_tools is not None else list(tool_factories.keys())
    tool_executor = ToolExecutor()
    for tool_name in selected_tool_names:
        factory = tool_factories.get(tool_name)
        if factory is None:
            continue
        tool_executor.register_tool(factory())

    llm = LMWrapper(
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        lm_api_url=resolved_lm_api_url,
        request_options=request_options,
    )
    prompt_vars: Dict[str, Any] = {
        "agent_name": "SkillAware-Agent",
        "available_skills": skill_registry.get_skill_summaries(),
    }
    prompt_vars.update(system_prompt_vars or {})
    system_prompt = prompt_manager.load_prompt(system_prompt_name, **prompt_vars)
    llm.set_system_prompt(system_prompt)

    history = LocalChatHistory(
        storage_directory=storage_directory,
        memory_config=history_memory_config,
    )
    history.create_conversation(conversation_id)
    session = ChatSession(
        llm=llm,
        history_backend=history,
        conversation_id=conversation_id,
    )
    runtime = AgentRuntime(
        session,
        tool_executor,
        event_handler=event_handler,
        compression_config=compression_config,
        runtime_options=runtime_options,
    )

    return {
        "project_root": PROJECT_ROOT,
        "prompt_manager": prompt_manager,
        "skill_registry": skill_registry,
        "tool_executor": tool_executor,
        "llm": llm,
        "history": history,
        "session": session,
        "runtime": runtime,
        "system_prompt": system_prompt,
        "tool_factories": tool_factories,
    }


def build_agent_runtime(
    conversation_id: str,
    *,
    storage_directory: str = "chat_history",
    event_handler=None,
    provider: str = "gemini",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    lm_api_url: Optional[str] = None,
    request_options: Optional[Dict[str, Any]] = None,
    workspace_scope: Optional[str] = None,
    enabled_tools: Optional[List[str]] = None,
    readonly_subagent_config: Optional[Dict[str, Any]] = None,
    compression_config: Optional[Dict[str, Any]] = None,
    history_memory_config: Optional[Dict[str, Any]] = None,
    enable_web_search_tool: bool = True,
) -> AgentRuntime:
    components = create_agent_components(
        conversation_id,
        storage_directory=storage_directory,
        event_handler=event_handler,
        provider=provider,
        model=model,
        api_key=api_key,
        lm_api_url=lm_api_url,
        request_options=request_options,
        workspace_scope=workspace_scope,
        enabled_tools=enabled_tools,
        readonly_subagent_config=readonly_subagent_config,
        compression_config=compression_config,
        history_memory_config=history_memory_config,
        enable_web_search_tool=enable_web_search_tool,
    )
    return components["runtime"]  # type: ignore[return-value]


def build_demo_prompt() -> str:
    return (
        "請先用 scan_workspace 掃描 skills 目錄，列出可用技能，"
        "然後用 lookup_skill 載入其中一個技能並說明它的用途。"
    )
