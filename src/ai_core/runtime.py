# src/ai_core/runtime.py
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from src.ai_core.compression import (
    SessionCompressionConfig,
    SessionToolResultCompressor,
    resolve_compression_int,
)
from src.ai_core.session import ChatSession
from src.ai_core.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

class AgentRuntime:
    FINAL_MARKERS = ("<?final>", "</end_of_message>", "</final>")
    ASK_USER_MARKERS = ("<?ask_user>", "<?await_user>")

    def __init__(
        self,
        session: ChatSession,
        tool_executor: Optional[ToolExecutor] = None,
        event_handler: Optional[Callable[[Dict[str, Any]], None]] = None,
        compression_config: Optional[Dict[str, Any]] = None,
    ):
        self.session = session
        self.tool_executor = tool_executor or ToolExecutor()
        self.event_handler = event_handler
        cc = compression_config or {}
        self.session_compressor = SessionToolResultCompressor(
            SessionCompressionConfig(
                keep_recent_tool_messages=int(
                    cc.get("keep_recent_tool_messages", 6)
                ),
                level1_window=int(cc.get("level1_window", 6)),
                level2_window=int(cc.get("level2_window", 10)),
                enable_level3_collapse=bool(
                    cc.get("enable_level3_collapse", True)
                ),
                immediate_tool_token_limit=int(
                    cc.get("immediate_tool_token_limit", 32500)
                ),
                token_char_ratio=int(cc.get("token_char_ratio", 4)),
                immediate_tool_char_budget=int(
                    cc.get("immediate_tool_char_budget", 12000)
                ),
                assistant_token_limit=int(
                    cc.get("assistant_token_limit", 24000)
                ),
                assistant_char_budget=int(
                    cc.get("assistant_char_budget", 6000)
                ),
                tool_line_collapse_trigger=int(
                    cc.get("tool_line_collapse_trigger", 10)
                ),
                tool_line_collapse_head=int(
                    cc.get("tool_line_collapse_head", 5)
                ),
                tool_line_collapse_tail=int(
                    cc.get("tool_line_collapse_tail", 5)
                ),
                tool_line_collapse_max_chars=int(
                    cc.get("tool_line_collapse_max_chars", 500)
                ),
                compress_min_step=resolve_compression_int(
                    cc,
                    "compress_min_step",
                    "AGENT_TOOL_COMPRESS_MIN_STEP",
                    4,
                ),
                compress_min_chars=resolve_compression_int(
                    cc,
                    "compress_min_chars",
                    "AGENT_TOOL_COMPRESS_MIN_CHARS",
                    40000,
                ),
            )
        )

    def run(self, user_message: str, max_steps: int = 10) -> str:
        """ Start Agent autonomous loop """
        # 1. Write the initial instruction of the user
        self.session.history_backend.add_message(
            self.session.conversation_id,
            {"role": "user", "content": user_message}
        )

        logger.info(f"\n[Agent Runtime] Task started: {user_message}")
        self._emit_event(
            "task_started",
            {
                "conversation_id": self.session.conversation_id,
                "user_message": user_message,
                "max_steps": max_steps,
            },
        )
        last_visible_content = ""

        for step in range(1, max_steps + 1):
            logger.info("[Step %s] Collecting conversation context", step)
            self._emit_event("step_started", {"step": step})

            # 2. Get the current complete context history
            history = self.session.history_backend.get_conversation(self.session.conversation_id)
            history = history or {}
            messages = history.get("messages", [])

            # 3. Call LLM (with tool list)
            tools = self.tool_executor.schemas if self.tool_executor.schemas else None
            messages_for_model = self.session_compressor.compress_messages(
                list(messages),
                loop_step=step,
            )
            if messages_for_model != messages and hasattr(self.session.history_backend, "replace_messages"):
                try:
                    self.session.history_backend.replace_messages(
                        self.session.conversation_id,
                        messages_for_model,
                    )
                    messages = messages_for_model
                except Exception:
                    logger.exception("Failed to persist compressed conversation history")
            messages_for_model.append(
                {
                    "role": "user",
                    "content": self._build_step_instruction(step, max_steps),
                }
            )
            response = self.session.llm.get_completion(messages_for_model, tools=tools)
            self._log_assistant_response(step, response)
            self._emit_grounding_citations(step, response)

            is_final_response = self._is_final_response(response)
            is_user_handoff_response = self._is_user_handoff_response(response)
            cleaned_content = self._strip_final_markers(response.get("content", ""))
            cleaned_content = self._strip_handoff_markers(cleaned_content)
            if cleaned_content != response.get("content", ""):
                response["content"] = cleaned_content
            if cleaned_content:
                compressed_content, assistant_compression_meta = self._compress_assistant_content_if_needed(
                    content=cleaned_content,
                    step=step,
                    max_steps=max_steps,
                )
                response["content"] = compressed_content
                if assistant_compression_meta.get("compressed"):
                    self._emit_event(
                        "assistant_content_compressed",
                        {
                            "step": step,
                            "estimated_tokens_before": assistant_compression_meta.get(
                                "estimated_tokens_before"
                            ),
                            "estimated_tokens_after": assistant_compression_meta.get(
                                "estimated_tokens_after"
                            ),
                            "token_limit": assistant_compression_meta.get("token_limit"),
                        },
                    )
                cleaned_content = compressed_content
            if cleaned_content.strip():
                last_visible_content = cleaned_content

            # 4. Determine if LLM requests to call tools
            if "tool_calls" in response and response["tool_calls"]:
                # Save the request of LLM to history, keep the conversation chain complete
                self.session.history_backend.add_message(self.session.conversation_id, response)

                # Traverse and execute all requested tools
                for tool_call in response["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    self._emit_event(
                        "tool_requested",
                        {
                            "step": step,
                            "tool_name": tool_name,
                            "arguments_json": tool_call["function"].get("arguments", ""),
                        },
                    )
                    
                    try:
                        # Our LMWrapper uniformly converts arguments to a JSON string, here needs to be deserialized
                        args_str = tool_call["function"]["arguments"]
                        args = json.loads(args_str) if args_str else {}
                    except json.JSONDecodeError:
                        args = {}

                    logger.info(f"  ⏳ [Step {step}] Call tool: {tool_name}({args})")
                    progress_emitter = self._build_tool_progress_emitter(step=step, tool_name=tool_name)

                    # Execute by Host
                    raw_tool_result = self.tool_executor.execute(
                        tool_name,
                        {
                            **args,
                            "_runtime_event_handler": progress_emitter,
                            "_conversation_id": self.session.conversation_id,
                            "_storage_directory": str(
                                getattr(
                                    self.session.history_backend,
                                    "storage_directory",
                                    Path("chat_history"),
                                )
                            ),
                        },
                    )
                    tool_payload = self._normalize_tool_result_payload(
                        tool_name=tool_name,
                        raw_result=raw_tool_result,
                        call_args=args,
                    )
                    tool_result_raw = str(tool_payload.get("content", ""))
                    should_skip_auto_compress = bool(
                        str(tool_payload.get("history_mode", "inline")) == "file"
                        and str(tool_payload.get("output_target", "memory")) == "memory"
                        and not bool(tool_payload.get("memory_compress", False))
                    )
                    if should_skip_auto_compress:
                        tool_result = tool_result_raw
                        compression_meta = {
                            "compressed": False,
                            "skipped": True,
                            "reason": "memory_output_no_auto_compress",
                        }
                    else:
                        tool_result, compression_meta = self._compress_tool_result_if_needed(
                            tool_name=tool_name,
                            tool_result=tool_result_raw,
                            step=step,
                            max_steps=max_steps,
                        )
                    history_tool_content = tool_result
                    if str(tool_payload.get("history_mode", "inline")) == "file":
                        stored_path, write_error = self._persist_tool_output(
                            tool_name=tool_name,
                            content=tool_result,
                            output_target=str(tool_payload.get("output_target", "memory")),
                            output_path=tool_payload.get("output_path"),
                        )
                        if write_error:
                            history_tool_content = f"Error: failed to persist tool output: {write_error}"
                        else:
                            history_tool_content = self._build_saved_output_note(
                                tool_name=tool_name,
                                stored_path=stored_path,
                                content=tool_result,
                            )
                    else:
                        history_tool_content = self._strip_debug_fields_from_tool_content(
                            tool_name=tool_name,
                            content=tool_result,
                        )
                    logger.info(
                        "  📦 [Step %s] Tool result preview: %s",
                        step,
                        self._truncate_text(history_tool_content),
                    )
                    if compression_meta.get("compressed"):
                        logger.warning(
                            "  🗜️ [Step %s] Tool result compressed immediately: tool=%s before=%s after=%s limit=%s",
                            step,
                            tool_name,
                            compression_meta.get("estimated_tokens_before"),
                            compression_meta.get("estimated_tokens_after"),
                            compression_meta.get("token_limit"),
                        )
                        self._emit_event(
                            "tool_result_compressed",
                            {
                                "step": step,
                                "tool_name": tool_name,
                                "estimated_tokens_before": compression_meta.get(
                                    "estimated_tokens_before"
                                ),
                                "estimated_tokens_after": compression_meta.get(
                                    "estimated_tokens_after"
                                ),
                                "token_limit": compression_meta.get("token_limit"),
                            },
                        )
                    self._emit_event(
                        "tool_result",
                        {
                            "step": step,
                            "tool_name": tool_name,
                            "preview": self._truncate_text(history_tool_content, max_length=500),
                            "content": history_tool_content,
                            "compressed": bool(compression_meta.get("compressed")),
                            "compression_skipped": bool(compression_meta.get("skipped")),
                            "history_mode": tool_payload.get("history_mode", "inline"),
                        },
                    )

                    # Return the execution result to LLM (Role must be 'tool')
                    self.session.history_backend.add_message(
                        self.session.conversation_id,
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
                            "content": history_tool_content
                        }
                    )
                
                # Continue the loop, let LLM read the tool result and decide the next step
                continue
            
            else:
                # 5. No tool calls, treat response as an intermediate step unless a final marker is present
                self.session.history_backend.add_message(self.session.conversation_id, response)
                if response.get("content"):
                    self._emit_event(
                        "assistant_update",
                        {
                            "step": step,
                            "content": response["content"],
                            "is_final": is_final_response,
                            "is_user_handoff": is_user_handoff_response,
                        },
                    )
                if is_final_response:
                    logger.info(f"✅ [Agent Runtime] Task completed (total {step} steps)")
                    self._emit_event(
                        "final_answer",
                        {
                            "step": step,
                            "content": response["content"],
                        },
                    )
                    return response["content"]
                if is_user_handoff_response:
                    logger.info(
                        "⏸️ [Agent Runtime] Waiting for user reply after step %s",
                        step,
                    )
                    self._emit_event(
                        "awaiting_user",
                        {
                            "step": step,
                            "content": response["content"],
                        },
                    )
                    return response["content"]

                logger.info(
                    "  🔄 [Step %s] Assistant returned an intermediate update without tools. Continue autonomous loop.",
                    step,
                )
                self._emit_event(
                    "intermediate_update",
                    {
                        "step": step,
                        "content": response.get("content", ""),
                    },
                )

        if last_visible_content:
            final_message = (
                f"⚠️ Task stopped after reaching the maximum number of thinking steps ({max_steps} steps).\n\n"
                f"{last_visible_content}"
            )
            self._emit_event(
                "error",
                {
                    "step": max_steps,
                    "content": final_message,
                },
            )
            return (
                final_message
            )
        aborted_message = f"⚠️ Task aborted: Agent reached the maximum number of thinking steps ({max_steps} steps)."
        self._emit_event(
            "error",
            {
                "step": max_steps,
                "content": aborted_message,
            },
        )
        return aborted_message

    def _log_assistant_response(self, step: int, response: dict) -> None:
        content = (response.get("content") or "").strip()
        if content:
            logger.info(
                "  💬 [Step %s] Assistant content: %s",
                step,
                self._truncate_text(content),
            )
            self._emit_event(
                "assistant_content_preview",
                {
                    "step": step,
                    "preview": self._truncate_text(content, max_length=500),
                },
            )

        if response.get("tool_calls"):
            tool_names = [tool_call["function"]["name"] for tool_call in response["tool_calls"]]
            logger.info("  🛠️ [Step %s] Assistant requested tools: %s", step, tool_names)

        gemini_content = response.get("gemini_content") or {}
        if self._has_thought_signature(gemini_content):
            logger.info(
                "  🧠 [Step %s] Gemini returned thoughtSignature metadata only; readable chain-of-thought is not exposed.",
                step,
            )

    def _has_thought_signature(self, gemini_content: dict) -> bool:
        parts = gemini_content.get("parts", [])
        return any("thoughtSignature" in part for part in parts if isinstance(part, dict))

    def _truncate_text(self, value: str, max_length: int = 200) -> str:
        single_line = " ".join(value.split())
        if len(single_line) <= max_length:
            return single_line
        return single_line[: max_length - 3] + "..."

    def _build_step_instruction(self, step: int, max_steps: int) -> str:
        if step == 1:
            return (
                "Autonomous loop instruction: first write a short visible planning update in natural language "
                "describing how you will break down the task (for example: 我先..., 然後再...). "
                "After that, either call the next needed tool or continue the task. "
                "If the current user request is already satisfied, stop immediately and append <?final>. "
                "If you need the user to decide, clarify, or provide missing information, end your message with <?ask_user>. "
                "Do not invent follow-up tasks that the user did not ask for."
            )

        return (
            f"Autonomous loop instruction for step {step}/{max_steps}: first write a short visible progress update "
            "about what you learned and what you will do next (for example: 很好，我拿到資料了，接著讓我看看...). "
            "Then continue autonomously only if more work is still required to satisfy the current user request. "
            "If the requested task has been completed, append <?final> and stop. "
            "If you need the user to decide, clarify, or provide missing information, append <?ask_user> and stop. "
            "Do not expand the scope into extra analysis, planning, or output that the user did not request."
        )

    def _is_final_response(self, response: Dict[str, object]) -> bool:
        content = str(response.get("content", "") or "")
        return any(marker in content for marker in self.FINAL_MARKERS)

    def _is_user_handoff_response(self, response: Dict[str, object]) -> bool:
        content = str(response.get("content", "") or "")
        return any(marker in content for marker in self.ASK_USER_MARKERS)

    def _strip_final_markers(self, content: str) -> str:
        stripped = content
        for marker in self.FINAL_MARKERS:
            stripped = stripped.replace(marker, "")
        return stripped.strip()

    def _strip_handoff_markers(self, content: str) -> str:
        stripped = content
        for marker in self.ASK_USER_MARKERS:
            stripped = stripped.replace(marker, "")
        return stripped.strip()

    def _emit_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self.event_handler:
            return

        event = {
            "type": event_type,
            "conversation_id": self.session.conversation_id,
            "timestamp": datetime.now().isoformat(),
        }
        if payload:
            event.update(payload)

        try:
            self.event_handler(event)
        except Exception:
            logger.exception("Failed to emit runtime event")

    def _build_tool_progress_emitter(
        self,
        *,
        step: int,
        tool_name: str,
    ) -> Callable[[Dict[str, Any]], None]:
        def emit(progress_payload: Dict[str, Any]) -> None:
            payload = dict(progress_payload or {})
            if payload.get("phase") == "todo_updated":
                self._emit_event(
                    "todo_updated",
                    {
                        "step": step,
                        "tool_name": tool_name,
                        "todo_snapshot": payload.get("todo_snapshot"),
                    },
                )
                return
            payload.update(
                {
                    "step": step,
                    "tool_name": tool_name,
                }
            )
            self._emit_event("tool_progress", payload)

        return emit

    def _emit_grounding_citations(self, step: int, response: Dict[str, Any]) -> None:
        grounding = response.get("grounding_metadata")
        if not isinstance(grounding, dict):
            return

        chunks = grounding.get("groundingChunks", [])
        citations = []
        for chunk in chunks:
            web = chunk.get("web", {}) if isinstance(chunk, dict) else {}
            uri = web.get("uri")
            title = web.get("title")
            if uri:
                citations.append(
                    {
                        "title": str(title or uri),
                        "uri": str(uri),
                    }
                )

        self._emit_event(
            "grounding_citations",
            {
                "step": step,
                "web_search_queries": grounding.get("webSearchQueries", []),
                "citations": citations,
                "raw_grounding_metadata": grounding,
            },
        )

    def _compress_tool_result_if_needed(
        self,
        *,
        tool_name: str,
        tool_result: str,
        step: int,
        max_steps: int,
    ) -> tuple[str, Dict[str, Any]]:
        compression = self.session_compressor.compress_tool_result_progressive(
            tool_name=tool_name,
            content=str(tool_result),
            step=step,
            max_steps=max_steps,
        )
        return str(compression.get("content", "")), compression

    def _compress_assistant_content_if_needed(
        self,
        *,
        content: str,
        step: int,
        max_steps: int,
    ) -> tuple[str, Dict[str, Any]]:
        compression = self.session_compressor.compress_assistant_content_progressive(
            content=str(content),
            step=step,
            max_steps=max_steps,
        )
        return str(compression.get("content", "")), compression

    def _normalize_tool_result_payload(
        self,
        *,
        tool_name: str,
        raw_result: Any,
        call_args: Dict[str, Any],
    ) -> Dict[str, Any]:
        if isinstance(raw_result, dict):
            payload = dict(raw_result)
            content = payload.get("content")
            if content is None:
                content = json.dumps(raw_result, ensure_ascii=False, indent=2)
            normalized = {
                "content": str(content),
                "history_mode": str(payload.get("history_mode", payload.get("save_policy", "inline"))),
                "output_target": str(payload.get("output_target", "memory")),
                "output_path": payload.get("output_path"),
                "memory_compress": self._to_bool(
                    payload.get(
                        "memory_compress",
                        payload.get(
                            "memory-compress",
                            call_args.get("memory_compress", call_args.get("memory-compress", False)),
                        ),
                    )
                ),
            }
        else:
            normalized = {
                "content": str(raw_result),
                "history_mode": str(call_args.get("save_policy", "inline")),
                "output_target": str(call_args.get("output_target", "memory")),
                "output_path": call_args.get("output_path"),
                "memory_compress": self._to_bool(
                    call_args.get("memory_compress", call_args.get("memory-compress", False))
                ),
            }

        if normalized["history_mode"] not in {"inline", "file"}:
            normalized["history_mode"] = "inline"
        if normalized["output_target"] not in {"memory", "materials"}:
            normalized["output_target"] = "memory"
        return normalized

    def _to_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    def _persist_tool_output(
        self,
        *,
        tool_name: str,
        content: str,
        output_target: str,
        output_path: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        base_root = Path.cwd().resolve()
        target_root = (base_root / ("materials" if output_target == "materials" else "memory")).resolve()
        target_root.mkdir(parents=True, exist_ok=True)

        if output_path:
            cleaned = str(output_path).strip().replace("\\", "/")
            if cleaned.startswith("./"):
                cleaned = cleaned[2:]
            if cleaned.startswith("memory/"):
                target_root = (base_root / "memory").resolve()
                cleaned = cleaned[len("memory/") :]
            elif cleaned.startswith("materials/"):
                target_root = (base_root / "materials").resolve()
                cleaned = cleaned[len("materials/") :]
            final_path = (target_root / cleaned).resolve()
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            final_path = (target_root / f"{tool_name}_{timestamp}.txt").resolve()

        try:
            final_path.relative_to(target_root)
        except ValueError:
            return None, f"Invalid output path outside target root: {final_path}"

        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(content, encoding="utf-8")
        return str(final_path), None

    def _strip_debug_fields_from_tool_content(self, *, tool_name: str, content: str) -> str:
        try:
            parsed = json.loads(content)
        except Exception:
            return content

        if not isinstance(parsed, dict):
            return content

        debug_keys = [
            key
            for key in parsed.keys()
            if key in {"debug_logs", "logs", "trace", "stack_trace", "raw_trace"}
        ]
        if not debug_keys:
            return content

        detached: Dict[str, Any] = {}
        for key in debug_keys:
            detached[key] = parsed.pop(key)

        detached_text = json.dumps(detached, ensure_ascii=False, indent=2)
        stored_path, write_error = self._persist_tool_output(
            tool_name=f"{tool_name}_debug",
            content=detached_text,
            output_target="memory",
            output_path=None,
        )
        if write_error:
            parsed["debug_note"] = f"Debug fields detached but failed to persist: {write_error}"
        else:
            parsed["debug_note"] = f"Debug fields detached to: {stored_path}"
        return json.dumps(parsed, ensure_ascii=False, indent=2)

    def _build_saved_output_note(
        self,
        *,
        tool_name: str,
        stored_path: str,
        content: str,
    ) -> str:
        lines = str(content).splitlines()
        line_count = len(lines)
        size_bytes = len(str(content).encode("utf-8"))

        head_lines = lines[:10]
        tail_lines = lines[-10:] if line_count > 10 else []

        parts = [
            "[TOOL_OUTPUT_SAVED]",
            f"tool={tool_name}",
            f"path={stored_path}",
            f"line_count={line_count}",
            f"size_bytes={size_bytes}",
            "",
            "[HEAD_10_LINES]",
        ]
        if head_lines:
            parts.extend(head_lines)
        else:
            parts.append("(empty)")

        if line_count > 20:
            omitted = line_count - 20
            parts.extend(
                [
                    "",
                    f"... ({omitted} lines omitted) ...",
                ]
            )

        if tail_lines and line_count > 10:
            parts.extend(
                [
                    "",
                    "[TAIL_10_LINES]",
                ]
            )
            parts.extend(tail_lines)

        return "\n".join(parts)