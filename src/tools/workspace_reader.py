import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.ai_core.llm import LMWrapper
from src.ai_core.tool_executor import BaseTool


class _WorkspaceToolBase(BaseTool):
    def __init__(self, root_dir: str = ".", allowed_scope: Optional[str] = None):
        workspace_root = Path(root_dir).resolve()
        if allowed_scope:
            workspace_root = (workspace_root / allowed_scope).resolve()
        self.workspace_root = workspace_root
        self.supported_text_extensions = {
            ".txt",
            ".md",
            ".json",
            ".csv",
            ".py",
            ".yaml",
            ".yml",
            ".log",
            ".html",
            ".css",
            ".js",
            ".php",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
        }
        self.max_summary_chars = 12000
        self.max_condensed_summary_chars = 400

    def _workspace_not_found_message(self) -> str:
        return f"Workspace scope not found: {self.workspace_root}"

    def _resolve_workspace_path(self, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            return None, self._workspace_not_found_message()

        candidate = (self.workspace_root / file_path).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            return None, "Invalid file_path. Only files inside configured workspace scope are allowed."

        if not candidate.exists() or not candidate.is_file():
            return None, f"Workspace file not found: {file_path}"

        return candidate, None

    def _is_supported_text_file(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_text_extensions

    def _read_text_file(self, file_path: Path) -> Tuple[Optional[str], Optional[str]]:
        if not self._is_supported_text_file(file_path):
            return None, (
                "Unsupported file type for text operations. "
                f"Supported extensions: {', '.join(sorted(self.supported_text_extensions))}"
            )

        for encoding in ("utf-8", "utf-8-sig"):
            try:
                return file_path.read_text(encoding=encoding), None
            except UnicodeDecodeError:
                continue

        return None, f"Unable to decode file as UTF-8 text: {file_path.name}"

    def _split_paragraphs(self, text: str) -> List[str]:
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]

    def _extract_keywords(self, text: str, limit: int = 8) -> List[str]:
        english_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "have",
            "will",
            "your",
            "about",
            "into",
            "json",
            "python",
            "class",
            "def",
            "return",
            "none",
        }

        counter: Counter[str] = Counter()
        for token in english_tokens + chinese_tokens:
            if token in stop_words:
                continue
            counter[token] += 1

        return [token for token, _ in counter.most_common(limit)]

    def _summarize_paragraph(self, paragraph: str, max_length: int = 120) -> str:
        compact = " ".join(paragraph.split())
        sentences = re.split(r"(?<=[。！？.!?])\s*", compact)
        summary = sentences[0] if sentences and sentences[0] else compact
        if len(summary) <= max_length:
            return summary
        return summary[: max_length - 3] + "..."

    def _compress_with_gemini(self, file_path: str, text: str) -> Optional[str]:
        api_key = os.getenv("GEMINI_KEY")
        if not api_key:
            return None

        try:
            model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
            llm = LMWrapper(
                provider="gemini",
                model=model,
                api_key=api_key,
                request_options={"temperature": 0.2, "max_tokens": 256, "timeout": 30},
            )
            llm.set_system_prompt(
                "You summarize workspace files into grounded plain text. "
                "Keep within 400 Chinese characters and never invent facts."
            )
            response = llm.get_completion(
                [
                    {
                        "role": "user",
                        "content": (
                            f"請將以下檔案內容摘要為不超過 {self.max_condensed_summary_chars} 字。\n"
                            f"File: {file_path}\n\n{text}"
                        ),
                    }
                ]
            )
            content = (response.get("content") or "").strip()
        except Exception:
            return None

        if not content:
            return None
        if len(content) <= self.max_condensed_summary_chars:
            return content
        return content[: self.max_condensed_summary_chars - 3] + "..."

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


class ReadWorkspaceFileTool(_WorkspaceToolBase):
    @property
    def name(self) -> str:
        return "read_workspace_file"

    @property
    def description(self) -> str:
        return (
            "Read a text file inside the configured workspace scope by optional line range. "
            "Use this for readonly code or document inspection."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative file path inside configured workspace scope.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-based start line.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional 1-based end line.",
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
            "required": ["file_path"],
        }

    def execute(
        self,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        resolved_path, error = self._resolve_workspace_path(file_path)
        if error:
            return error

        text, read_error = self._read_text_file(resolved_path)
        if read_error:
            return read_error

        lines = text.splitlines()
        if start_line is None and end_line is None:
            start = 1
            end = len(lines)
        else:
            start = start_line or 1
            end = end_line or start
            if start < 1 or end < start:
                return "Invalid line range. start_line must be >= 1 and end_line must be >= start_line."

        selected_lines = lines[start - 1:end]
        if not selected_lines:
            return f"File: {file_path}\n\nNo content found in requested line range."

        numbered_lines = [
            f"{index}: {content}"
            for index, content in enumerate(selected_lines, start=start)
        ]
        content = f"File: {file_path}\nScope: {self.workspace_root}\n\n" + "\n".join(numbered_lines)
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )


class SummarizeWorkspaceFileTool(_WorkspaceToolBase):
    @property
    def name(self) -> str:
        return "summarize_workspace_file"

    @property
    def description(self) -> str:
        return (
            "Summarize a text file inside the configured workspace scope and extract key topics. "
            "Use this after reading a long file."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative file path inside configured workspace scope.",
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
            "required": ["file_path"],
        }

    def execute(
        self,
        file_path: str,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        resolved_path, error = self._resolve_workspace_path(file_path)
        if error:
            return error

        text, read_error = self._read_text_file(resolved_path)
        if read_error:
            return read_error

        truncated = False
        if len(text) > self.max_summary_chars:
            text = text[: self.max_summary_chars]
            truncated = True

        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return f"File '{file_path}' is empty."

        condensed_summary = self._compress_with_gemini(file_path, text)
        if not condensed_summary:
            condensed_summary = self._summarize_paragraph(
                " ".join(paragraphs[:3]),
                max_length=self.max_condensed_summary_chars,
            )

        summary_lines = [
            f"File: {file_path}",
            f"Scope: {self.workspace_root}",
            "Overall summary:",
            condensed_summary,
            "",
            "Overall keywords: " + (", ".join(self._extract_keywords(text)) or "none"),
            "",
            "Paragraph summaries:",
        ]
        for index, paragraph in enumerate(paragraphs, start=1):
            summary_lines.append(f"{index}. Summary: {self._summarize_paragraph(paragraph)}")
            summary_lines.append(
                "   Keywords: " + (", ".join(self._extract_keywords(paragraph, limit=5)) or "none")
            )

        if truncated:
            summary_lines.append("")
            summary_lines.append("Note: File content was truncated before summarization.")

        content = "\n".join(summary_lines)
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )
