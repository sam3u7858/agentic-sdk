# src/tools/html_worker_subagent.py
"""HTML worker sub-agent: may write output/ and read templates/ via scoped tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper, resolve_default_llm_api_key
from src.ai_core.prompt_manager import PromptManager
from src.ai_core.runtime import AgentRuntime
from src.ai_core.session import ChatSession
from src.ai_core.tool_executor import BaseTool, ToolExecutor


class HtmlWorkerSubAgentTool(BaseTool):
    def __init__(
        self,
        *,
        project_root: str,
        storage_directory: str = "chat_history",
        provider: str = "gemini",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        lm_api_url: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
        default_allowed_tools: Optional[List[str]] = None,
        tool_factories: Optional[Dict[str, Callable[[], BaseTool]]] = None,
        prompt_name: str = "system_core",
    ):
        self.project_root = Path(project_root).resolve()
        self.storage_directory = storage_directory
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.lm_api_url = lm_api_url
        self.request_options = request_options
        self.default_allowed_tools = default_allowed_tools or []
        self.tool_factories = tool_factories or {}
        self.prompt_name = prompt_name

    @property
    def name(self) -> str:
        return "html_worker_subagent"

    @property
    def description(self) -> str:
        return (
            "Spawn an HTML worker sub-agent that may write files under output/ and read "
            "templates/ + output/. Cannot call html_worker_subagent or readonly_subagent."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Work order for the HTML worker."},
                "max_steps": {"type": "integer", "description": "Max worker steps (clamped)."},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tool whitelist; worker tools only.",
                },
                "template_id": {
                    "type": "string",
                    "description": "Optional templates/<id>/ to load system_prompt.md into worker context.",
                },
            },
            "required": ["task"],
        }

    def execute(
        self,
        task: str,
        max_steps: int = 12,
        allowed_tools: Optional[List[str]] = None,
        template_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        if not str(task).strip():
            return "Error: task is required."

        selected = self._resolve_allowed_tools(allowed_tools)
        if not selected:
            return "Error: no allowed tools available for html worker."

        sub_exec = ToolExecutor()
        for tool_name in selected:
            factory = self.tool_factories.get(tool_name)
            if factory is None:
                continue
            sub_exec.register_tool(factory())

        if not sub_exec.schemas:
            return "Error: html worker has no tools after whitelist."

        resolved_provider = self.provider
        resolved_model = self.model
        if resolved_model is None:
            if resolved_provider.lower() == "gemini":
                resolved_model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
            else:
                return "Error: model is required when provider is not 'gemini'."

        resolved_api_key = resolve_default_llm_api_key(resolved_provider, self.api_key)

        prompt_manager = PromptManager(str(self.project_root / "prompts"))
        system_prompt = prompt_manager.load_prompt(
            self.prompt_name,
            agent_name="HTML-Worker",
            available_skills="Worker mode: may write output/ and read templates/ via tools.",
        )
        system_prompt += (
            "\n\n[HTML Worker Hard Constraints]\n"
            "1) Use write_workspace_file only under output/.\n"
            "2) Read HTML via read_worker_scoped_file under templates/ or output/.\n"
            "3) Do not call html_worker_subagent or readonly_subagent.\n"
            "4) Return concise status and paths; do not paste huge HTML in final summaries.\n"
        )

        tid = str(template_id or "").strip()
        if tid:
            sp_path = self.project_root / "templates" / tid / "system_prompt.md"
            if sp_path.is_file():
                system_prompt += (
                    "\n\n[TEMPLATE system_prompt.md]\n" + sp_path.read_text(encoding="utf-8")
                )
            else:
                system_prompt += f"\n\n[Note] template_id={tid} has no system_prompt.md\n"

        llm = LMWrapper(
            provider=resolved_provider,
            model=str(resolved_model),
            api_key=resolved_api_key,
            lm_api_url=self.lm_api_url,
            request_options=self.request_options,
        )
        llm.set_system_prompt(system_prompt)

        conversation_id = f"hw_{uuid4().hex[:12]}"
        sub_history_dir = str((Path(self.storage_directory) / "subagents").resolve())
        history = LocalChatHistory(storage_directory=sub_history_dir)
        history.create_conversation(conversation_id)
        session = ChatSession(llm=llm, history_backend=history, conversation_id=conversation_id)
        runtime = AgentRuntime(session, sub_exec)

        result = runtime.run(task, max_steps=max(1, min(max_steps, 24)))
        payload = {
            "worker_conversation_id": conversation_id,
            "allowed_tools": selected,
            "template_id": tid or None,
            "result": result,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _resolve_allowed_tools(self, allowed_tools: Optional[List[str]]) -> List[str]:
        if allowed_tools is None:
            candidate = list(self.default_allowed_tools)
        else:
            candidate = [name for name in allowed_tools if isinstance(name, str)]

        blocked = {"readonly_subagent", "html_worker_subagent"}
        resolved = [
            name for name in candidate
            if name not in blocked and name in self.tool_factories
        ]

        seen = set()
        unique: List[str] = []
        for name in resolved:
            if name in seen:
                continue
            seen.add(name)
            unique.append(name)
        return unique
