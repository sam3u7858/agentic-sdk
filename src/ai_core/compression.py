import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def resolve_compression_int(
    compression_config: Optional[Dict[str, Any]],
    key: str,
    env_name: str,
    default: int,
) -> int:
    """compression_config[key] overrides env; invalid values fall back to default."""
    cc = compression_config or {}
    if key in cc and cc[key] is not None:
        try:
            return int(cc[key])
        except (TypeError, ValueError):
            pass
    raw = os.getenv(env_name)
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except ValueError:
            pass
    return int(default)


@dataclass
class SessionCompressionConfig:
    keep_recent_tool_messages: int = 6
    level1_window: int = 6
    level2_window: int = 10
    enable_level3_collapse: bool = True
    immediate_tool_token_limit: int = 32500
    token_char_ratio: int = 4
    immediate_tool_char_budget: int = 12000
    assistant_token_limit: int = 24000
    assistant_char_budget: int = 6000
    tool_line_collapse_trigger: int = 10
    tool_line_collapse_head: int = 5
    tool_line_collapse_tail: int = 5
    tool_line_collapse_max_chars: int = 500
    # Gate: skip tool-output / history-tool compression until loop step exceeds this
    # OR any tool payload exceeds compress_min_chars (characters).
    compress_min_step: int = 4
    compress_min_chars: int = 40000


