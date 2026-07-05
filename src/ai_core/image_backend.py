# src/ai_core/image_backend.py
"""ImageBackend protocol and default hardcoded catalog backend (no CLIP / vectors)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol


DEFAULT_IMAGE_STATIC_BASE = "http://192.168.0.162:50005"


def resolve_image_static_base() -> str:
    raw = (os.getenv("IMAGE_STATIC_BASE") or "").strip()
    return raw or DEFAULT_IMAGE_STATIC_BASE


class ImageBackend(Protocol):
    """Pluggable image candidate source (Hardcoded today; CLIP/FAISS later)."""

    def find_candidates(self, query_text: str, top_k: int = 8) -> str:
        ...


@dataclass
class HardcodedImageBackend:
    """Returns the canonical asset reference list; ignores embedding similarity."""

    catalog_path: Optional[Path] = None

    def _load_catalog_text(self) -> str:
        base = resolve_image_static_base()
        path = self.catalog_path or (
            Path(__file__).resolve().parent / "image_catalog" / "hardcoded_asset_reference.md"
        )
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = (
                "# Asset Reference List\n\nStatic root: {{IMAGE_STATIC_BASE}}/static/\n"
                "[IMAGE_RESOURCE]\npath: /static/mh-items/demo.png\ndescription: fallback\n"
            )
        return raw.replace("{{IMAGE_STATIC_BASE}}", base.rstrip("/"))

    def find_candidates(self, query_text: str, top_k: int = 8) -> str:
        _ = (query_text or "").strip()
        k = max(1, min(int(top_k or 8), 32))
        body = self._load_catalog_text()
        head = (
            f"[find_images] query={query_text!r} top_k={k}\n"
            f"IMAGE_STATIC_BASE={resolve_image_static_base()}\n\n"
        )
        return head + body
