import sys
from pathlib import Path

from src.agent_factory import (
    build_demo_prompt,
    configure_logging,
    create_agent_components,
)

# Ensure Python can import from the project root.
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

def main():
    configure_logging()
    components = create_agent_components("agent_skill_test_01")
    tool_executor = components["tool_executor"]
    runtime = components["runtime"]

    print("=== Agent 已裝載的工具清單 ===")
    for schema in tool_executor.schemas:
        print(f"- {schema['name']}: {schema['description']}")
    print("==============================\n")

    user_prompt = build_demo_prompt()

    print(f"💬 使用者: {user_prompt}")
    final_answer = runtime.run(user_prompt)

    print("\n" + "=" * 50)
    print("🤖 Agent 最終回答：")
    print("=" * 50)
    print(final_answer)


if __name__ == "__main__":
    main()