class SessionToolResultCompressor:
    """Compress historical tool results for model context windows."""

    def __init__(self, config: Optional[SessionCompressionConfig] = None):
        self.config = config or SessionCompressionConfig()

    @staticmethod
    def _synthetic_tool_message(
        source: Dict[str, Any],
        *,
        tool_name: str,
        content: str,
        compression_level: int,
    ) -> Dict[str, Any]:
        """Build a tool message; OpenAI requires non-empty tool_call_id on role=tool."""
        msg: Dict[str, Any] = {
            "role": "tool",
            "name": tool_name,
            "content": content,
            "compression_level": compression_level,
        }
        tid = source.get("tool_call_id")
        if tid is not None and str(tid).strip() != "":
            msg["tool_call_id"] = tid
        else:
            msg["role"] = "user"
            msg.pop("name", None)
            msg["content"] = (
                f"[compressed tool summary name={tool_name}]\n{content}"
            )
        return msg

    def _should_apply_tool_compression_gate(
        self,
        *,
        loop_step: Optional[int],
        content: str,
    ) -> bool:
        """True when step is past compress_min_step or payload is larger than compress_min_chars."""
        cfg = self.config
        min_s = max(0, int(cfg.compress_min_step))
        min_c = max(0, int(cfg.compress_min_chars))
        if len(str(content)) > min_c:
            return True
        if loop_step is None:
            return True
        return int(loop_step) > min_s

    def compress_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        loop_step: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not messages:
            return []

        cfg = self.config
        min_s = max(0, int(cfg.compress_min_step))
        min_c = max(0, int(cfg.compress_min_chars))
        if loop_step is not None:
            tool_msgs = [m for m in messages if m.get("role") == "tool"]
            any_huge = any(len(str(m.get("content", ""))) > min_c for m in tool_msgs)
            if int(loop_step) <= min_s and not any_huge:
                return [dict(m) for m in messages]

        tool_indexes = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
        newest_tool_index = tool_indexes[-1] if tool_indexes else -1
        protected_tool_indexes = self._collect_unread_trailing_tool_indexes(messages)
        keep_newest_tool_full = newest_tool_index == (len(messages) - 1)
        should_level_compress = len(tool_indexes) > self.config.keep_recent_tool_messages
        keep_indexes = set(tool_indexes[-self.config.keep_recent_tool_messages :]) if should_level_compress else set()
        compressed: List[Dict[str, Any]] = []
        l3_buckets: List[Dict[str, Any]] = []

        for index, message in enumerate(messages):
            if message.get("role") != "tool":
                compressed.append(dict(message))
                continue

            msg_copy = dict(message)
            if index in protected_tool_indexes:
                # Keep the full trailing tool batch unchanged until assistant consumes it.
                compressed.append(msg_copy)
                continue
            # Keep newest tool output intact only when it is still the last message
            # (i.e., assistant has not read it yet in the current round).
            if index != newest_tool_index or not keep_newest_tool_full:
                raw_tool_text = str(msg_copy.get("content", ""))
                if self._should_apply_tool_compression_gate(loop_step=loop_step, content=raw_tool_text):
                    collapsed_content, is_collapsed = self._collapse_tool_lines(raw_tool_text)
                    if is_collapsed:
                        msg_copy["content"] = collapsed_content
                        msg_copy["line_collapsed"] = True

            if not should_level_compress or index in keep_indexes:
                compressed.append(msg_copy)
                continue

            age_rank = len(tool_indexes) - tool_indexes.index(index)
            tool_name = str(msg_copy.get("name") or "unknown_tool")
            status = "fail" if str(msg_copy.get("content", "")).startswith("Error:") else "success"

            if age_rank <= self.config.level1_window:
                compressed.append(
                    self._synthetic_tool_message(
                        msg_copy,
                        tool_name=tool_name,
                        content=f"[TOOL_METADATA] tool={tool_name} status={status}",
                        compression_level=1,
                    )
                )
                continue

            if age_rank <= self.config.level2_window:
                compressed.append(
                    self._synthetic_tool_message(
                        msg_copy,
                        tool_name=tool_name,
                        content="[TOOL_EXECUTED]",
                        compression_level=2,
                    )
                )
                continue

            if self.config.enable_level3_collapse:
                tid = str(msg_copy.get("tool_call_id") or "")
                if l3_buckets and l3_buckets[-1]["tool_name"] == tool_name:
                    l3_buckets[-1]["count"] += 1
                    l3_buckets[-1]["tool_call_ids"].append(tid)
                else:
                    l3_buckets.append(
                        {"tool_name": tool_name, "count": 1, "tool_call_ids": [tid]}
                    )

                # Delay append; we collapse contiguous old calls into action-loop markers.
                continue

            compressed.append(
                self._synthetic_tool_message(
                    msg_copy,
                    tool_name=tool_name,
                    content="[TOOL_EXECUTED]",
                    compression_level=2,
                )
            )

        if self.config.enable_level3_collapse and l3_buckets:
            collapsed = []
            for bucket in l3_buckets:
                content = (
                    f"<ActionLoop: {bucket['tool_name']} repeated "
                    f"{bucket['count']} times in historical steps>"
                )
                tname = bucket["tool_name"]
                non_empty_ids = [t for t in bucket["tool_call_ids"] if t]
                if non_empty_ids:
                    for tid in non_empty_ids:
                        collapsed.append(
                            {
                                "role": "tool",
                                "tool_call_id": tid,
                                "name": tname,
                                "content": content,
                                "compression_level": 3,
                            }
                        )
                else:
                    collapsed.append(
                        {
                            "role": "user",
                            "content": (
                                f"[compressed tool loop summary name={tname}]\n{content}"
                            ),
                            "compression_level": 3,
                        }
                    )
            # Prepend L3 markers so the model still sees long-horizon history hints first.
            compressed = collapsed + compressed

        return compressed

    def estimate_tokens(self, text: str) -> int:
        ratio = max(1, int(self.config.token_char_ratio))
        return max(1, (len(text) + ratio - 1) // ratio)

    def compress_tool_result(
        self,
        *,
        tool_name: str,
        content: str,
        token_limit_override: Optional[int] = None,
        char_budget_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        estimated_tokens = self.estimate_tokens(content)
        token_limit = (
            max(1, int(token_limit_override))
            if token_limit_override is not None
            else max(1, int(self.config.immediate_tool_token_limit))
        )
        if estimated_tokens <= token_limit:
            return {
                "content": content,
                "compressed": False,
                "estimated_tokens_before": estimated_tokens,
                "estimated_tokens_after": estimated_tokens,
                "token_limit": token_limit,
            }

        budget = (
            max(500, int(char_budget_override))
            if char_budget_override is not None
            else max(500, int(self.config.immediate_tool_char_budget))
        )
        compact_snippet = self._compact_json_preview(content, max_chars=min(5000, budget // 2))
        head_budget = max(200, int((budget - len(compact_snippet)) * 0.45))
        tail_budget = max(200, int((budget - len(compact_snippet)) * 0.35))
        head = content[:head_budget]
        tail = content[-tail_budget:] if len(content) > tail_budget else ""

        compressed_content = (
            "[TOOL_RESULT_COMPRESSED]\n"
            f"tool={tool_name}\n"
            f"estimated_tokens_before={estimated_tokens}\n"
            f"token_limit={token_limit}\n"
            f"original_chars={len(content)}\n"
            f"compression_reason=tool_output_exceeds_token_limit\n"
            "\n"
            f"{compact_snippet}\n"
            "\n"
            "[HEAD]\n"
            f"{head}\n"
            "\n"
            "[TAIL]\n"
            f"{tail}"
        ).strip()

        return {
            "content": compressed_content,
            "compressed": True,
            "estimated_tokens_before": estimated_tokens,
            "estimated_tokens_after": self.estimate_tokens(compressed_content),
            "token_limit": token_limit,
        }

    def compress_tool_result_progressive(
        self,
        *,
        tool_name: str,
        content: str,
        step: int,
        max_steps: int,
    ) -> Dict[str, Any]:
        text = str(content)
        if not self._should_apply_tool_compression_gate(loop_step=step, content=text):
            et = self.estimate_tokens(text)
            return {
                "content": text,
                "compressed": False,
                "skipped": True,
                "reason": "below_compress_min_step_and_char_gate",
                "estimated_tokens_before": et,
                "estimated_tokens_after": et,
                "token_limit": max(1, int(self.config.immediate_tool_token_limit)),
            }

        pressure = self._compression_pressure(step=step, max_steps=max_steps)
        token_limit = max(500, int(self.config.immediate_tool_token_limit * (1.0 - 0.7 * pressure)))
        char_budget = max(800, int(self.config.immediate_tool_char_budget * (1.0 - 0.75 * pressure)))
        return self.compress_tool_result(
            tool_name=tool_name,
            content=text,
            token_limit_override=token_limit,
            char_budget_override=char_budget,
        )

    def compress_assistant_content_progressive(
        self,
        *,
        content: str,
        step: int,
        max_steps: int,
    ) -> Dict[str, Any]:
        normalized = " ".join(str(content).split())
        if not normalized:
            return {
                "content": "",
                "compressed": False,
                "estimated_tokens_before": 0,
                "estimated_tokens_after": 0,
                "token_limit": 0,
            }

        pressure = self._compression_pressure(step=step, max_steps=max_steps)
        token_limit = max(300, int(self.config.assistant_token_limit * (1.0 - 0.7 * pressure)))
        char_budget = max(500, int(self.config.assistant_char_budget * (1.0 - 0.75 * pressure)))

        estimated_tokens = self.estimate_tokens(normalized)
        if estimated_tokens <= token_limit and len(normalized) <= char_budget:
            return {
                "content": normalized,
                "compressed": normalized != content,
                "estimated_tokens_before": estimated_tokens,
                "estimated_tokens_after": estimated_tokens,
                "token_limit": token_limit,
            }

        head_budget = max(120, int(char_budget * 0.6))
        tail_budget = max(80, int(char_budget * 0.25))
        middle_budget = max(0, char_budget - head_budget - tail_budget)
        head = normalized[:head_budget]
        tail = normalized[-tail_budget:] if len(normalized) > tail_budget else ""
        middle = normalized[head_budget : head_budget + middle_budget] if middle_budget > 0 else ""

        compressed = (
            "[ASSISTANT_CONTENT_COMPRESSED]\n"
            f"estimated_tokens_before={estimated_tokens}\n"
            f"token_limit={token_limit}\n"
            f"original_chars={len(normalized)}\n"
            "\n"
            "[HEAD]\n"
            f"{head}\n"
            "\n"
            "[MIDDLE]\n"
            f"{middle}\n"
            "\n"
            "[TAIL]\n"
            f"{tail}"
        ).strip()

        return {
            "content": compressed,
            "compressed": True,
            "estimated_tokens_before": estimated_tokens,
            "estimated_tokens_after": self.estimate_tokens(compressed),
            "token_limit": token_limit,
        }

    def _compact_json_preview(self, content: str, max_chars: int) -> str:
        try:
            parsed = json.loads(content)
        except Exception:
            return "[STRUCTURE] non-json payload"

        if isinstance(parsed, dict):
            keys = list(parsed.keys())
            preview = {
                "type": "object",
                "top_level_keys": keys[:30],
                "top_level_key_count": len(keys),
            }
        elif isinstance(parsed, list):
            preview = {
                "type": "array",
                "length": len(parsed),
                "first_item_type": type(parsed[0]).__name__ if parsed else None,
            }
        else:
            preview = {
                "type": type(parsed).__name__,
                "repr": str(parsed)[:300],
            }

        text = f"[STRUCTURE]\n{json.dumps(preview, ensure_ascii=False, indent=2)}"
        return text[:max_chars]

    def _compression_pressure(self, *, step: int, max_steps: int) -> float:
        if max_steps <= 1:
            return 1.0
        bounded_step = min(max(step, 1), max_steps)
        return (bounded_step - 1) / (max_steps - 1)

    def _collapse_tool_lines(self, content: str) -> tuple[str, bool]:
        trigger = max(1, int(self.config.tool_line_collapse_trigger))
        head_n = max(1, int(self.config.tool_line_collapse_head))
        tail_n = max(1, int(self.config.tool_line_collapse_tail))
        max_chars = max(120, int(self.config.tool_line_collapse_max_chars))

        lines = str(content).splitlines()
        if len(lines) <= trigger:
            return content, False

        effective_head_n = min(head_n, len(lines))
        remaining_after_head = max(0, len(lines) - effective_head_n)
        effective_tail_n = min(tail_n, remaining_after_head)
        head = lines[:effective_head_n]
        tail = lines[-effective_tail_n:] if effective_tail_n > 0 else []
        omitted = max(0, len(lines) - effective_head_n - effective_tail_n)

        # Keep collapsed output within head+tail lines (default <= 10 lines).
        if head:
            head[0] = f"[TOOL_LINE_COLLAPSED omitted={omitted}] {head[0]}"
        else:
            head = [f"[TOOL_LINE_COLLAPSED omitted={omitted}]"]

        collapsed_parts: List[str] = []
        collapsed_parts.extend(head)
        collapsed_parts.extend(tail)
        collapsed_text = "\n".join(collapsed_parts)
        if len(collapsed_text) <= max_chars:
            return collapsed_text, True
        return self._cap_collapsed_chars(collapsed_text, max_chars=max_chars), True

    def _collect_unread_trailing_tool_indexes(self, messages: List[Dict[str, Any]]) -> set[int]:
        if not messages:
            return set()
        idx = len(messages) - 1
        trailing: List[int] = []
        while idx >= 0 and messages[idx].get("role") == "tool":
            trailing.append(idx)
            idx -= 1
        if not trailing:
            return set()
        if idx < 0:
            return set(trailing)
        prev = messages[idx]
        if prev.get("role") == "assistant" and prev.get("tool_calls"):
            return set(trailing)
        return set()

    def _cap_collapsed_chars(self, text: str, *, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        head_budget = max(40, int(max_chars * 0.6))
        tail_budget = max(20, max_chars - head_budget - 24)
        head = text[:head_budget]
        tail = text[-tail_budget:] if tail_budget > 0 else ""
        omitted = max(0, len(text) - len(head) - len(tail))
        marker = f"\n... ({omitted} chars omitted) ...\n"
        compact = f"{head}{marker}{tail}"
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars]
