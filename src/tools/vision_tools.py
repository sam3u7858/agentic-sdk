# src/tools/vision_tools.py
"""analyze_image (vision LLM) and screenshot + visual QA for HTML."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.ai_core.llm import LMWrapper, LMBackendError, resolve_default_llm_api_key
from src.ai_core.tool_executor import BaseTool
from src.tools.network_safety import validate_outbound_url


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


class AnalyzeImageTool(BaseTool):
    """Download or read an image, then run a single multimodal LLM pass."""

    def __init__(
        self,
        *,
        project_root: str,
        provider: str = "gemini",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        lm_api_url: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
    ):
        self._root = Path(project_root).resolve()
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._lm_api_url = lm_api_url
        self._request_options = request_options or {}

    def _make_llm(self) -> LMWrapper:
        return LMWrapper(
            provider=self._provider,
            model=str(self._model or ""),
            api_key=self._api_key,
            lm_api_url=self._lm_api_url,
            request_options=self._request_options,
        )

    @property
    def name(self) -> str:
        return "analyze_image"

    @property
    def description(self) -> str:
        return (
            "Analyze an image using the vision-capable model. "
            "Provide either image_url (http/https) or relative image_path under "
            "templates/, output/, or materials/."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What to extract or check."},
                "image_url": {"type": "string", "description": "Public or internal http(s) URL."},
                "image_path": {
                    "type": "string",
                    "description": "Project-relative path, e.g. output/preview.png",
                },
            },
            "required": ["question"],
        }

    def _load_bytes(self, image_url: Optional[str], image_path: Optional[str]) -> Tuple[bytes, str, Optional[str]]:
        if image_path and str(image_path).strip():
            rel = str(image_path).strip().replace("\\", "/").lstrip("/")
            allowed = ("templates/", "output/", "materials/")
            if not any(rel.startswith(p) for p in allowed):
                raise ValueError("image_path must be under templates/, output/, or materials/.")
            path = (self._root / rel).resolve()
            try:
                path.relative_to(self._root)
            except ValueError as exc:
                raise ValueError("image_path escapes project root.") from exc
            if not path.is_file():
                raise ValueError(f"image file not found: {rel}")
            mime = _guess_mime(path.name)
            return path.read_bytes(), mime, None

        if image_url and str(image_url).strip():
            url = str(image_url).strip()
            err = validate_outbound_url(url)
            if err:
                raise ValueError(err)
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            mime = resp.headers.get("Content-Type", "").split(";")[0].strip() or _guess_mime(
                urlparse(url).path
            )
            return resp.content, mime, None

        raise ValueError("Provide image_url or image_path.")

    def execute(
        self,
        question: str,
        image_url: Optional[str] = None,
        image_path: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        if not (question or "").strip():
            return "Error: question is required."
        try:
            data, mime, _ = self._load_bytes(image_url, image_path)
        except ValueError as exc:
            return f"Error: {exc}"
        except requests.RequestException as exc:
            return f"Error: failed to fetch image: {exc}"

        if not mime.startswith("image/"):
            return f"Error: unsupported content type {mime!r} (expected image/*)."

        key = resolve_default_llm_api_key(self._provider, self._api_key)
        llm = self._make_llm()
        if not key and self._provider.lower() == "gemini":
            return "Error: missing GEMINI_KEY for analyze_image."
        llm.set_system_prompt(
            "You are a careful vision assistant. Answer the user question about the image. "
            "If text is illegible, say so. Reply concisely."
        )
        try:
            out = llm.analyze_image_bytes(
                prompt=str(question),
                image_bytes=data,
                mime_type=mime,
                system_prompt=None,
            )
            return out or "(empty model response)"
        except LMBackendError as exc:
            return f"Error: vision model failed: {exc}"


class ScreenshotReviewHtmlTool(BaseTool):
    """Headless screenshot of a local HTML file or URL, then short visual QA via vision LLM."""

    def __init__(
        self,
        *,
        project_root: str,
        provider: str = "gemini",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        lm_api_url: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
    ):
        self._root = Path(project_root).resolve()
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._lm_api_url = lm_api_url
        self._request_options = request_options or {}

    def _make_llm(self) -> LMWrapper:
        return LMWrapper(
            provider=self._provider,
            model=str(self._model or ""),
            api_key=self._api_key,
            lm_api_url=self._lm_api_url,
            request_options=self._request_options,
        )

    @property
    def name(self) -> str:
        return "screenshot_and_review_html"

    @property
    def description(self) -> str:
        return (
            "Open local HTML (file under output/ or templates/) or http(s) page in a headless browser, "
            "capture screenshot, and return a brief visual QA report via the vision model. "
            "Requires optional dependency playwright (`pip install playwright` + browser install)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "relative_html_path": {
                    "type": "string",
                    "description": "Project-relative path to HTML under output/ or templates/.",
                },
                "page_url": {
                    "type": "string",
                    "description": "Instead of local file, load this http(s) URL (SSRF rules apply).",
                },
                "viewport_width": {"type": "integer"},
                "viewport_height": {"type": "integer"},
            },
            "required": [],
        }

    def _resolve_local_html(self, relative_html_path: str) -> str:
        rel = str(relative_html_path or "").strip().replace("\\", "/").lstrip("/")
        if not rel.startswith(("output/", "templates/")):
            raise ValueError("relative_html_path must be under output/ or templates/.")
        path = (self._root / rel).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("path escapes project root.") from exc
        if not path.is_file():
            raise ValueError(f"HTML not found: {rel}")
        return path.as_uri()

    def execute(
        self,
        relative_html_path: Optional[str] = None,
        page_url: Optional[str] = None,
        viewport_width: int = 1280,
        viewport_height: int = 720,
        **kwargs: Any,
    ) -> Any:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return (
                "Error: playwright is not installed. Run: pip install playwright && "
                "python -m playwright install chromium"
            )

        target: Optional[str] = None
        if relative_html_path and str(relative_html_path).strip():
            try:
                target = self._resolve_local_html(str(relative_html_path))
            except ValueError as exc:
                return f"Error: {exc}"
        elif page_url and str(page_url).strip():
            url = str(page_url).strip()
            err = validate_outbound_url(url)
            if err:
                return f"Error: {err}"
            target = url
        else:
            return "Error: provide relative_html_path or page_url."

        w = max(320, min(int(viewport_width or 1280), 1920))
        h = max(240, min(int(viewport_height or 720), 1080))

        png_bytes: bytes
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(target, wait_until="networkidle", timeout=60000)
                png_bytes = page.screenshot(type="png", full_page=True)
                browser.close()
        except Exception as exc:
            return f"Error: screenshot failed: {exc}"

        key = resolve_default_llm_api_key(self._provider, self._api_key)
        llm = self._make_llm()
        if not key and self._provider.lower() == "gemini":
            return "Error: missing GEMINI_KEY for screenshot QA."

        llm.set_system_prompt(
            "You review a screenshot of a web page. List layout/visual issues, unreadable text, "
            "broken chrome, obvious alignment problems. Be concise; use bullet points."
        )
        prompt = (
            f"Target: {target}\nViewport: {w}x{h}\n"
            "Produce a short QA checklist for this render (max 8 bullets)."
        )
        try:
            report = llm.analyze_image_bytes(
                prompt=prompt,
                image_bytes=png_bytes,
                mime_type="image/png",
                system_prompt=None,
            )
        except LMBackendError as exc:
            return f"Error: vision QA failed: {exc}"

        summary = f"[screenshot target]\n{target}\n[bytes]{len(png_bytes)}\n\n{report}"
        return {
            "content": summary,
            "history_mode": "inline",
        }
