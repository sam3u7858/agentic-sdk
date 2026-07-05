import json
import os
import re
from collections import Counter
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from src.ai_core.llm import LMWrapper
from src.ai_core.tool_executor import BaseTool


class URLSecondaryLLMSummarizerTool(BaseTool):
    def __init__(self, timeout: int = 15, max_source_chars: int = 60000):
        self.timeout = timeout
        self.max_source_chars = max_source_chars
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "summarize_url_with_secondary_llm"

    @property
    def description(self) -> str:
        return (
            "Summarize URL content using a secondary LLM into <=300 Chinese characters and return "
            "keywords and important facts while preserving required original content."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target webpage URL."},
                "preserve_original_content": {
                    "type": "string",
                    "description": "Critical phrases or facts that must be preserved in the summary.",
                },
                "instruction": {
                    "type": "string",
                    "description": "Extra summarization constraints.",
                },
                "max_summary_chars": {
                    "type": "integer",
                    "description": "Maximum summary length in Chinese characters. Default 300.",
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
            "required": ["url", "preserve_original_content", "instruction"],
        }

    def execute(
        self,
        url: str,
        preserve_original_content: str,
        instruction: str,
        max_summary_chars: int = 300,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
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

        if not url.strip():
            return as_output("Error: url is required.")
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return as_output("Error: url must be a valid absolute http/https URL.")

        html_text, fetch_error = self._fetch_html(url.strip())
        if fetch_error:
            return as_output(json.dumps(
                {"url": url.strip(), "error": fetch_error},
                ensure_ascii=False,
                indent=2,
            ))

        source_text = self._html_to_text(html_text)
        if len(source_text) > self.max_source_chars:
            source_text = source_text[: self.max_source_chars]

        cap = max(120, min(int(max_summary_chars), 600))
        llm_payload = self._summarize_with_secondary_llm(
            url=url.strip(),
            source_text=source_text,
            preserve_original_content=preserve_original_content,
            instruction=instruction,
            max_summary_chars=cap,
        )
        if llm_payload is not None:
            return as_output(json.dumps(llm_payload, ensure_ascii=False, indent=2))

        # Fallback when secondary LLM is unavailable.
        fallback = self._fallback_summary(
            url=url.strip(),
            source_text=source_text,
            preserve_original_content=preserve_original_content,
            instruction=instruction,
            max_summary_chars=cap,
        )
        return as_output(json.dumps(fallback, ensure_ascii=False, indent=2))

    def _fetch_html(self, url: str) -> Tuple[str, Optional[str]]:
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
            return "", f"Skipped non-html content type: {content_type or 'unknown'}"
        return response.text, None

    def _html_to_text(self, html_text: str) -> str:
        no_script = re.sub(
            r"<(script|style|noscript|svg|canvas|iframe)[^>]*>.*?</\1>",
            "",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        with_breaks = re.sub(r"</(p|div|section|article|h\d|li|tr|br)>", "\n", no_script, flags=re.IGNORECASE)
        no_tags = re.sub(r"<[^>]+>", " ", with_breaks)
        text = unescape(no_tags)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    def _summarize_with_secondary_llm(
        self,
        *,
        url: str,
        source_text: str,
        preserve_original_content: str,
        instruction: str,
        max_summary_chars: int,
    ) -> Optional[Dict[str, Any]]:
        provider = os.getenv("SECONDARY_LLM_PROVIDER", "").strip().lower()
        if not provider:
            return None

        model = os.getenv("SECONDARY_LLM_MODEL", "").strip()
        if not model:
            return None

        api_key = os.getenv("SECONDARY_LLM_API_KEY", "").strip() or None
        base_url = os.getenv("SECONDARY_LLM_API_URL", "").strip() or None

        try:
            llm = LMWrapper(
                provider=provider,
                model=model,
                api_key=api_key,
                lm_api_url=base_url,
                request_options={"temperature": 0.2, "max_tokens": 700, "timeout": 45},
            )
            llm.set_system_prompt(
                "You are a strict summarizer. Return only valid JSON. "
                "Do not omit required preserved content."
            )
            response = llm.get_completion(
                [
                    {
                        "role": "user",
                        "content": (
                            "請根據以下網頁內容輸出 JSON。\n"
                            f"URL: {url}\n"
                            f"摘要上限: {max_summary_chars} 字\n"
                            f"必須保留原文內容: {preserve_original_content}\n"
                            f"額外指令: {instruction}\n\n"
                            "輸出格式:\n"
                            "{\n"
                            '  "summary": "不超過上限字數",\n'
                            '  "keywords": ["k1","k2","k3"],\n'
                            '  "important_points": ["p1","p2","p3"],\n'
                            '  "preserved_content_check": ["逐項列出你保留了哪些關鍵內容"]\n'
                            "}\n\n"
                            f"網頁原文:\n{source_text}"
                        ),
                    }
                ]
            )
            content = (response.get("content") or "").strip()
            payload = json.loads(content)
            if not isinstance(payload, dict):
                return None
            summary = str(payload.get("summary") or "").strip()
            if len(summary) > max_summary_chars:
                summary = summary[: max_summary_chars - 3] + "..."

            keywords = payload.get("keywords")
            if not isinstance(keywords, list):
                keywords = self._extract_keywords(source_text)

            points = payload.get("important_points")
            if not isinstance(points, list):
                points = []

            preserved_check = payload.get("preserved_content_check")
            if not isinstance(preserved_check, list):
                preserved_check = []

            return {
                "url": url,
                "summary": summary,
                "keywords": [str(item) for item in keywords][:12],
                "important_points": [str(item) for item in points][:8],
                "preserved_content_check": [str(item) for item in preserved_check][:8],
                "secondary_llm_used": True,
                "secondary_llm_provider": provider,
                "secondary_llm_model": model,
            }
        except Exception:
            return None

    def _fallback_summary(
        self,
        *,
        url: str,
        source_text: str,
        preserve_original_content: str,
        instruction: str,
        max_summary_chars: int,
    ) -> Dict[str, Any]:
        keywords = self._extract_keywords(source_text)
        short = " ".join(source_text.split())[: max_summary_chars - 3]
        if len(short) < len(source_text):
            short += "..."
        points = self._extract_points(source_text, limit=4)
        return {
            "url": url,
            "summary": short,
            "keywords": keywords,
            "important_points": points,
            "preserved_content_check": [preserve_original_content],
            "instruction_echo": instruction,
            "secondary_llm_used": False,
            "warning": "SECONDARY_LLM_PROVIDER/MODEL not configured. Fallback summarizer used.",
        }

    def _extract_keywords(self, text: str, limit: int = 10) -> List[str]:
        english_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        counter: Counter[str] = Counter()
        for token in english_tokens + chinese_tokens:
            counter[token] += 1
        return [token for token, _ in counter.most_common(limit)]

    def _extract_points(self, text: str, limit: int = 4) -> List[str]:
        compact = " ".join(text.split())
        sentences = re.split(r"(?<=[。！？.!?])\s+", compact)
        points: List[str] = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            points.append(sentence[:120])
            if len(points) >= limit:
                break
        return points
