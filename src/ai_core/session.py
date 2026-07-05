from src.ai_core.llm import LMWrapper
from src.ai_core.history import LocalChatHistory, IChatHistoryBackend
from typing import Optional


class ChatSession:
    def __init__(self, llm: LMWrapper, history_backend: IChatHistoryBackend, conversation_id: str):
        self.llm = llm
        self.history_backend = history_backend
        self.conversation_id = conversation_id

        self.history_backend.create_conversation(conversation_id)
    
    def ask(self, question: str) -> str:
        # 1. add user message to history
        self.history_backend.add_message(self.conversation_id, {"role": "user", "content": question})
        # 2. get conversation from history
        conversation = self.history_backend.get_conversation(self.conversation_id)['messages']
        # 3. get response from LMWrapper
        response = self.llm.get_completion(conversation)
        # 4. add assistant message to history
        self.history_backend.add_message(self.conversation_id, {"role": "assistant", "content": response})
        return response
