# src/tools/workspace_scout.py
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
from src.ai_core.tool_executor import BaseTool

class ScanWorkspaceTool(BaseTool):
    """
    Tool to scan the workspace.
    After inheriting BaseTool, it will automatically convert name, description, parameters to LLM Schema.
    """
    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir).resolve()
        self.ignore_dirs: Set[str] = {".git", "__pycache__", "venv", ".venv", "node_modules", ".pytest_cache", "chat_history"}
        self.ignore_exts: Set[str] = {".pyc", ".png", ".jpg", ".exe", ".dll", ".so"}

    @property
    def name(self) -> str:
        return "scan_workspace"

    @property
    def description(self) -> str:
        return "Scan the current project directory, return the tree structure of folders and files. Use when you need to know what files are in the project."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_depth": {
                    "type": "integer",
                    "description": "The depth of the scanned directory, default is 3"
                },
                "save_policy": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "description": "inline: put content in history. file: save content to file and keep history slim."
                },
                "output_target": {
                    "type": "string",
                    "enum": ["memory", "materials"],
                    "description": "When save_policy=file, target folder to store output."
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional relative output file path within target folder."
                }
            }
        }

    def execute(
        self,
        max_depth: int = 3,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Execution logic: generate tree string"""
        tree_lines = []
        self._generate_tree(self.root_dir, "", tree_lines, 0, max_depth)
        
        if not tree_lines:
            content = "The workspace is empty or only contains ignored files."
        else:
            content = "\n".join(tree_lines)
        if save_policy != "file":
            return content
        return {
            "content": content,
            "history_mode": "file",
            "output_target": output_target if output_target in {"memory", "materials"} else "memory",
            "output_path": output_path,
        }

    def _generate_tree(self, current_path: Path, prefix: str, tree_lines: List[str], current_depth: int, max_depth: int):
        if current_depth > max_depth:
            return

        try:
            items = sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return

        valid_items = []
        for item in items:
            if item.name in self.ignore_dirs or (item.is_file() and item.suffix in self.ignore_exts):
                continue
            valid_items.append(item)

        for index, item in enumerate(valid_items):
            is_last = (index == len(valid_items) - 1)
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{item.name}")
            
            if item.is_dir():
                extension = "    " if is_last else "│   "
                self._generate_tree(item, prefix + extension, tree_lines, current_depth + 1, max_depth)