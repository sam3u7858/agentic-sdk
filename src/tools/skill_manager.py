import re
from typing import Any, Dict, List, Optional

from src.ai_core.skill_registry import SkillRegistry
from src.ai_core.tool_executor import BaseTool


class LookupSkillTool(BaseTool):
    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        skill_registry: Optional[SkillRegistry] = None,
    ):
        self.registry = registry or skill_registry
        if self.registry is None:
            raise ValueError("LookupSkillTool requires a SkillRegistry instance.")

    @property
    def name(self) -> str:
        return "lookup_skill"

    @property
    def description(self) -> str:
        return (
            "當你需要專業領域的 SOP 或特定輸出格式（例如 video_planner）時，請使用此工具檢索詳細指令。"
            "【極度重要警告】：技能 (Skills) 只是文字說明書，不是可以直接執行的工具！"
            "你絕對不能直接呼叫技能名稱（如呼叫 video_planner 工具）。你必須先用 lookup_skill 讀取它的 SOP，然後『由你自己』在思考後產出結果。\n"
            "Use this tool when you need a domain-specific SOP or a required output format "
            "(for example, video_planner). "
            "CRITICAL WARNING: Skills are instruction documents, not executable tools. "
            "Never call a skill name directly as if it were a tool. "
            "You must first use lookup_skill to read the SOP, then produce the result yourself."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The keyword or phrase used to search for a skill.",
                }
            },
            "required": ["query"],
        }

    def execute(self, query: str, **kwargs) -> str:
        normalized_query = self._normalize_text(query)
        query_tokens = self._tokenize(query)

        for skill in self.registry.skills.values():
            if self._matches(skill.name, skill.description, normalized_query, query_tokens):
                return f"Skill: {skill.name}\n\n{skill.instructions}"

        return (
            "Skill not found. Available skills are: "
            f"{self.registry.get_skill_summaries()}"
        )

    def _matches(
        self,
        skill_name: str,
        skill_description: str,
        normalized_query: str,
        query_tokens: List[str],
    ) -> bool:
        normalized_name = self._normalize_text(skill_name)
        normalized_description = self._normalize_text(skill_description)

        if normalized_query and (
            normalized_query in normalized_name
            or normalized_query in normalized_description
        ):
            return True

        return any(
            token in normalized_name or token in normalized_description
            for token in query_tokens
        )

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[\W_]+", "", value.casefold())

    def _tokenize(self, value: str) -> List[str]:
        return [
            token
            for token in re.split(r"[\W_]+", value.casefold())
            if token
        ]
