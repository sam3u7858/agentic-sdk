import base64
import copy
import json
import os
import uuid
import openai
import requests
import logging
from typing import Protocol, List, Dict, Optional, Sequence, TypedDict, Literal, Any

logger = logging.getLogger(__name__)


def resolve_default_llm_api_key(provider: str, api_key: Optional[str]) -> Optional[str]:
    """Use explicit api_key when provided; else read env for supported providers."""
    if api_key is not None:
        return api_key
    p = provider.lower()
    if p == "gemini":
        return os.getenv("GEMINI_KEY")
    if p in ("openai", "local", "grok"):
        return os.getenv("OPENAI_API_KEY")
    return None


class LMWrapperError(RuntimeError):
    pass


class LMWrapperNotInitializedError(LMWrapperError):
    pass


class LMMessageValidationError(LMWrapperError):
    pass


class LMBackendError(LMWrapperError):
    pass


Role = Literal["user", "assistant", "system", "tool", "function"]


class ChatMessage(TypedDict):
    role: Role
    content: str
    tool_call_id: Optional[str]
    name: Optional[str]
    tool_calls: Optional[List[Dict[str, Any]]]
    gemini_content: Optional[Dict[str, Any]]


class ToolAdapter:
    @staticmethod
    def _normalize_schema_for_gemini(node: Any) -> Any:
        if isinstance(node, dict):
            normalized: Dict[str, Any] = {}
            for key, value in node.items():
                if key == "type" and isinstance(value, list):
                    preferred = [item for item in value if isinstance(item, str) and item != "null"]
                    normalized[key] = preferred[0] if preferred else "string"
                else:
                    normalized[key] = ToolAdapter._normalize_schema_for_gemini(value)
            return normalized
        if isinstance(node, list):
            return [ToolAdapter._normalize_schema_for_gemini(item) for item in node]
        return node

    @staticmethod
    def to_openai_tool(tool: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            },
        }

    @staticmethod
    def to_gemini_tool(tool: dict) -> dict:
        parameters = copy.deepcopy(tool.get("parameters") or {})
        if not parameters:
            parameters = {"type": "object", "properties": {}, "required": []}
        else:
            parameters.setdefault("type", "object")
            parameters.setdefault("properties", {})
            parameters.setdefault("required", [])
            parameters = ToolAdapter._normalize_schema_for_gemini(parameters)

        return {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": parameters,
        }


def _validate_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(messages, (list, tuple)):
        raise LMMessageValidationError("messages must be a list/tuple")
    return list(messages)


def _normalize_openai_tool_messages(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI Chat Completions require role=tool messages to include tool_call_id."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") != "tool":
            out.append(m)
            continue
        tid = m.get("tool_call_id")
        if tid is not None and str(tid).strip() != "":
            out.append(m)
            continue
        name = m.get("name") or "unknown"
        content = m.get("content", "")
        out.append(
            {
                "role": "user",
                "content": f"[tool:{name} missing tool_call_id]\n{content}",
            }
        )
    return out


def gemini_to_openai_like(response_json) -> Dict[str, Any]:
    try:
        if "candidates" not in response_json:
            raise RuntimeError(
                f"No 'candidates' in Gemini response: {response_json}")

        candidate = response_json["candidates"][0]
        content = candidate["content"]
        parts = content.get("parts", [])

        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                call_id = fc.get("id", f"call_{uuid.uuid4().hex[:8]}")
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    }
                )

        result = {
            "role": "assistant",
            "content": "".join(text_parts).strip(),
            "gemini_content": content,
        }
        grounding_metadata = candidate.get("groundingMetadata")
        if grounding_metadata:
            result["grounding_metadata"] = grounding_metadata
        if tool_calls:
            result["tool_calls"] = tool_calls

        return result
    except Exception as e:
        logger.debug("Error parsing Gemini response: %s", response_json)
        raise RuntimeError(f"Invalid Gemini response structure: {e}") from e


