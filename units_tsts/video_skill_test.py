from src.ai_core.prompt_manager import PromptManager
from src.ai_core.skill_registry import SkillRegistry


def run():
    # 1. 初始化資源
    prompt_mgr = PromptManager("prompts")
    skill_reg = SkillRegistry("skills")

    # 2. 取得所有可用技能的摘要
    skills_summary = skill_reg.get_skill_summaries()

    # 3. 組裝出最終要餵給 Agent 的 System Prompt
    system_prompt = prompt_mgr.load_prompt(
        "system_core",
        agent_name="Codex-Alpha",
        available_skills=skills_summary
    )

    print("=== 最終生成的 System Prompt ===")
    print(system_prompt)
