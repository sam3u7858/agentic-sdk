import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

# --- Protocol Definition ---

class IChatHistoryBackend(Protocol):
    """
    Defines the interface that all chat history storage backends must implement.
    """
    def conversation_exists(self, conversation_id: str) -> bool:
        pass
        
    def create_conversation(self, conversation_id: str) -> None:
        pass

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        pass

    def add_message(self, conversation_id: str, message: Dict[str, Any]) -> None:
        pass

    def replace_messages(self, conversation_id: str, messages: List[Dict[str, Any]]) -> None:
        pass

    def list_conversations(self, skip: Optional[int] = None) -> List[str]:
        pass



class ChatHistoryProvider(Protocol):
    def __init__(self):
        self.backend: Optional[IChatHistoryBackend] = None
       

class LocalChatHistory:
    def __init__(self, storage_directory: str, memory_config: Optional[Dict[str, Any]] = None):
        self.storage_directory = Path(storage_directory)
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self.memory_config = {
            "enabled": True,
            "retain_recent_messages": 40,
            "archive_directory": ".archive",
            "max_entity_count": 8,
            "enable_vector_placeholder": True,
        }
        if memory_config:
            self.memory_config.update(memory_config)
        self.archive_directory = self.storage_directory / str(self.memory_config["archive_directory"])
        self.archive_directory.mkdir(parents=True, exist_ok=True)

    def _get_path(self, conversation_id: str) -> Path:
        return self.storage_directory / f"{conversation_id}.json"

    def conversation_exists(self, conversation_id: str) -> bool:
        return self._get_path(conversation_id).exists()

    def create_conversation(self, conversation_id: str) -> None:
        if (not self.conversation_exists(conversation_id)):
            data = {"conversation_id": conversation_id, "messages": [], "created_at": datetime.now().isoformat()}
            self._save_to_file(conversation_id, data)

    def add_message(self, conversation_id: str, message: Dict[str, Any]) -> None:
        self.create_conversation(conversation_id)
        data = self.get_conversation(conversation_id)
        if data is None:
            raise OSError(f"Conversation '{conversation_id}' could not be loaded after creation.")

        message_with_timestamp = dict(message)
        message_with_timestamp["timestamp"] = datetime.now().isoformat()
        data["messages"].append(message_with_timestamp)
        if self.memory_config.get("enabled", True):
            self._compress_and_archive(conversation_id, data)
        self._save_to_file(conversation_id, data)

    def replace_messages(self, conversation_id: str, messages: List[Dict[str, Any]]) -> None:
        self.create_conversation(conversation_id)
        data = self.get_conversation(conversation_id)
        if data is None:
            raise OSError(f"Conversation '{conversation_id}' could not be loaded after creation.")
        data["messages"] = list(messages)
        if self.memory_config.get("enabled", True):
            self._compress_and_archive(conversation_id, data)
        self._save_to_file(conversation_id, data)


    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_path(conversation_id)
        if (not path.exists()):  return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise OSError(
                f"Failed to load conversation '{conversation_id}' from '{path}'. "
                f"Reason: {e}"
            ) from e

    def list_conversations(self, skip: Optional[int] = None) -> List[str]:
        conversation_files = sorted(
            self.storage_directory.glob("*.json"),
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )

        if skip is None:
            return [file_path.stem for file_path in conversation_files[:10]]

        return [file_path.stem for file_path in conversation_files[skip:]]


    def _save_to_file(self, conversation_id: str, conversation: Dict[str, Any]) -> None:
        path = self._get_path(conversation_id)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(conversation, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise OSError(
                f"Failed to save conversation '{conversation_id}' to '{path}'. "
                f"Reason: {e}"
            ) from e

    def _archive_path(self, conversation_id: str) -> Path:
        return self.archive_directory / f"{conversation_id}.json"

    def _load_archive(self, conversation_id: str) -> Dict[str, Any]:
        archive_path = self._archive_path(conversation_id)
        if not archive_path.exists():
            return {
                "conversation_id": conversation_id,
                "created_at": datetime.now().isoformat(),
                "entries": [],
            }
        try:
            with archive_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise OSError(
                f"Failed to load archive '{conversation_id}' from '{archive_path}'. "
                f"Reason: {e}"
            ) from e

    def _save_archive(self, conversation_id: str, archive_data: Dict[str, Any]) -> None:
        archive_path = self._archive_path(conversation_id)
        try:
            with archive_path.open("w", encoding="utf-8") as f:
                json.dump(archive_data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise OSError(
                f"Failed to save archive '{conversation_id}' to '{archive_path}'. "
                f"Reason: {e}"
            ) from e

    def _compress_and_archive(self, conversation_id: str, conversation_data: Dict[str, Any]) -> None:
        messages = conversation_data.get("messages", [])
        retain_recent = int(self.memory_config.get("retain_recent_messages", 40))
        if len(messages) <= retain_recent:
            return

        cutoff = len(messages) - retain_recent
        archive_data = self._load_archive(conversation_id)
        compressed_count = 0

        # 第一則使用者訊息是任務本身（題目、要求），封存掉模型就不知道自己在做什麼
        first_user = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)

        for idx in range(cutoff):
            message = messages[idx]
            if message.get("archive_ref") or idx == first_user:
                continue

            archive_ref = f"arc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{idx}"
            archive_bundle = self._build_archive_bundle(archive_ref, message)
            archive_data["entries"].append(archive_bundle)
            messages[idx] = self._build_compacted_message(message, archive_ref, archive_bundle)
            compressed_count += 1

        if compressed_count:
            archive_data["updated_at"] = datetime.now().isoformat()
            conversation_data["memory_compression"] = {
                "last_updated_at": datetime.now().isoformat(),
                "compressed_messages_total": int(
                    conversation_data.get("memory_compression", {}).get(
                        "compressed_messages_total", 0
                    )
                )
                + compressed_count,
            }
            self._save_archive(conversation_id, archive_data)

    def _build_archive_bundle(self, archive_ref: str, message: Dict[str, Any]) -> Dict[str, Any]:
        message_copy = copy.deepcopy(message)
        role = str(message_copy.get("role", "unknown"))
        name = str(message_copy.get("name", ""))
        content = str(message_copy.get("content", ""))

        level0 = {"raw_message": message_copy}
        level1 = {
            "narrative_summary": (
                f"Agent message archived. role={role}"
                + (f", tool={name}" if name else "")
                + f", content_preview={content[:160]}"
            )
        }
        level2 = {
            "entities": self._extract_entities(content),
            "relations": self._extract_relations(role, name, content),
        }
        level3 = {
            "vector_placeholder": {
                "backend": "not-configured",
                "status": "placeholder",
                "query_text": content[:400],
                "archive_ref": archive_ref,
            }
        }

        if not self.memory_config.get("enable_vector_placeholder", True):
            level3 = {"vector_placeholder": {"status": "disabled"}}

        return {
            "archive_ref": archive_ref,
            "timestamp": datetime.now().isoformat(),
            "level0": level0,
            "level1": level1,
            "level2": level2,
            "level3": level3,
        }

    def _build_compacted_message(
        self, original_message: Dict[str, Any], archive_ref: str, archive_bundle: Dict[str, Any]
    ) -> Dict[str, Any]:
        compacted = dict(original_message)
        compacted["compression_level"] = 2
        compacted["summary"] = archive_bundle["level1"]["narrative_summary"]
        compacted["archive_ref"] = archive_ref
        compacted["compressed_from"] = "raw_message"

        role = str(compacted.get("role", "unknown"))
        if role == "tool":
            compacted["content"] = "[ARCHIVED_TOOL_RESULT]"
        else:
            compacted["content"] = "[ARCHIVED_MESSAGE]"
        return compacted

    def _extract_entities(self, text: str) -> List[str]:
        english_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text)
        chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        tokens = english_tokens + chinese_tokens
        seen = set()
        entities: List[str] = []
        max_entity_count = int(self.memory_config.get("max_entity_count", 8))
        for token in tokens:
            normalized = token.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            entities.append(token)
            if len(entities) >= max_entity_count:
                break
        return entities

    def _extract_relations(self, role: str, name: str, content: str) -> List[Dict[str, str]]:
        relations = [{"source": role, "relation": "produced", "target": "message"}]
        if name:
            relations.append({"source": role, "relation": "invoked", "target": name})
        if content.startswith("Error:"):
            relations.append({"source": role, "relation": "status", "target": "error"})
        else:
            relations.append({"source": role, "relation": "status", "target": "success"})
        return relations

class MongoDBChatHistory:
    def __init__(self):
        pass 

    def replace_messages(self, conversation_id: str, messages: List[Dict[str, Any]]) -> None:
        # Placeholder for future MongoDB implementation.
        pass

    # TODO: in the future, we will implement the MongoDBChatHistory class