# units_tsts/agent_test.py
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 確保 Python 能找到 src 目錄
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper
from src.ai_core.session import ChatSession
from src.ai_core.tool_executor import ToolExecutor
from src.ai_core.runtime import AgentRuntime
from src.tools.workspace_scout import ScanWorkspaceTool

def run_test():
    load_dotenv()

    # 1. 準備工具箱
    tool_executor = ToolExecutor()
    tool_executor.register_tools([
        ScanWorkspaceTool(root_dir=str(project_root)) # 注入專案根目錄
    ])

    print("=== 工具 Schema 檢查 ===")
    print(tool_executor.schemas)
    print("========================\n")

    # 2. 初始化大腦 (LMWrapper)
    ai = LMWrapper(
        provider="gemini", # 或 openai
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        api_key=os.getenv("GEMINI_KEY")
    )
    ai.set_system_prompt(
        "你是一個資深的軟體工程 Agent。你的任務是幫助使用者解決問題。"
        "遇到需要了解專案結構時，請主動呼叫 `scan_workspace` 工具。回答時請保持專業且簡潔。"
    )

    # 3. 初始化記憶與 Session
    history = LocalChatHistory(storage_directory="chat_history")
    conversation_id = "test_agent_runtime_01"
    
    # 每次測試前可以選擇清空舊的記憶 (若有實作的話)，這裡直接覆寫或接續
    history.create_conversation(conversation_id)
    session = ChatSession(llm=ai, history_backend=history, conversation_id=conversation_id)

    # 4. 啟動 Agent Runtime
    runtime = AgentRuntime(session, tool_executor)

    # 5. 執行任務 (Closed-Loop)
    user_prompt = "嗨，請幫我掃描一下目前專案底下的結構（深度用3就好），並簡單告訴我 src 資料夾底下大概有哪些模組？"
    
    final_answer = runtime.run(user_prompt)
    
    print("\n" + "="*50)
    print("🤖 最終回答：")
    print("="*50)
    print(final_answer)

if __name__ == "__main__":
    run_test()