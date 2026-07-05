import json as jsonlib
from typing import Any, Dict, Optional

import requests

from src.ai_core.tool_executor import BaseTool
from src.tools.network_safety import (
    is_textual_content_type,
    sanitize_request_headers,
    validate_outbound_url,
)


class HttpRequestTool(BaseTool):
    def __init__(self, timeout: int = 20, max_body_chars: int = 120000):
        self.timeout = timeout
        self.max_body_chars = max_body_chars
        self.default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Send a safe outbound HTTP request and return status_code/content_type/body. "
            "Supports GET/POST/PUT/PATCH/DELETE with params/data/json/headers."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "method": {"type": "string"},
                "url": {"type": "string"},
                "params": {"type": "object"},
                "data": {
                    "type": "string",
                    "description": "Optional raw request body string (for form/text payloads).",
                },
                "json": {
                    "type": "string",
                    "description": "Optional JSON payload as a JSON-encoded string.",
                },
                "headers": {"type": "object"},
                "timeout_seconds": {"type": "integer"},
                "save_policy": {
                    "type": "string",
                    "enum": ["inline", "file"],
                    "description": "inline: put content in history. file: save content to file and keep history slim.",
                },
                "output_target": {
                    "type": "string",
                    "enum": ["memory", "materials"],
                    "description": "When save_policy=file, target folder to store output.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional relative output file path within target folder.",
                },
            },
            "required": ["url"],
        }

    def execute(
        self,
        url: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Any = None,
        json: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
        save_policy: str = "inline",
        output_target: str = "memory",
        output_path: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        target = str(url or "").strip()
        if not target:
            return "Error: url is required."

        safety_error = validate_outbound_url(target)
        if safety_error:
            content = self._as_json(
                {
                    "url": target,
                    "error": f"Blocked by safety policy: {safety_error}",
                }
            )
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        method_upper = str(method or "GET").strip().upper()
        allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        if method_upper not in allowed_methods:
            return f"Error: unsupported method '{method_upper}'."
        if data is not None and json is not None:
            return "Error: data and json cannot be used at the same time."

        parsed_json_payload = self._parse_json_payload(json)
        if json is not None and parsed_json_payload is None:
            return "Error: json must be a valid JSON string."

        clean_headers = sanitize_request_headers(self._to_string_dict(headers))
        if "User-Agent" not in clean_headers and "user-agent" not in {k.lower() for k in clean_headers}:
            clean_headers["User-Agent"] = self.default_user_agent

        request_timeout = max(1, min(int(timeout_seconds or self.timeout), 120))

        try:
            response = requests.request(
                method=method_upper,
                url=target,
                params=params if isinstance(params, dict) else None,
                data=data,
                json=parsed_json_payload,
                headers=clean_headers,
                timeout=request_timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            content = self._as_json(
                {
                    "url": target,
                    "method": method_upper,
                    "error": f"Request failed: {exc}",
                }
            )
            return self._build_output_payload(
                content=content,
                save_policy=save_policy,
                output_target=output_target,
                output_path=output_path,
            )

        content_type = str(response.headers.get("Content-Type", ""))
        safe_textual = is_textual_content_type(content_type)
        raw_body = response.text if safe_textual else ""
        body_truncated = False
        if len(raw_body) > self.max_body_chars:
            raw_body = raw_body[: self.max_body_chars]
            body_truncated = True

        result = {
            "url": str(response.url),
            "method": method_upper,
            "status_code": int(response.status_code),
            "ok": bool(response.ok),
            "content_type": content_type or "unknown",
            "body_truncated": body_truncated,
            "body_length": len(raw_body),
            "blocked_non_text_body": not safe_textual,
            "body": raw_body if safe_textual else "",
        }
        if not safe_textual:
            result["safety_note"] = "Non-text/binary response body is blocked by safety policy."

        content = self._as_json(result)
        return self._build_output_payload(
            content=content,
            save_policy=save_policy,
            output_target=output_target,
            output_path=output_path,
        )

    def _build_output_payload(
        self,
        *,
        content: str,
        save_policy: str,
        output_target: str,
        output_path: Optional[str],
    ) -> Any:
        if save_policy != "file":
            return content
        return {
            "content": content,
            "history_mode": "file",
            "output_target": output_target if output_target in {"memory", "materials"} else "memory",
            "output_path": output_path,
        }

    def _as_json(self, payload: Dict[str, Any]) -> str:
        return jsonlib.dumps(payload, ensure_ascii=False, indent=2)

    def _to_string_dict(self, value: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items()}

    def _parse_json_payload(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list, str, int, float, bool)):
            if isinstance(value, str):
                try:
                    return jsonlib.loads(value)
                except Exception:
                    return None
            return value
        return None