class IChatBackend(Protocol):
    def chat(
        self,
        messages: Sequence[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        pass


class OpenAIWrapper:
    def __init__(self, api_key: str, base_url: str, model: str, request_options: Dict):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.request_options = request_options

    def analyze_image_bytes(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Single-turn vision call (Chat Completions)."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": str(prompt)},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        msgs: List[Dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": content})
        kwargs = self.request_options.copy()
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                **kwargs,
            )
            return (completion.choices[0].message.content or "").strip()
        except Exception as e:
            logger.exception("OpenAI vision call failed")
            raise LMBackendError(f"Vision model call failed: {e}") from e

    def chat(
        self,
        messages: Sequence[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(_normalize_openai_tool_messages(messages))

        kwargs = self.request_options.copy()
        if tools:
            kwargs["tools"] = [ToolAdapter.to_openai_tool(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                **kwargs,
            )
            msg = completion.choices[0].message

            result = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            return result
        except Exception as e:
            logger.exception("OpenAI API call failed")
            raise LMBackendError(f"Model call failed: {e}") from e


class GeminiWrapper:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        request_options: Dict = None,
    ):
        self.api_key = api_key
        self.model = model
        self.request_options = request_options or {}

    def analyze_image_bytes(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """One-shot Gemini call with inline image + text."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        parts: List[Dict[str, Any]] = [
            {"text": str(prompt)},
            {"inlineData": {"mimeType": mime_type, "data": b64}},
        ]
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": self.request_options.get("temperature", 0.4),
                "maxOutputTokens": self.request_options.get("max_tokens", 4096),
            },
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            resp = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=self.request_options.get("timeout", 60),
            )
            if not resp.ok:
                logger.error("Gemini vision request failed: %s", resp.text[:2000])
            resp.raise_for_status()
            parsed = gemini_to_openai_like(resp.json())
            return str(parsed.get("content", "") or "").strip()
        except requests.HTTPError as e:
            logger.exception("Gemini vision call failed")
            raise LMBackendError(f"Vision model call failed: {e}") from e
        except Exception as e:
            logger.exception("Gemini vision call failed")
            raise LMBackendError(f"Vision model call failed: {e}") from e

    def chat(
        self,
        messages: Sequence[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        contents = []
        pending_function_calls: Dict[str, str] = {}
        for m in messages:
            if m["role"] == "user":
                contents.append({"role": "user", "parts": [
                                {"text": str(m.get("content", ""))}]})
            elif m["role"] == "assistant":
                gemini_content = m.get("gemini_content")
                if isinstance(gemini_content, dict) and gemini_content.get("parts"):
                    contents.append(gemini_content)
                    continue

                if m.get("tool_calls"):
                    parts = []
                    if m.get("content"):
                        parts.append({"text": m["content"]})
                    for tc in m["tool_calls"]:
                        call_id = tc.get("id", "")
                        call_name = tc.get("function", {}).get("name", "")
                        if call_id and call_name:
                            pending_function_calls[call_id] = call_name
                        parts.append(
                            {
                                "functionCall": {
                                    "id": call_id,
                                    "name": call_name,
                                    "args": json.loads(tc["function"]["arguments"]),
                                }
                            }
                        )
                    contents.append({"role": "model", "parts": parts})
                else:
                    contents.append({"role": "model", "parts": [
                                    {"text": str(m.get("content", ""))}]})
            elif m["role"] == "tool" or m["role"] == "function":
                response_data: Any = m.get("content")
                try:
                    if isinstance(response_data, str):
                        response_data = json.loads(response_data)
                except Exception:
                    pass

                if not isinstance(response_data, dict):
                    response_data = {"result": response_data}

                tool_call_id = m.get("tool_call_id", "")
                tool_name = m.get("name", "")
                expected_name = pending_function_calls.get(tool_call_id)
                can_emit_function_response = bool(
                    tool_call_id and tool_name and expected_name and expected_name == tool_name
                )

                if not can_emit_function_response:
                    # If historical tool messages are compressed/reordered, Gemini may reject
                    # functionResponse turns that are not immediately after functionCall turns.
                    # Fallback to plain user text to preserve context without breaking protocol.
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": f"[tool:{tool_name or 'unknown'}]\n{str(m.get('content', ''))}"
                                }
                            ],
                        }
                    )
                    continue

                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "id": tool_call_id,
                                    "name": tool_name,
                                    "response": response_data,
                                }
                            }
                        ],
                    }
                )
                pending_function_calls.pop(tool_call_id, None)

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.request_options.get("temperature", 0.7),
                "maxOutputTokens": self.request_options.get("max_tokens", 8192),
            },
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]}

        payload_tools = []
        if tools:
            gemini_tools = [ToolAdapter.to_gemini_tool(t) for t in tools]
            payload_tools.append({"functionDeclarations": gemini_tools})

        if self.request_options.get("enable_google_search_grounding", False):
            google_search_tool: Dict[str, Any] = {"google_search": {}}
            exclude_domains = self.request_options.get(
                "google_search_exclude_domains")
            if isinstance(exclude_domains, list) and exclude_domains:
                google_search_tool["google_search"]["exclude_domains"] = [
                    str(domain).strip()
                    for domain in exclude_domains
                    if str(domain).strip()
                ]
            payload_tools.append(google_search_tool)

        if payload_tools:
            payload["tools"] = payload_tools

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        try:
            resp = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=self.request_options.get("timeout", 30),
            )
            if not resp.ok:
                response_body = resp.text
                try:
                    response_body = json.dumps(resp.json(), ensure_ascii=False)
                except ValueError:
                    pass

                logger.error(
                    "Gemini API request failed with status %s. Response body: %s",
                    resp.status_code,
                    response_body,
                )
            resp.raise_for_status()
            return gemini_to_openai_like(resp.json())
        except requests.HTTPError as e:
            response_body = ""
            if e.response is not None:
                try:
                    response_body = json.dumps(
                        e.response.json(), ensure_ascii=False)
                except ValueError:
                    response_body = e.response.text

            logger.exception("Gemini API call failed")
            raise LMBackendError(
                f"Model call failed: {e}. Response body: {response_body}"
            ) from e
        except Exception as e:
            logger.exception("Gemini API call failed")
            raise LMBackendError(f"Model call failed: {e}") from e


class LMWrapper:
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        lm_api_url: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
    ):
        self.backend: Optional[IChatBackend] = None
        self.system_prompt: Optional[str] = None
        self._initialize_backend(
            provider=provider,
            model=model,
            api_key=api_key,
            lm_api_url=lm_api_url,
            request_options=request_options,
        )

    def _initialize_backend(
        self,
        *,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        lm_api_url: Optional[str] = None,
        request_options: Optional[Dict[str, Any]] = None,
    ):
        if provider.lower() in ["local", "openai", "grok"]:
            self.backend = OpenAIWrapper(
                api_key=api_key or "",
                base_url=lm_api_url,
                model=model,
                request_options=request_options or {},
            )
        elif provider.lower() == "gemini":
            self.backend = GeminiWrapper(
                api_key=api_key or "",
                model=model,
                request_options=request_options or {},
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    def set_system_prompt(self, system_prompt: str):
        self.system_prompt = system_prompt

    def get_completion(
        self,
        messages: Sequence[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not self.backend:
            raise LMWrapperNotInitializedError("Backend not initialized.")
        validated_messages = _validate_messages(messages)
        return self.backend.chat(validated_messages, system_prompt=self.system_prompt, tools=tools)

    def analyze_image_bytes(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Single-turn image analysis using the configured backend (Gemini or OpenAI-compatible vision)."""
        if not self.backend:
            raise LMWrapperNotInitializedError("Backend not initialized.")
        sys_p = system_prompt if system_prompt is not None else self.system_prompt
        if hasattr(self.backend, "analyze_image_bytes"):
            return self.backend.analyze_image_bytes(
                prompt=prompt,
                image_bytes=image_bytes,
                mime_type=mime_type,
                system_prompt=sys_p,
            )
        raise LMBackendError("Current backend does not support analyze_image_bytes.")
