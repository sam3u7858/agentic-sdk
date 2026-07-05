# src/tools/image_find.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from src.ai_core.image_backend import HardcodedImageBackend, ImageBackend
from src.ai_core.tool_executor import BaseTool


class FindImagesTool(BaseTool):
    """Resolve image URL candidates via ImageBackend (default: hardcoded catalog)."""

    def __init__(self, backend: Optional[ImageBackend] = None):
        self._backend = backend or HardcodedImageBackend()

    @property
    def name(self) -> str:
        return "find_images"

    @property
    def description(self) -> str:
        return (
            "Find image asset URLs and reference text for video/HTML work. "
            "Uses a catalog backend (hardcoded mock URLs; CLIP/vectors are future)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query_text": {"type": "string", "description": "What kinds of images you need."},
                "top_k": {"type": "integer", "description": "Hint for backend (default 8)."},
                "save_policy": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "description": "file recommended for full catalog.",
                },
                "history_mode": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "description": "Alias of save_policy for orchestrator tools.",
                },
            },
            "required": ["query_text"],
        }

    def execute(
        self,
        query_text: str,
        top_k: int = 8,
        save_policy: str = "inline",
        history_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        text = self._backend.find_candidates(str(query_text or ""), top_k=int(top_k or 8))
        mode = history_mode or save_policy or "inline"
        if mode == "file":
            return {
                "content": text,
                "history_mode": "file",
                "output_target": "memory",
            }
        return text
