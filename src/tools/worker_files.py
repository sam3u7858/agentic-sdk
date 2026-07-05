# src/tools/worker_files.py
"""Restricted read/write for HTML worker sub-agent."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.ai_core.tool_executor import BaseTool

_WORKER_READ_PREFIXES = ("templates/", "output/")


def _resolve_under_root(project_root: Path, relative: str) -> Tuple[Optional[Path], Optional[str]]:
    rel = str(relative or "").strip().replace("\\", "/").lstrip("/")
    if not rel or ".." in Path(rel).parts:
        return None, "Invalid relative path."
    candidate = (project_root / rel).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return None, "Path escapes project root."
    if not any(rel.startswith(p) for p in _WORKER_READ_PREFIXES):
        return None, "Read only allowed under templates/ or output/."
    return candidate, None


class ReadWorkerScopedFileTool(BaseTool):
    """Read-only access to templates/* and output/* under the project root."""

    def __init__(self, project_root: str):
        self._root = Path(project_root).resolve()

    @property
    def name(self) -> str:
        return "read_worker_scoped_file"

    @property
    def description(self) -> str:
        return (
            "Read a text file under templates/ or output/ (relative to project root). "
            "Use for base.html, system_prompt.md, or generated assets."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "e.g. templates/t01_demo_video/base.html",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Optional read cap (default 200000).",
                },
            },
            "required": ["relative_path"],
        }

    def execute(
        self,
        relative_path: str,
        max_chars: int = 200000,
        **kwargs: Any,
    ) -> str:
        path, err = _resolve_under_root(self._root, relative_path)
        if err:
            return err
        assert path is not None
        if not path.is_file():
            return f"File not found: {relative_path}"
        cap = max(1000, min(int(max_chars or 200000), 500000))
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        truncated = False
        if len(text) > cap:
            text = text[:cap]
            truncated = True
        return (
            f"File: {relative_path}\n"
            f"truncated={truncated}\n\n"
            f"{text}"
        )


class WriteWorkspaceFileTool(BaseTool):
    """Write text only under output/ relative to project root."""

    def __init__(self, project_root: str):
        self._root = Path(project_root).resolve()

    @property
    def name(self) -> str:
        return "write_workspace_file"

    @property
    def description(self) -> str:
        return (
            "Create or overwrite a UTF-8 text file under output/ only. "
            "relative_path must start with output/."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Must be like output/run1/index.html",
                },
                "content": {"type": "string", "description": "Full file text."},
            },
            "required": ["relative_path", "content"],
        }

    def execute(self, relative_path: str, content: str, **kwargs: Any) -> str:
        rel = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
        if not rel.startswith("output/"):
            return "Error: write_workspace_file only allows paths under output/."
        if ".." in rel.split("/"):
            return "Error: path must not contain '..'."
        path = (self._root / rel).resolve()
        try:
            path.relative_to(self._root)
            path.relative_to(self._root / "output")
        except ValueError:
            return "Error: path must stay inside project output/."

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")
        return f"OK: wrote {len(content.encode('utf-8'))} bytes to {rel}"
