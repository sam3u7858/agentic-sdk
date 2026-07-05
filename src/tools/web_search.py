import html
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

from src.ai_core.tool_executor import BaseTool


class SandboxWebSearchTool(BaseTool):
    def __init__(self, timeout: int = 12, max_content_chars: int = 4000):
        self.timeout = timeout
        self.max_content_chars = max_content_chars
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web in a sandbox-like readonly mode, sanitize fetched pages, and return "
            "plain Markdown text wrapped with <UNTRUSTED_WEB_DATA> tags."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query keywords.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of search results to fetch page contents for (1-5).",
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
            "required": ["query"],
        }

    def execute(
        self,
        query: str,
        max_results: int = 3,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        def as_output(content: str) -> Any:
            if save_policy != "file":
                return content
            return {
                "content": content,
                "history_mode": "file",
                "output_target": output_target if output_target in {"memory", "materials"} else "memory",
                "output_path": output_path,
            }

        if not query.strip():
            return as_output("Error: query is required.")

        capped_results = max(1, min(max_results, 5))
        provider_funcs = {
            "serper": (self._search_serper, "Serper Google Search API + sanitized page fetch"),
            "google_cse": (
                self._search_google_custom_search,
                "Google Custom Search JSON API + sanitized page fetch",
            ),
            "duckduckgo": (
                self._search_duckduckgo,
                "DuckDuckGo HTML fallback + sanitized page fetch",
            ),
        }
        provider_order = self._resolve_provider_order(list(provider_funcs.keys()))
        links: List[Tuple[str, str]] = []
        search_error: Optional[str] = None
        source_label = "unknown"
        provider_errors: List[str] = []

        for provider_name in provider_order:
            func, label = provider_funcs[provider_name]
            links, search_error = func(query, capped_results)
            source_label = label
            if links:
                break
            if search_error:
                provider_errors.append(f"{provider_name}: {search_error}")

        if search_error and not links:
            detail = "\n".join(provider_errors[-3:]) if provider_errors else search_error
            return as_output(f"Error: all web search providers failed.\n{detail}")
        if not links:
            return as_output(self._wrap_untrusted(
                f"# Web Search\n\nQuery: {query}\n\nNo search result found."
            ))

        result_blocks: List[str] = []
        for index, (title, url) in enumerate(links, start=1):
            page_text, fetch_error = self._fetch_page_text(url)
            if fetch_error:
                result_blocks.append(
                    f"## Result {index}\n- Title: {title}\n- URL: {url}\n- Error: {fetch_error}"
                )
                continue
            clipped_text = page_text[: self.max_content_chars]
            result_blocks.append(
                f"## Result {index}\n- Title: {title}\n- URL: {url}\n\n{clipped_text}"
            )

        markdown = (
            "# Web Search\n\n"
            f"Query: {query}\n"
            f"Source: {source_label}\n\n"
            + "\n\n".join(result_blocks)
        )
        return as_output(self._wrap_untrusted(markdown))

    def _resolve_provider_order(self, default_order: List[str]) -> List[str]:
        raw = os.getenv("WEB_SEARCH_PROVIDER_ORDER", "").strip()
        if not raw:
            return default_order

        requested = [part.strip().lower() for part in raw.split(",") if part.strip()]
        valid = [name for name in requested if name in default_order]
        if not valid:
            return default_order

        # Preserve user-defined priority first, then append missing defaults.
        merged = list(valid)
        for name in default_order:
            if name not in merged:
                merged.append(name)
        return merged

    def _search_google_custom_search(
        self, query: str, max_results: int
    ) -> Tuple[List[Tuple[str, str]], Optional[str]]:
        api_key = (
            os.getenv("GOOGLE_CSE_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )
        engine_id = (
            os.getenv("GOOGLE_CSE_ENGINE_ID", "").strip()
            or os.getenv("GOOGLE_CSE_CX", "").strip()
        )
        if not api_key or not engine_id:
            return [], "Error: GOOGLE_CSE_API_KEY/GOOGLE_CSE_ENGINE_ID is not configured."

        params = {
            "key": api_key,
            "cx": engine_id,
            "q": query,
            "num": max(1, min(max_results, 10)),
            "safe": "off",
        }
        try:
            response = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return [], f"Error: Google Custom Search request failed: {exc}"
        except ValueError:
            return [], "Error: Google Custom Search response is not valid JSON."

        items = payload.get("items", [])
        links: List[Tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url:
                continue
            links.append((title or url, url))
            if len(links) >= max_results:
                break
        return links, None

    def _search_serper(self, query: str, max_results: int) -> Tuple[List[Tuple[str, str]], Optional[str]]:
        api_key = os.getenv("SEARCH_API_KEY", "").strip()
        if not api_key:
            return [], "Error: SEARCH_API_KEY is not configured."

        try:
            response = requests.post(
                "https://google.serper.dev/search",
                json={"q": query},
                timeout=self.timeout,
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return [], f"Error: Serper search request failed: {exc}"
        except ValueError:
            return [], "Error: Serper search response is not valid JSON."

        organic_results = payload.get("organic", [])
        links: List[Tuple[str, str]] = []
        for item in organic_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url:
                continue
            links.append((title or url, url))
            if len(links) >= max_results:
                break
        return links, None

    def _search_duckduckgo(self, query: str, max_results: int) -> Tuple[List[Tuple[str, str]], Optional[str]]:
        url = "https://duckduckgo.com/html/"
        try:
            response = requests.get(
                url,
                params={"q": query},
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return [], f"Error: web search request failed: {exc}"

        html_text = response.text
        links: List[Tuple[str, str]] = []
        for href, raw_title in self._extract_result_links(html_text):
            title = self._strip_html(raw_title)
            resolved_url = self._resolve_duckduckgo_redirect(href)
            if not resolved_url:
                continue
            links.append((title or resolved_url, resolved_url))
            if len(links) >= max_results:
                break
        return links, None

    def _extract_result_links(self, html_text: str) -> List[Tuple[str, str]]:
        # Primary: result anchors where href/class attribute order can vary.
        anchor_pattern = re.compile(r"<a\\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
        href_pattern = re.compile(r'href="([^"]+)"', re.IGNORECASE)
        class_pattern = re.compile(r'class="([^"]+)"', re.IGNORECASE)

        extracted: List[Tuple[str, str]] = []
        for anchor in anchor_pattern.findall(html_text):
            href_match = href_pattern.search(anchor)
            class_match = class_pattern.search(anchor)
            if not href_match:
                continue
            class_value = class_match.group(1) if class_match else ""
            if "result__a" not in class_value and "result-link" not in class_value:
                continue
            href = href_match.group(1)
            title = self._strip_html(anchor)
            extracted.append((href, title))

        if extracted:
            return extracted

        # Fallback: accept any duckduckgo redirect link if primary class matching fails.
        fallback_links = re.findall(r'<a[^>]*href="([^"]*duckduckgo\\.com/l/\\?[^"]+)"[^>]*>(.*?)</a>', html_text, flags=re.IGNORECASE | re.DOTALL)
        return [(href, self._strip_html(title)) for href, title in fallback_links]

    def _resolve_duckduckgo_redirect(self, url: str) -> Optional[str]:
        if not url:
            return None
        if url.startswith("http://") or url.startswith("https://"):
            parsed = urlparse(url)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
                target = parse_qs(parsed.query).get("uddg", [])
                if target:
                    return target[0]
            return url
        return None

    def _fetch_page_text(self, url: str) -> Tuple[str, Optional[str]]:
        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return "", f"Fetch failed: {exc}"

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return "", f"Skipped non-text content type: {content_type or 'unknown'}"

        sanitized = self._sanitize_html(response.text)
        markdown_text = self._html_to_markdown_text(sanitized)
        if not markdown_text.strip():
            return "(empty after sanitization)", None
        return markdown_text, None

    def _sanitize_html(self, html_text: str) -> str:
        # Strip risky and low-value blocks before plain-text conversion.
        no_script = re.sub(
            r"<(script|style|noscript|iframe|svg|canvas)[^>]*>.*?</\1>",
            "",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        no_hidden = re.sub(
            r"<[^>]*(?:hidden|display\s*:\s*none|visibility\s*:\s*hidden)[^>]*>.*?</[^>]+>",
            "",
            no_script,
            flags=re.IGNORECASE | re.DOTALL,
        )
        no_handlers = re.sub(r"\son\w+\s*=\s*\"[^\"]*\"", "", no_hidden, flags=re.IGNORECASE)
        no_handlers = re.sub(r"\son\w+\s*=\s*'[^']*'", "", no_handlers, flags=re.IGNORECASE)
        return no_handlers

    def _html_to_markdown_text(self, html_text: str) -> str:
        blockified = re.sub(r"</(p|div|section|article|h\d|li|tr|br)>", "\n", html_text, flags=re.IGNORECASE)
        text = self._strip_html(blockified)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _strip_html(self, value: str) -> str:
        no_tags = re.sub(r"<[^>]+>", "", value)
        unescaped = html.unescape(no_tags)
        return re.sub(r"[ \t]+", " ", unescaped).strip()

    def _wrap_untrusted(self, content: str) -> str:
        return f"<UNTRUSTED_WEB_DATA>\n{content}\n</UNTRUSTED_WEB_DATA>"
