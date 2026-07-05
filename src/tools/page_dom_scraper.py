import json
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.ai_core.tool_executor import BaseTool
from src.tools.network_safety import (
    is_json_content_type,
    validate_outbound_url,
)


class PageDOMScraperTool(BaseTool):
    def __init__(self, timeout: int = 15, max_html_chars: int = 800000):
        self.timeout = timeout
        self.max_html_chars = max_html_chars
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "scrape_page_dom"

    @property
    def description(self) -> str:
        return (
            "Fetch full page HTML DOM from a URL. Use when complete structure is needed for parser design, "
            "debugging dynamic rendering, or detailed selector inspection."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target page URL.",
                },
                "render_dynamic": {
                    "type": "boolean",
                    "description": "Enable headless-browser rendering for JS-loaded content.",
                },
                "dynamic_wait_ms": {
                    "type": "integer",
                    "description": "Wait time for JS-rendered DOM in milliseconds.",
                },
                "allow_non_html": {
                    "type": "boolean",
                    "description": "Allow non-HTML textual response bodies to be returned as body.",
                },
                "accept_json": {
                    "type": "boolean",
                    "description": "When content-type is JSON, return response.text as body instead of rejecting.",
                },
                "save_policy": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "description": "inline: put content in history. file: save content to file and keep history slim.",
                },
                "output_target": {
                    "type": "string",
                    "enum": ["memory", "materials"],
                    "description": "When save_policy=file, target folder to store output.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional relative output file path within target folder.",
                },
            },
            "required": ["url"],
        }

    def execute(
        self,
        url: str,
        render_dynamic: bool = True,
        dynamic_wait_ms: int = 1800,
        allow_non_html: bool = False,
        accept_json: bool = False,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        if not url.strip():
            return "Error: url is required."
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Error: url must be a valid absolute http/https URL."
        safety_error = validate_outbound_url(url.strip())
        if safety_error:
            content = json.dumps(
                {
                    "url": url.strip(),
                    "error": f"Blocked by safety policy: {safety_error}",
                },
                ensure_ascii=False,
                indent=2,
            )
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        body_text, fetch_error, mode, notice, content_type = self._fetch_html(
            url.strip(),
            render_dynamic=render_dynamic,
            dynamic_wait_ms=dynamic_wait_ms,
            allow_non_html=allow_non_html,
            accept_json=accept_json,
        )
        if fetch_error:
            content = json.dumps(
                {
                    "url": url.strip(),
                    "error": fetch_error,
                    "render_mode_used": mode,
                    "render_notice": notice,
                    "content_type": content_type or "unknown",
                },
                ensure_ascii=False,
                indent=2,
            )
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        truncated = False
        if len(body_text) > self.max_html_chars:
            body_text = body_text[: self.max_html_chars]
            truncated = True

        is_html = "html" in str(content_type or "").lower()
        content = json.dumps(
            {
                "url": url.strip(),
                "render_mode_used": mode,
                "render_notice": notice,
                "content_type": content_type or "unknown",
                "is_html": is_html,
                "truncated": truncated,
                "html_length": len(body_text) if is_html else 0,
                "body_length": len(body_text),
                "html": body_text if is_html else "",
                "body": body_text if not is_html else "",
            },
            ensure_ascii=False,
            indent=2,
        )
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )

    def _build_output_payload(
        self,
        *,
        content: str,
        save_policy: str,
        output_target: str,
        output_path: Optional[str],
    ) -> Any:
        if save_policy != "file":
            return content
        return {
            "content": content,
            "history_mode": "file",
            "output_target": output_target if output_target in {"memory", "materials"} else "memory",
            "output_path": output_path,
        }

    def _fetch_html(
        self,
        url: str,
        *,
        render_dynamic: bool,
        dynamic_wait_ms: int,
        allow_non_html: bool,
        accept_json: bool,
    ) -> Tuple[str, Optional[str], str, Optional[str], str]:
        if render_dynamic:
            rendered_html, render_error = self._fetch_dynamic_html(url, dynamic_wait_ms=dynamic_wait_ms)
            if rendered_html:
                return rendered_html, None, "dynamic_browser", None, "text/html; charset=utf-8"
            fallback_notice = f"Dynamic render fallback to static: {render_error}"
        else:
            fallback_notice = None

        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return "", f"Fetch failed: {exc}", "static_http", fallback_notice, "unknown"

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" in content_type or "text/" in content_type:
            return response.text, None, "static_http", fallback_notice, (content_type or "unknown")
        if accept_json and is_json_content_type(content_type):
            return response.text, None, "static_http", fallback_notice, (content_type or "unknown")
        if allow_non_html and ("json" in content_type or "xml" in content_type):
            return response.text, None, "static_http", fallback_notice, (content_type or "unknown")
        return (
            "",
            f"Skipped non-html content type: {content_type or 'unknown'}",
            "static_http",
            fallback_notice,
            (content_type or "unknown"),
        )

    def _fetch_dynamic_html(self, url: str, *, dynamic_wait_ms: int) -> Tuple[str, Optional[str]]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return "", "Playwright is not installed in runtime environment."

        wait_ms = max(0, min(int(dynamic_wait_ms), 20000))
        timeout_ms = max(1000, int(self.timeout * 1000))
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.default_user_agent)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
                page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight, 1200));")
                if wait_ms > 0:
                    page.wait_for_timeout(min(wait_ms, 1200))
                html_text = page.content()
                browser.close()
                return html_text, None
        except Exception as exc:
            return "", f"Dynamic render failed: {exc}"
