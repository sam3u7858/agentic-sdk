from pathlib import Path
from string import Template
from typing import Optional, Dict, Any

class PromptManager:
    def __init__(self, prompt_directory: str):
        self.prompt_directory = Path(prompt_directory)
        self.prompt_directory.mkdir(parents=True, exist_ok=True)

    def load_prompt(self, template_name: str, **kwargs: Any) -> str:
        """
        Load a Markdown file as a prompt template.
        Example: load_prompt("system_prompt.md", agent_name="Gemini")
        """
        file_path = self.prompt_directory / f"{template_name}.md"
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt template '{template_name}' not found.")
        
        content = file_path.read_text(encoding="utf-8")
        template = Template(content)
        return template.safe_substitute(**kwargs)

    