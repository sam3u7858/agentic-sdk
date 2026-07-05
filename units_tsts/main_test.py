from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper
from src.ai_core.session import ChatSession
import os
from dotenv import load_dotenv

load_dotenv()

# from src.ai_core.tool import ToolExecutor

def run_test():
    # 1. Initialize history
    history = LocalChatHistory(storage_directory="chat_history")
    history.create_conversation("user_001")

    # 2. Initialize model client
    provider = "gemini"
    api_key = os.getenv("GEMINI_KEY") if provider == "gemini" else os.getenv(
        "OPENAI_API_KEY")
    model = os.getenv(
        "GEMINI_MODEL", "gemini-3-flash-preview") if provider == "gemini" else os.getenv("OPENAI_MODEL", "gpt-oss-20b")
    lm_api_url = None if provider == "gemini" else os.getenv(
        "LM_API_URL", "http://localhost:1234/v1/")
    request_options = {
        "temperature": 0.7,
        "max_tokens": 30000,
        "stream": False,
    }
    ai = LMWrapper(
        provider=provider,
        model=model,
        api_key=api_key,
        lm_api_url=lm_api_url,
        request_options=request_options,
    )

    # 3. Read user input and start session
    user_input = input("You: ").strip()
    session = ChatSession(
        llm=ai, history_backend=history, conversation_id="user_001")

    # 4. Run 3 chat turns
    for _ in range(3):
        response = session.ask(user_input)
        print(f"Assistant: {response}")
        user_input = input("You: ").strip()


if __name__ == "__main__":
    run_test()
