import json
import re
import time
from collections import deque
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests

from src.ai_core.tool_executor import BaseTool


_NAV_HINTS = {
    "nav",
    "navbar",
    "menu",
    "header",
    "breadcrumb",
    "breadcrumbs",
    "topnav",
    "global-nav",
    "main-nav",
}
_CATEGORY_HINTS = {
    "category",
    "categories",
    "catalog",
    "listing",
    "list",
    "archive",
    "taxonomy",
    "filter",
    "product-list",
}


def _normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    cleaned = parsed._replace(fragment="")
    # Normalize trailing slash except root.
    path = cleaned.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    cleaned = cleaned._replace(path=path)
    return urlunparse(cleaned)


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", unescape(match.group(1))).strip()
    return title[:200]


def _url_label(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if path == "/":
        return "/"
    parts = [part for part in path.split("/") if part]
    return parts[-1] if parts else path


class _LinkCollector(HTMLParser):
    """Collect links and infer lightweight context labels."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.context_stack: List[Tuple[str, str, str]] = []
        self.links: List[Dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_map = {k.lower(): (v or "") for k, v in attrs}
        class_value = attrs_map.get("class", "").lower()
        id_value = attrs_map.get("id", "").lower()
        self.context_stack.append((tag.lower(), class_value, id_value))

        if tag.lower() != "a":
            return
        href = attrs_map.get("href", "").strip()
        if not href:
            return

        context_tokens = " ".join(
            [item[0] + " " + item[1] + " " + item[2] for item in self.context_stack[-4:]]
        )
        is_nav = any(token in context_tokens for token in _NAV_HINTS)
        is_category = any(token in context_tokens for token in _CATEGORY_HINTS)
        self.links.append(
            {
                "href": href,
                "is_nav": is_nav,
                "is_category": is_category,
            }
        )

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.context_stack:
            self.context_stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self.context_stack:
            self.context_stack.pop()


class WebTopologySpiderTool(BaseTool):
    def __init__(self, timeout: int = 10, max_pages: int = 180):
        self.timeout = timeout
        self.max_pages = max_pages
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "web_topology_spider"

    @property
    def description(self) -> str:
        return (
            "Explore a website topology from a seed URL, estimate page hierarchy, and return "
            "a structured JSON tree with navigation links, category links, and per-path subpage estimates."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seed_url": {
                    "type": "string",
                    "description": "The starting URL for exploration.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Exploration depth. Defaults to 2.",
                },
                "url_pattern_filter": {
                    "type": "string",
                    "description": "Optional substring filter for URL path, such as /weapons/.",
                },
                "render_dynamic": {
                    "type": "boolean",
                    "description": "Enable headless-browser rendering to simulate JS-loaded content.",
                },
                "dynamic_wait_ms": {
                    "type": "integer",
                    "description": "Extra wait time in milliseconds after first paint for dynamic content.",
                },
                "max_runtime_seconds": {
                    "type": "integer",
                    "description": "Hard time limit for one crawl run to avoid long blocking.",
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
            "required": ["seed_url"],
        }

    def execute(
        self,
        seed_url: str,
        max_depth: int = 2,
        url_pattern_filter: Optional[str] = None,
        render_dynamic: bool = False,
        dynamic_wait_ms: int = 1500,
        max_runtime_seconds: int = 45,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        if not seed_url.strip():
            return "Error: seed_url is required."

        normalized_seed = _normalize_url(seed_url)
        parsed_seed = urlparse(normalized_seed)
        if parsed_seed.scheme not in {"http", "https"} or not parsed_seed.netloc:
            return "Error: seed_url must be a valid absolute http/https URL."

        capped_depth = max(0, min(int(max_depth), 5))
        capped_runtime_seconds = max(5, min(int(max_runtime_seconds), 300))
        pattern = (url_pattern_filter or "").strip()
        runtime_event_handler = kwargs.get("_runtime_event_handler")
        debug_logs: List[Dict[str, Any]] = []

        def push_debug(message: str, **fields: Any) -> None:
            record: Dict[str, Any] = {"message": message}
            record.update(fields)
            if len(debug_logs) < 400:
                debug_logs.append(record)
            if callable(runtime_event_handler):
                try:
                    runtime_event_handler(record)
                except Exception:
                    # Debug event failure must not break crawling.
                    pass

        started_at = time.monotonic()
        deadline = started_at + capped_runtime_seconds

        visited: Set[str] = set()
        queue: Deque[Tuple[str, int]] = deque([(normalized_seed, 0)])
        nodes: Dict[str, Dict[str, Any]] = {}
        parent_map: Dict[str, Optional[str]] = {normalized_seed: None}
        nav_links: Set[str] = set()
        category_links: Set[str] = set()
        render_mode_used = "static_http"
        render_notice: Optional[str] = None
        stop_reason = "completed"
        source_mode = "crawl"

        push_debug(
            "crawl_started",
            seed_url=normalized_seed,
            max_depth=capped_depth,
            pattern_filter=(pattern or None),
            render_dynamic=render_dynamic,
            max_runtime_seconds=capped_runtime_seconds,
        )

        sitemap_urls = self._collect_sitemap_urls(
            seed_url=normalized_seed,
            pattern=pattern,
            push_debug=push_debug,
        )
        if sitemap_urls:
            source_mode = "sitemap"
            stop_reason = "sitemap_preferred"
            visited = set(sitemap_urls)
            visited.add(normalized_seed)
            nodes, parent_map = self._build_nodes_from_urls(normalized_seed, list(visited))
            nav_links, category_links = self._infer_navigation_groups(list(visited), normalized_seed)
            push_debug(
                "sitemap_mode_activated",
                sitemap_url_count=len(sitemap_urls),
                total_urls=len(visited),
            )

        while source_mode == "crawl" and queue and len(visited) < self.max_pages:
            now = time.monotonic()
            if now >= deadline:
                stop_reason = "max_runtime_reached"
                push_debug(
                    "crawl_stopped_by_runtime_limit",
                    visited_pages=len(visited),
                    pending_queue=len(queue),
                    elapsed_seconds=round(now - started_at, 2),
                )
                break

            current_url, depth = queue.popleft()
            if current_url in visited:
                continue
            visited.add(current_url)
            push_debug(
                "fetch_page_started",
                depth=depth,
                url=current_url,
                visited_pages=len(visited),
                pending_queue=len(queue),
            )

            html_text, fetch_error, fetch_mode, fetch_notice = self._fetch_html(
                current_url,
                render_dynamic=render_dynamic,
                dynamic_wait_ms=dynamic_wait_ms,
            )
            if fetch_mode == "dynamic_browser":
                render_mode_used = "dynamic_browser"
            elif fetch_notice and render_notice is None:
                render_notice = fetch_notice
            push_debug(
                "fetch_page_finished",
                depth=depth,
                url=current_url,
                fetch_mode=fetch_mode,
                has_error=bool(fetch_error),
            )
            title = ""
            page_links: List[Dict[str, Any]] = []
            if html_text:
                title = _extract_title(html_text)
                page_links = self._collect_links(current_url, html_text)
                push_debug(
                    "links_collected",
                    depth=depth,
                    url=current_url,
                    internal_links=len(page_links),
                )

            node = nodes.setdefault(
                current_url,
                {
                    "url": current_url,
                    "title": title,
                    "depth": depth,
                    "children": [],
                    "page_error": fetch_error,
                },
            )
            if title and not node.get("title"):
                node["title"] = title
            node["depth"] = min(node.get("depth", depth), depth)
            if fetch_error:
                node["page_error"] = fetch_error

            if depth >= capped_depth:
                continue

            for entry in page_links:
                child_url = entry["url"]
                if pattern and pattern not in urlparse(child_url).path:
                    continue
                if child_url not in parent_map:
                    parent_map[child_url] = current_url
                    queue.append((child_url, depth + 1))
                    node["children"].append(child_url)
                if entry["is_nav"]:
                    nav_links.add(child_url)
                if entry["is_category"]:
                    category_links.add(child_url)

        if len(visited) >= self.max_pages and stop_reason == "completed":
            stop_reason = "max_pages_reached"
            push_debug("crawl_stopped_by_page_limit", visited_pages=len(visited))

        tree = self._build_tree(normalized_seed, nodes, parent_map)
        self._attach_subpage_estimates(tree)
        tree_text = self._render_tree_text(tree)
        elapsed_seconds = round(time.monotonic() - started_at, 2)
        push_debug(
            "crawl_finished",
            stop_reason=stop_reason,
            visited_pages=len(visited),
            discovered_pages=len(nodes),
            elapsed_seconds=elapsed_seconds,
        )

        result = {
            "seed_url": normalized_seed,
            "max_depth": capped_depth,
            "url_pattern_filter": pattern or None,
            "summary": {
                "source_mode": source_mode,
                "discovered_pages": len(nodes),
                "visited_pages": len(visited),
                "core_navigation_links": sorted(nav_links),
                "category_listing_links": sorted(category_links),
                "max_pages_limit": self.max_pages,
                "render_mode_used": render_mode_used,
                "render_notice": render_notice,
                "stop_reason": stop_reason,
                "elapsed_seconds": elapsed_seconds,
            },
            "topology_tree": tree,
            "topology_tree_text": tree_text,
            "debug_logs": debug_logs,
        }
        content = json.dumps(result, ensure_ascii=False, indent=2)
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

    def _collect_sitemap_urls(
        self,
        *,
        seed_url: str,
        pattern: str,
        push_debug: Callable[..., None],
    ) -> List[str]:
        parsed_seed = urlparse(seed_url)
        base = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
        candidate_sitemaps = {
            f"{base}/sitemap.xml",
            f"{base}/sitemap_index.xml",
        }
        robots_url = f"{base}/robots.txt"
        try:
            robots_resp = requests.get(
                robots_url,
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            if robots_resp.ok:
                for line in robots_resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url:
                            candidate_sitemaps.add(sitemap_url)
        except requests.RequestException:
            pass

        collected_urls: Set[str] = set()
        visited_maps: Set[str] = set()
        queue: Deque[str] = deque(sorted(candidate_sitemaps))
        max_sitemap_files = 20
        max_sitemap_urls = 5000

        while queue and len(visited_maps) < max_sitemap_files and len(collected_urls) < max_sitemap_urls:
            sitemap_url = queue.popleft()
            normalized_map_url = _normalize_url(sitemap_url)
            if normalized_map_url in visited_maps:
                continue
            visited_maps.add(normalized_map_url)
            push_debug("sitemap_fetch_started", sitemap_url=normalized_map_url)
            xml_text, err = self._fetch_plain_text(normalized_map_url)
            if err:
                push_debug("sitemap_fetch_failed", sitemap_url=normalized_map_url, error=err)
                continue
            discovered_urls, child_sitemaps = self._parse_sitemap_xml(xml_text)
            push_debug(
                "sitemap_parsed",
                sitemap_url=normalized_map_url,
                url_count=len(discovered_urls),
                child_sitemap_count=len(child_sitemaps),
            )
            for child_map in child_sitemaps:
                absolute = _normalize_url(urljoin(normalized_map_url, child_map))
                if absolute not in visited_maps:
                    queue.append(absolute)
            for item_url in discovered_urls:
                absolute = _normalize_url(urljoin(normalized_map_url, item_url))
                parsed = urlparse(absolute)
                if parsed.scheme not in {"http", "https"}:
                    continue
                if parsed.netloc.lower() != parsed_seed.netloc.lower():
                    continue
                if pattern and pattern not in parsed.path:
                    continue
                collected_urls.add(absolute)
                if len(collected_urls) >= max_sitemap_urls:
                    break

        if collected_urls:
            push_debug(
                "sitemap_urls_collected",
                sitemap_files=len(visited_maps),
                url_count=len(collected_urls),
            )
        return sorted(collected_urls)

    def _fetch_plain_text(self, url: str) -> Tuple[str, Optional[str]]:
        try:
            response = requests.get(
                url,
                timeout=self.timeout,
                headers={"User-Agent": self.default_user_agent},
            )
            response.raise_for_status()
            return response.text, None
        except requests.RequestException as exc:
            return "", f"Fetch failed: {exc}"

    def _parse_sitemap_xml(self, xml_text: str) -> Tuple[List[str], List[str]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return [], []

        urls: List[str] = []
        child_sitemaps: List[str] = []

        root_tag = root.tag.lower()
        if root_tag.endswith("sitemapindex"):
            for elem in root.iter():
                if elem.tag.lower().endswith("loc") and elem.text:
                    child_sitemaps.append(elem.text.strip())
            return urls, child_sitemaps

        if root_tag.endswith("urlset"):
            for url_node in root:
                if not url_node.tag.lower().endswith("url"):
                    continue
                for child in url_node:
                    if child.tag.lower().endswith("loc") and child.text:
                        urls.append(child.text.strip())
                        break
        return urls, child_sitemaps

    def _build_nodes_from_urls(
        self,
        seed_url: str,
        urls: List[str],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Optional[str]]]:
        parsed_seed = urlparse(seed_url)
        seed_segments = [seg for seg in parsed_seed.path.split("/") if seg]
        all_urls = sorted(set([seed_url] + [u for u in urls if u]))
        url_set = set(all_urls)

        nodes: Dict[str, Dict[str, Any]] = {}
        parent_map: Dict[str, Optional[str]] = {seed_url: None}
        for url in all_urls:
            parsed = urlparse(url)
            segments = [seg for seg in parsed.path.split("/") if seg]
            depth = max(0, len(segments) - len(seed_segments))
            nodes[url] = {
                "url": url,
                "title": "",
                "depth": depth,
                "children": [],
                "page_error": None,
            }
            if url == seed_url:
                continue

            parent = seed_url
            for idx in range(len(segments) - 1, -1, -1):
                candidate_path = "/" + "/".join(segments[:idx]) if idx > 0 else "/"
                candidate = _normalize_url(
                    urlunparse(parsed._replace(path=candidate_path, query="", fragment=""))
                )
                if candidate in url_set and candidate != url:
                    parent = candidate
                    break
            parent_map[url] = parent
        return nodes, parent_map

    def _infer_navigation_groups(
        self,
        urls: List[str],
        seed_url: str,
    ) -> Tuple[Set[str], Set[str]]:
        nav_links: Set[str] = set()
        category_links: Set[str] = set()
        seed = urlparse(seed_url)
        seed_segments = [seg for seg in seed.path.split("/") if seg]

        for url in urls:
            if url == seed_url:
                continue
            parsed = urlparse(url)
            segments = [seg for seg in parsed.path.split("/") if seg]
            relative_depth = max(0, len(segments) - len(seed_segments))
            if relative_depth <= 1:
                nav_links.add(url)
            if any(token in parsed.path.lower() for token in _CATEGORY_HINTS):
                category_links.add(url)
        return nav_links, category_links

    def _fetch_html(
        self,
        url: str,
        *,
        render_dynamic: bool,
        dynamic_wait_ms: int,
    ) -> Tuple[str, Optional[str], str, Optional[str]]:
        if render_dynamic:
            rendered_html, render_error = self._fetch_dynamic_html(url, dynamic_wait_ms=dynamic_wait_ms)
            if rendered_html:
                return rendered_html, None, "dynamic_browser", None
            # Fallback to static HTTP fetch when dynamic rendering is unavailable.
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
            return "", f"Fetch failed: {exc}", "static_http", fallback_notice

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and "text" not in content_type:
            return (
                "",
                f"Skipped non-html content type: {content_type or 'unknown'}",
                "static_http",
                fallback_notice,
            )
        return response.text, None, "static_http", fallback_notice

    def _fetch_dynamic_html(self, url: str, *, dynamic_wait_ms: int) -> Tuple[str, Optional[str]]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return "", "Playwright is not installed in runtime environment."

        wait_ms = max(0, min(int(dynamic_wait_ms), 15000))
        timeout_ms = max(1000, int(self.timeout * 1000))
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.default_user_agent)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
                # A short scroll helps trigger some lazy-loaded banners.
                page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight, 1200));")
                if wait_ms > 0:
                    page.wait_for_timeout(min(wait_ms, 1200))
                html_text = page.content()
                browser.close()
                return html_text, None
        except Exception as exc:
            return "", f"Dynamic render failed: {exc}"

    def _collect_links(self, current_url: str, html_text: str) -> List[Dict[str, Any]]:
        collector = _LinkCollector()
        collector.feed(html_text)

        current_netloc = urlparse(current_url).netloc.lower()
        seen: Set[str] = set()
        links: List[Dict[str, Any]] = []
        for item in collector.links:
            href = item.get("href", "").strip()
            if not href:
                continue
            if href.startswith(("mailto:", "javascript:", "tel:", "#")):
                continue

            absolute = _normalize_url(urljoin(current_url, href))
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.netloc.lower() != current_netloc:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(
                {
                    "url": absolute,
                    "is_nav": bool(item.get("is_nav")),
                    "is_category": bool(item.get("is_category")),
                }
            )
        return links

    def _build_tree(
        self,
        root_url: str,
        nodes: Dict[str, Dict[str, Any]],
        parent_map: Dict[str, Optional[str]],
    ) -> Dict[str, Any]:
        children_map: Dict[str, List[str]] = {}
        for child, parent in parent_map.items():
            if parent is None:
                continue
            children_map.setdefault(parent, []).append(child)

        def render(url: str) -> Dict[str, Any]:
            node = nodes.get(
                url,
                {"url": url, "title": "", "depth": 0, "children": [], "page_error": None},
            )
            child_urls = children_map.get(url, [])
            rendered_children = [render(child_url) for child_url in child_urls]
            return {
                "url": node.get("url", url),
                "title": node.get("title", ""),
                "depth": node.get("depth", 0),
                "estimated_subpage_count": 0,
                "children": rendered_children,
                "page_error": node.get("page_error"),
            }

        return render(root_url)

    def _attach_subpage_estimates(self, node: Dict[str, Any]) -> int:
        total_descendants = 0
        for child in node.get("children", []):
            total_descendants += 1 + self._attach_subpage_estimates(child)
        node["estimated_subpage_count"] = total_descendants
        return total_descendants

    def _render_tree_text(self, root_node: Dict[str, Any]) -> str:
        root_url = str(root_node.get("url", ""))
        root_label = _url_label(root_url)
        root_title = str(root_node.get("title") or "").strip()
        root_count = int(root_node.get("estimated_subpage_count", 0))
        if root_title:
            root_line = f"{root_label} [{root_count}] ({root_title})"
        else:
            root_line = f"{root_label} [{root_count}]"

        lines = [root_line]

        def walk(node: Dict[str, Any], prefix: str) -> None:
            children = node.get("children", [])
            for index, child in enumerate(children):
                is_last = index == len(children) - 1
                connector = "└── " if is_last else "├── "
                extension = "    " if is_last else "│   "

                child_url = str(child.get("url", ""))
                child_label = _url_label(child_url)
                child_title = str(child.get("title") or "").strip()
                child_count = int(child.get("estimated_subpage_count", 0))
                if child_title:
                    node_text = f"{child_label} [{child_count}] ({child_title})"
                else:
                    node_text = f"{child_label} [{child_count}]"

                lines.append(prefix + connector + node_text)
                walk(child, prefix + extension)

        walk(root_node, "")
        return "\n".join(lines)
