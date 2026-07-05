import json
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.ai_core.tool_executor import BaseTool


_STRIP_CONTAINERS = {"script", "style", "noscript", "template", "svg", "canvas"}
_DROP_TAGS = {"img", "picture", "source", "video", "audio", "iframe"}
_VOID_TAGS = {"br", "hr", "meta", "link", "input", "area", "base", "col", "embed", "param", "track", "wbr"}


@dataclass
class _Node:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List["_Node"] = field(default_factory=list)
    keep_self: bool = False


class _SkeletonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="root")
        self.stack: List[_Node] = [self.root]
        self._strip_depth = 0
        self._last_start_pushed = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._last_start_pushed = False
        lowered_tag = tag.lower()
        if lowered_tag in _STRIP_CONTAINERS:
            self._strip_depth += 1
            return
        if self._strip_depth > 0:
            return
        if lowered_tag in _DROP_TAGS:
            return

        kept_attrs: Dict[str, str] = {}
        for key, value in attrs:
            if value is None:
                continue
            lowered_key = key.lower()
            if lowered_key in {"id", "class"} or lowered_key.startswith("data-"):
                cleaned = " ".join(value.split())
                if cleaned:
                    kept_attrs[lowered_key] = cleaned

        node = _Node(
            tag=lowered_tag,
            attrs=kept_attrs,
            keep_self=bool(kept_attrs),
        )
        self.stack[-1].children.append(node)
        self.stack.append(node)
        self._last_start_pushed = True

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._last_start_pushed and len(self.stack) > 1:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if lowered_tag in _STRIP_CONTAINERS:
            if self._strip_depth > 0:
                self._strip_depth -= 1
            return
        if self._strip_depth > 0:
            return
        if lowered_tag in _DROP_TAGS:
            return
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        # Text content is intentionally discarded for skeleton mode.
        return


class DOMSkeletonXrayTool(BaseTool):
    def __init__(self, timeout: int = 10, max_skeleton_chars: int = 60000):
        self.timeout = timeout
        self.max_skeleton_chars = max_skeleton_chars
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "dom_skeleton_xray"

    @property
    def description(self) -> str:
        return (
            "Fetch and compress an HTML page into a DOM skeleton by removing text, images, and scripts, "
            "while preserving structural tags that contain id/class/data-* attributes."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_url": {
                    "type": "string",
                    "description": "The target page URL to analyze.",
                },
                "render_dynamic": {
                    "type": "boolean",
                    "description": "Enable headless-browser rendering to simulate JS-loaded content.",
                },
                "dynamic_wait_ms": {
                    "type": "integer",
                    "description": "Extra wait time in milliseconds after first paint for dynamic content.",
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
            "required": ["target_url"],
        }

    def execute(
        self,
        target_url: str,
        render_dynamic: bool = False,
        dynamic_wait_ms: int = 1500,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        if not target_url.strip():
            return "Error: target_url is required."
        parsed = urlparse(target_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "Error: target_url must be a valid absolute http/https URL."

        html_text, fetch_error, render_mode_used, render_notice = self._fetch_html(
            target_url.strip(),
            render_dynamic=render_dynamic,
            dynamic_wait_ms=dynamic_wait_ms,
        )
        if fetch_error:
            content = json.dumps(
                {
                    "target_url": target_url.strip(),
                    "error": fetch_error,
                    "render_mode_used": render_mode_used,
                    "render_notice": render_notice,
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

        parser = _SkeletonParser()
        parser.feed(html_text)
        parser.close()

        kept_root = self._prune_tree(parser.root)
        selector_counter: Counter = Counter()
        skeleton_html = self._render_children(kept_root, selector_counter)
        truncated = False
        if len(skeleton_html) > self.max_skeleton_chars:
            truncated = True
            skeleton_html = skeleton_html[: self.max_skeleton_chars] + "\n<!-- truncated -->"

        result = {
            "target_url": target_url.strip(),
            "skeleton_html": skeleton_html,
            "key_selectors": [
                {"selector": key, "count": count}
                for key, count in selector_counter.most_common(30)
            ],
            "stats": {
                "skeleton_length": len(skeleton_html),
                "truncated": truncated,
                "render_mode_used": render_mode_used,
                "render_notice": render_notice,
            },
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

    def _prune_tree(self, node: _Node) -> _Node:
        new_node = _Node(tag=node.tag, attrs=dict(node.attrs), keep_self=node.keep_self)
        for child in node.children:
            pruned_child = self._prune_tree(child)
            if pruned_child.keep_self or pruned_child.children:
                new_node.children.append(pruned_child)
        if new_node.children:
            new_node.keep_self = True
        return new_node

    def _render_children(self, root: _Node, selector_counter: Counter) -> str:
        parts: List[str] = []
        for child in root.children:
            rendered = self._render_node(child, selector_counter)
            if rendered:
                parts.append(rendered)
        return "\n".join(parts).strip()

    def _render_node(self, node: _Node, selector_counter: Counter) -> str:
        if not node.keep_self and not node.children:
            return ""

        attrs_fragments: List[str] = []
        for key in sorted(node.attrs.keys()):
            value = node.attrs[key].replace('"', "&quot;")
            attrs_fragments.append(f'{key}="{value}"')
            self._collect_selectors(node.tag, key, value, selector_counter)
        attrs_text = (" " + " ".join(attrs_fragments)) if attrs_fragments else ""

        if not node.children and node.tag in _VOID_TAGS:
            return f"<{node.tag}{attrs_text} />"

        children_html = "\n".join(
            [chunk for chunk in (self._render_node(child, selector_counter) for child in node.children) if chunk]
        )
        if children_html:
            return f"<{node.tag}{attrs_text}>\n{children_html}\n</{node.tag}>"
        return f"<{node.tag}{attrs_text}></{node.tag}>"

    def _collect_selectors(self, tag: str, key: str, value: str, selector_counter: Counter) -> None:
        if key == "id":
            selector_counter[f"#{value}"] += 1
            selector_counter[f"{tag}#{value}"] += 1
        elif key == "class":
            for class_name in value.split():
                selector_counter[f".{class_name}"] += 1
                selector_counter[f"{tag}.{class_name}"] += 1
        elif key.startswith("data-"):
            selector_counter[f"[{key}]"] += 1
            selector_counter[f"{tag}[{key}]"] += 1
