from pathlib import Path
from typing import List, Set

class WorkspaceScout:
    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir).resolve()
        # Ignore directories and files that are not needed to be scanned
        self.ignore_dirs: Set[str] = {".git", "__pycache__", "venv", ".venv", "node_modules", ".pytest_cache", "chat_history"}
        self.ignore_exts: Set[str] = {".pyc", ".png", ".jpg", ".exe", ".dll", ".so"}

    def get_file_tree(self, max_depth: int = 3) -> str:
        """Scan the workspace and generate a tree structure string"""
        tree_lines = []
        self._generate_tree(self.root_dir, "", tree_lines, 0, max_depth)
        return "\n".join(tree_lines)

    def _generate_tree(self, current_path: Path, prefix: str, tree_lines: List[str], current_depth: int, max_depth: int):
        if current_depth > max_depth:
            return

        # Get all items in the directory and sort them (folders first, files last)
        try:
            items = sorted(current_path.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return

        # Filter out ignored items
        valid_items = []
        for item in items:
            if item.name in self.ignore_dirs:
                continue
            if item.is_file() and item.suffix in self.ignore_exts:
                continue
            valid_items.append(item)

        for index, item in enumerate(valid_items):
            is_last = (index == len(valid_items) - 1)
            connector = "└── " if is_last else "├── "
            
            tree_lines.append(f"{prefix}{connector}{item.name}")
            
            if item.is_dir():
                extension = "    " if is_last else "│   "
                self._generate_tree(item, prefix + extension, tree_lines, current_depth + 1, max_depth)

# # Test code : Usage example
# if __name__ == "__main__":
#     scout = WorkspaceScout()
#     print("=== Current workspace structure ===")
#     print(scout.get_file_tree())