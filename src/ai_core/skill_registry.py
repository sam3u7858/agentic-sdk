import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class Skill:
    name: str
    description: str # For LLM
    instructions: str # For LLM, detailed instructions for the skill
    required_tools: List[str] = field(default_factory=list)

class SkillRegistry:
    def __init__(self, skill_directory: str = "skills"):
        self.skill_directory = Path(skill_directory)
        self.skill_directory.mkdir(parents=True, exist_ok=True)
        self.skills: Dict[str, Skill] = {}
        self.load_skills()

    def load_skills(self) -> None:
        """Load skills from the skill directory."""
        self.skills = {}

        for skill_folder in sorted(self.skill_directory.iterdir(), key=lambda path: path.name):
            if not skill_folder.is_dir():
                continue

            meta_path = skill_folder / "meta.json"
            instr_path = skill_folder / "instructions.md"

            if not meta_path.exists() or not instr_path.exists():
                logger.warning(
                    "Skipping skill folder '%s' because meta.json or instructions.md is missing.",
                    skill_folder,
                )
                continue

            with meta_path.open("r", encoding="utf-8") as file_handle:
                meta_data = json.load(file_handle)

            skill = Skill(
                name=meta_data.get("name", skill_folder.name),
                description=meta_data.get(
                    "description",
                    "There is no description for this skill.",
                ),
                instructions=instr_path.read_text(encoding="utf-8"),
                required_tools=meta_data.get("required_tools", []),
            )
            self.skills[skill.name] = skill

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        return self.skills.get(skill_name)

    def get_skill_summaries(self) -> str:
        """Get a formatted string of all skill summaries."""
        summaries = [
            f"- {skill.name}: {skill.description}"
            for skill in sorted(self.skills.values(), key=lambda item: item.name)
        ]
        return "\n".join(summaries)