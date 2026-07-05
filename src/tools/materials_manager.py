import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.ai_core.llm import LMWrapper
from src.ai_core.tool_executor import BaseTool


class _MaterialsToolBase(BaseTool):
    def __init__(self, project_root: str = ".", search_dirs: Optional[List[str]] = None):
        self.project_root = Path(project_root).resolve()
        normalized_dirs = search_dirs or ["materials"]
        self.search_roots: Dict[str, Path] = {}
        for dir_name in normalized_dirs:
            clean_name = str(dir_name).strip().replace("\\", "/").lstrip("./").lstrip("@").strip("/")
            if not clean_name:
                continue
            self.search_roots[clean_name] = (self.project_root / clean_name).resolve()
        if not self.search_roots:
            self.search_roots["materials"] = (self.project_root / "materials").resolve()
        self.materials_root = self.search_roots.get("materials", next(iter(self.search_roots.values())))
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
            ".hpp"
        }
        self.max_summary_chars = 12000
        self.max_condensed_summary_chars = 400

    def _materials_exists(self) -> bool:
        return self.materials_root.exists() and self.materials_root.is_dir()

    def _materials_not_found_message(self) -> str:
        return (
            "Materials directory not found. Expected folder: "
            f"{self.materials_root}"
        )

    def _resolve_material_path(self, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
        clean_file_path = file_path.strip().replace("\\", "/")
        if clean_file_path.startswith("./"):
            clean_file_path = clean_file_path[2:]
        clean_file_path = clean_file_path.lstrip("@")
        clean_file_path = clean_file_path.strip("/")
        if not clean_file_path:
            return None, "Invalid file_path."

        roots_to_try: List[Tuple[str, Path]] = []
        for root_name, root_path in self.search_roots.items():
            prefix = f"{root_name}/"
            if clean_file_path.startswith(prefix):
                remainder = clean_file_path[len(prefix):]
                roots_to_try = [(root_name, root_path / remainder)]
                break
        if not roots_to_try:
            roots_to_try = [(root_name, root_path / clean_file_path) for root_name, root_path in self.search_roots.items()]

        for root_name, raw_candidate in roots_to_try:
            root_path = self.search_roots[root_name]
            if not root_path.exists() or not root_path.is_dir():
                continue
            candidate = raw_candidate.resolve()
            try:
                candidate.relative_to(root_path)
            except ValueError:
                continue
            if candidate.exists() and candidate.is_file():
                return candidate, None

        readable_roots = ", ".join([f"./{name}/" for name in self.search_roots.keys()])
        return None, f"Material file not found: {file_path}. searched_roots={readable_roots}"

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

    def _count_lines(self, file_path: Path) -> str:
        text, error = self._read_text_file(file_path)
        if error:
            return "unavailable"
        return str(len(text.splitlines()))

    def _format_size(self, size_in_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = float(size_in_bytes)
        unit = units[0]
        for unit in units:
            if size < 1024.0 or unit == units[-1]:
                break
            size /= 1024.0
        if unit == "B":
            return f"{int(size)} {unit}"
        return f"{size:.1f} {unit}"

    def _split_paragraphs(self, text: str) -> List[str]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        return paragraphs

    def _extract_keywords(self, text: str, limit: int = 5) -> List[str]:
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
            "段落",
            "內容",
            "使用者",
            "影片",
            "素材",
        }

        counter = Counter()
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
                request_options={
                    "temperature": 0.2,
                    "max_tokens": 256,
                    "timeout": 30,
                },
            )
            llm.set_system_prompt(
                "You compress source material into a grounded summary. "
                "Return plain text only. Keep the answer within 400 Chinese characters. "
                "Do not invent facts."
            )

            response = llm.get_completion(
                [
                    {
                        "role": "user",
                        "content": (
                            f"Please summarize the following file content into at most "
                            f"{self.max_condensed_summary_chars} Chinese characters.\n"
                            f"File: {file_path}\n\n"
                            f"Content:\n{text}"
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


class ListMaterialsTool(_MaterialsToolBase):
    @property
    def name(self) -> str:
        return "list_materials"

    @property
    def description(self) -> str:
        return (
            "List all files under ./materials with relative path, line count, and file size. "
            "Use this before reading materials so you can identify relevant source files."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
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
        }

    def execute(
        self,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs
    ) -> Any:
        if not self._materials_exists():
            content = self._materials_not_found_message()
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        files = sorted(path for path in self.materials_root.rglob("*") if path.is_file())
        if not files:
            content = "No files found in ./materials."
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        lines = ["Materials files:"]
        for file_path in files:
            relative_path = file_path.relative_to(self.materials_root).as_posix()
            line_count = self._count_lines(file_path)
            file_size = self._format_size(file_path.stat().st_size)
            lines.append(
                f"- {relative_path} | lines: {line_count} | size: {file_size}"
            )

        content = "\n".join(lines)
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )


class ReadMaterialTool(_MaterialsToolBase):
    def __init__(self, project_root: str = ".", search_dirs: Optional[List[str]] = None):
        # Default search roots include both materials and memory.
        super().__init__(project_root=project_root, search_dirs=search_dirs or ["materials", "memory"])

    @property
    def name(self) -> str:
        return "read_material"

    @property
    def description(self) -> str:
        return (
            "Read text content from configured roots (default ./materials and ./memory) by line range or keywords. "
            "Use this when you need to inspect source material before planning."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path inside configured roots, optionally prefixed with materials/ or memory/.",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional starting line number for direct line reading.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional ending line number for direct line reading.",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of keywords used to find relevant paragraphs.",
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
        keywords: Optional[List[str]] = None,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs
    ) -> Any:
        if start_line is None and end_line is None and not keywords:
            return "Please provide a line range or at least one keyword."

        resolved_path, error = self._resolve_material_path(file_path)
        if error:
            return error

        text, read_error = self._read_text_file(resolved_path)
        if read_error:
            return read_error

        sections = []
        lines = text.splitlines()

        if start_line is not None or end_line is not None:
            start = start_line or 1
            end = end_line or start
            if start < 1 or end < start:
                return "Invalid line range. start_line must be >= 1 and end_line must be >= start_line."

            selected_lines = lines[start - 1:end]
            if not selected_lines:
                sections.append("Line range result:\nNo content found in the requested line range.")
            else:
                numbered_lines = [
                    f"{index}: {content}"
                    for index, content in enumerate(selected_lines, start=start)
                ]
                sections.append("Line range result:\n" + "\n".join(numbered_lines))

        if keywords:
            normalized_keywords = [keyword.casefold() for keyword in keywords if keyword.strip()]
            paragraphs = self._split_paragraphs(text)
            matched_paragraphs = []

            for index, paragraph in enumerate(paragraphs, start=1):
                normalized_paragraph = paragraph.casefold()
                matches = [
                    keyword for keyword in normalized_keywords if keyword in normalized_paragraph
                ]
                if matches:
                    matched_paragraphs.append(
                        f"[Paragraph {index}] matched: {', '.join(matches)}\n{paragraph}"
                    )

            if matched_paragraphs:
                sections.append("Keyword result:\n" + "\n\n".join(matched_paragraphs))
            else:
                sections.append(
                    "Keyword result:\nNo paragraphs matched the provided keywords."
                )

        content = f"File: {file_path}\n\n" + "\n\n".join(sections)
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )


class SummarizeMaterialTool(_MaterialsToolBase):
    @property
    def name(self) -> str:
        return "summarize_material"

    @property
    def description(self) -> str:
        return (
            "Summarize a text file inside ./materials with a Gemini model and extract keywords for each paragraph. "
            "Use this after identifying a relevant material file."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative file path inside ./materials.",
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
        **kwargs
    ) -> Any:
        resolved_path, error = self._resolve_material_path(file_path)
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

        overall_keywords = self._extract_keywords(text, limit=8)
        condensed_summary = self._compress_with_gemini(file_path, text)
        if not condensed_summary:
            condensed_summary = self._summarize_paragraph(
                " ".join(paragraphs[:3]),
                max_length=self.max_condensed_summary_chars,
            )
        summary_lines = [
            f"File: {file_path}",
            "Overall summary:",
            condensed_summary,
            "",
            "Overall keywords: " + (", ".join(overall_keywords) or "none"),
            "",
            "Paragraph summaries:",
        ]

        for index, paragraph in enumerate(paragraphs, start=1):
            paragraph_summary = self._summarize_paragraph(paragraph)
            paragraph_keywords = self._extract_keywords(paragraph, limit=5)
            summary_lines.append(
                f"{index}. Summary: {paragraph_summary}"
            )
            summary_lines.append(
                "   Keywords: " + (", ".join(paragraph_keywords) or "none")
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
