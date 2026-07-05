# src/tools/orchestrator_tools.py
"""Orchestrator tools: TODO state and video template metadata (no full HTML)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.ai_core.tool_executor import BaseTool

_TEMPLATE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def _emit_todo_progress(kwargs: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    handler = kwargs.get("_runtime_event_handler")
    if callable(handler):
        handler({"phase": "todo_updated", "todo_snapshot": snapshot})


class ManageTodoListTool(BaseTool):
    """Persist orchestration TODO items under chat_history/todos/<conversation_id>.json."""

    def __init__(self, storage_directory: str = "chat_history"):
        self._storage = Path(storage_directory)

    @property
    def name(self) -> str:
        return "manage_todo_list"

    @property
    def description(self) -> str:
        return (
            "Load or update the orchestration TODO list for the current conversation. "
            "State file: <storage>/todos/<conversation_id>.json. "
            "Use action=get to read; add/update/complete/remove/clear to mutate."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "add", "update", "complete", "remove", "clear", "set"],
                    "description": "get: return items; add: new item; update: patch fields; "
                    "complete: shorthand for done=true; remove: delete id; clear: empty; "
                    "set: replace entire items list.",
                },
                "items": {
                    "type": "array",
                    "description": "For action=set: full list of {id?, text, done}.",
                    "items": {"type": "object"},
                },
                "item_id": {"type": "string", "description": "Target id for update/remove/complete."},
                "text": {"type": "string", "description": "Text for add or update."},
                "done": {"type": "boolean", "description": "Done flag for update/complete."},
            },
            "required": ["action"],
        }

    def _todo_path(self, conversation_id: str) -> Path:
        return (self._storage / "todos" / f"{conversation_id}.json").resolve()

    def _load(self, path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {"items": [], "updated_at": None}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"items": [], "updated_at": None}
        if not isinstance(data, dict):
            return {"items": [], "updated_at": None}
        items = data.get("items")
        if not isinstance(items, list):
            items = []
        clean: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id") or "").strip() or uuid4().hex[:12]
            clean.append(
                {
                    "id": iid,
                    "text": str(it.get("text", "")).strip(),
                    "done": bool(it.get("done", False)),
                }
            )
        return {"items": clean, "updated_at": data.get("updated_at")}

    def _save(self, path: Path, state: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        state = dict(state)
        state["updated_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def execute(
        self,
        action: str,
        items: Optional[List[Any]] = None,
        item_id: Optional[str] = None,
        text: Optional[str] = None,
        done: Optional[bool] = None,
        **kwargs: Any,
    ) -> str:
        conv = str(kwargs.get("_conversation_id") or "").strip()
        if not conv:
            return json.dumps({"error": "missing _conversation_id (internal)"}, ensure_ascii=False)
        if "/" in conv or "\\" in conv or ".." in conv:
            return json.dumps({"error": "invalid conversation_id"}, ensure_ascii=False)

        path = self._todo_path(conv)
        try:
            path.relative_to(self._storage.resolve())
        except ValueError:
            return json.dumps({"error": "invalid todo path"}, ensure_ascii=False)

        state = self._load(path)
        act = (action or "get").lower().strip()
        mutated = False

        if act == "get":
            out = dict(state)
            _emit_todo_progress(kwargs, out)
            return json.dumps(out, ensure_ascii=False, indent=2)

        if act == "clear":
            state = {"items": [], "updated_at": state.get("updated_at")}
            mutated = True
        elif act == "set":
            if items is None:
                return json.dumps({"error": "action=set requires items[]"}, ensure_ascii=False)
            clean_set: List[Dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                iid = str(it.get("id") or "").strip() or uuid4().hex[:12]
                clean_set.append(
                    {
                        "id": iid,
                        "text": str(it.get("text", "")).strip(),
                        "done": bool(it.get("done", False)),
                    }
                )
            state["items"] = clean_set
            mutated = True
        elif act == "add":
            t = (text or "").strip()
            if not t:
                return json.dumps({"error": "add requires non-empty text"}, ensure_ascii=False)
            state["items"].append({"id": uuid4().hex[:12], "text": t, "done": False})
            mutated = True
        elif act in {"update", "complete", "remove"}:
            tid = (item_id or "").strip()
            if not tid:
                return json.dumps({"error": f"{act} requires item_id"}, ensure_ascii=False)
            idx = next((i for i, x in enumerate(state["items"]) if x.get("id") == tid), -1)
            if idx < 0:
                return json.dumps({"error": f"unknown item_id {tid}"}, ensure_ascii=False)
            if act == "remove":
                del state["items"][idx]
                mutated = True
            elif act == "complete":
                state["items"][idx]["done"] = True
                mutated = True
            else:
                if text is not None:
                    state["items"][idx]["text"] = str(text).strip()
                if done is not None:
                    state["items"][idx]["done"] = bool(done)
                mutated = True
        else:
            return json.dumps({"error": f"unknown action {action}"}, ensure_ascii=False)

        if mutated:
            self._save(path, state)
        _emit_todo_progress(kwargs, dict(state))
        return json.dumps(state, ensure_ascii=False, indent=2)


class ListVideoTemplatesTool(BaseTool):
    """List template folders under project templates/ with meta.json summaries."""

    def __init__(self, project_root: str):
        self._root = Path(project_root).resolve()

    @property
    def name(self) -> str:
        return "list_video_templates"

    @property
    def description(self) -> str:
        return (
            "List video HTML templates under templates/<id>/ that contain meta.json. "
            "Returns ids and short metadata only (not base.html)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **kwargs: Any) -> str:
        templates_dir = (self._root / "templates").resolve()
        if not templates_dir.is_dir():
            return json.dumps({"templates": [], "note": "templates/ missing"}, ensure_ascii=False)

        rows: List[Dict[str, Any]] = []
        for child in sorted(templates_dir.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            meta_path = child / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {"error": "invalid meta.json"}
            rows.append(
                {
                    "id": child.name,
                    "meta": meta if isinstance(meta, dict) else {"raw": meta},
                }
            )
        return json.dumps({"templates": rows}, ensure_ascii=False, indent=2)


class ReadVideoTemplateTool(BaseTool):
    """Read templates/<id>/meta.json and optional system_prompt.md (bounded size; not base.html)."""

    def __init__(self, project_root: str, max_system_prompt_chars: int = 12000):
        self._root = Path(project_root).resolve()
        self._max_sys = max_system_prompt_chars

    @property
    def name(self) -> str:
        return "read_video_template"

    @property
    def description(self) -> str:
        return (
            "Read video template meta.json and optional system_prompt.md for template id. "
            "Does not return base.html body; use html_worker sub-agent for HTML."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "description": "Folder name under templates/."},
                "include_system_prompt": {
                    "type": "boolean",
                    "description": "If true, include truncated system_prompt.md text.",
                },
            },
            "required": ["template_id"],
        }

    def execute(
        self,
        template_id: str,
        include_system_prompt: bool = False,
        **kwargs: Any,
    ) -> str:
        tid = str(template_id or "").strip()
        if not _TEMPLATE_ID_RE.fullmatch(tid):
            return json.dumps({"error": "invalid template_id"}, ensure_ascii=False)

        base = (self._root / "templates" / tid).resolve()
        try:
            base.relative_to(self._root / "templates")
        except ValueError:
            return json.dumps({"error": "path outside templates"}, ensure_ascii=False)

        meta_path = base / "meta.json"
        if not meta_path.is_file():
            return json.dumps({"error": f"meta.json not found for {tid}"}, ensure_ascii=False)

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"invalid meta.json: {exc}"}, ensure_ascii=False)

        payload: Dict[str, Any] = {
            "template_id": tid,
            "meta": meta,
            "system_prompt_path": str(base / "system_prompt.md"),
            "base_html_path": str(base / "base.html"),
        }
        if include_system_prompt:
            sp = base / "system_prompt.md"
            if sp.is_file():
                text = sp.read_text(encoding="utf-8")
                trunc = False
                if len(text) > self._max_sys:
                    text = text[: self._max_sys]
                    trunc = True
                payload["system_prompt_excerpt"] = text
                payload["system_prompt_truncated"] = trunc
            else:
                payload["system_prompt_excerpt"] = ""
        return json.dumps(payload, ensure_ascii=False, indent=2)
