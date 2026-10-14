import json
import os
import re
import threading
import time
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, Response, abort, jsonify, redirect, render_template, request, stream_with_context, url_for
from markupsafe import Markup

from src.agent_factory import configure_logging, create_agent_components
from src.ai_core.history import LocalChatHistory


os.chdir(Path(__file__).resolve().parent)   # chat_history 等相對路徑一律以專案根目錄為準
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True  # 改頁面不用重開伺服器
configure_logging()
load_dotenv()

_sdk_docs_cache: Any = None
_sdk_docs_cache_lock = threading.Lock()

_HOW_TO_LANG_ORDER = ("zh-Hant", "en", "ja")
_HOW_TO_LANG_LABELS = {
    "zh-Hant": "繁體中文",
    "en": "English",
    "ja": "日本語",
}
_HOW_TO_SLUG_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]*$")


def _load_sdk_docs_index() -> Dict[str, Any]:
    """
    Load `docs/SDK/*.json` into a cache suitable for docs browsing.

    The JSON format is expected to follow the `sdk.reference.v1` schema:
    - index.sidebar: sidebar tree (module nodes with children symbol nodes)
    - symbols: list of symbol objects
    """
    docs_dir = Path(__file__).resolve().parent / "docs" / "SDK"
    module_index: Dict[str, Any] = {}
    symbol_index: Dict[str, Any] = {}
    modules_order: List[str] = []

    if not docs_dir.exists():
        return {
            "modules_order": [],
            "module_index": {},
            "symbol_index": {},
        }

    for doc_path in sorted(docs_dir.glob("*.json")):
        try:
            with open(doc_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            # Skip broken JSON files so the web UI still works.
            continue

        sidebar_entries = (doc.get("index") or {}).get("sidebar") or []
        symbols = doc.get("symbols") or []
        types = doc.get("types") or []
        # Sidebar children can point to both `symbols[]` (classes/functions/tools) and `types[]` (TypedDict/dataclass schemas).
        symbol_by_id: Dict[str, Any] = {
            str(item.get("id")): item
            for item in (symbols + types)
            if item.get("id")
        }

        if not sidebar_entries:
            continue

        primary_module_id = str(sidebar_entries[0].get("id") or "")

        for module_entry in sidebar_entries:
            module_id = str(module_entry.get("id") or "")
            if not module_id:
                continue

            module_children = module_entry.get("children") or []

            # Keep module order based on file iteration and module entries.
            if module_id not in module_index:
                modules_order.append(module_id)

            module_index[module_id] = {
                "doc": doc,
                "module_entry": module_entry,
                "sidebar_children": module_children,
            }

            for child in module_children:
                child_id = str(child.get("id") or "")
                if not child_id:
                    continue
                symbol_obj = symbol_by_id.get(child_id)
                if symbol_obj is None:
                    # Some docs may have sidebar children without a matching symbols[] entry.
                    continue
                symbol_index[child_id] = {
                    "symbol": symbol_obj,
                    "module_id": module_id,
                }

        # Fallback: if some symbol ids were not captured via sidebar children, map them to the first module.
        if primary_module_id and primary_module_id in module_index:
            for symbol_id, symbol_obj in symbol_by_id.items():
                if symbol_id and symbol_id not in symbol_index:
                    symbol_index[symbol_id] = {
                        "symbol": symbol_obj,
                        "module_id": primary_module_id,
                    }

    return {
        "modules_order": modules_order,
        "module_index": module_index,
        "symbol_index": symbol_index,
    }


def _get_sdk_docs_cache() -> Dict[str, Any]:
    global _sdk_docs_cache
    with _sdk_docs_cache_lock:
        if _sdk_docs_cache is None:
            _sdk_docs_cache = _load_sdk_docs_index()
        return _sdk_docs_cache


class RuntimeEventStore:
    def __init__(self):
        self._events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._completed: Dict[str, bool] = defaultdict(bool)
        self._runtime_meta: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def publish(self, conversation_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            self._events[conversation_id].append(event)

    def mark_completed(self, conversation_id: str) -> None:
        with self._lock:
            self._completed[conversation_id] = True

    def start_run(self, conversation_id: str) -> None:
        with self._lock:
            self._events[conversation_id] = []
            self._completed[conversation_id] = False

    def get_events_since(self, conversation_id: str, index: int) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events.get(conversation_id, [])[index:])

    def is_completed(self, conversation_id: str) -> bool:
        with self._lock:
            return self._completed.get(conversation_id, False)

    def set_runtime_meta(self, conversation_id: str, meta: Dict[str, Any]) -> None:
        with self._lock:
            self._runtime_meta[conversation_id] = dict(meta)

    def get_runtime_meta(self, conversation_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._runtime_meta.get(conversation_id, {}))


event_store = RuntimeEventStore()
history_backend = LocalChatHistory("chat_history")


def _event_handler(event: Dict[str, Any]) -> None:
    conversation_id = str(event["conversation_id"])
    event_store.publish(conversation_id, event)


def _detect_runtime_model(components: Dict[str, Any]) -> Dict[str, str]:
    llm = components.get("llm")
    backend = getattr(llm, "backend", None)
    model = str(getattr(backend, "model", "") or "")
    backend_name = backend.__class__.__name__.lower() if backend is not None else ""
    provider = ""
    if backend_name.endswith("wrapper"):
        provider = backend_name[:-7]
    elif backend_name:
        provider = backend_name
    return {"provider": provider, "model": model}


def _resolve_runtime_config_from_env() -> Dict[str, Any]:
    provider = str(os.getenv("LLM_PROVIDER", "gemini")
                   ).strip().lower() or "gemini"
    if provider == "gemini":
        model = str(os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
                    ).strip() or "gemini-3-flash-preview"
    else:
        model = str(os.getenv("OPENAI_MODEL", "")).strip()
    lm_api_url_raw = str(os.getenv("LM_API_URL", "")).strip()
    lm_api_url: Optional[str] = lm_api_url_raw or None
    return {"provider": provider, "model": model, "lm_api_url": lm_api_url}


def _run_agent_in_background(
    conversation_id: str,
    prompt: str,
    max_steps: int,
    provider: str = "gemini",
    model: Optional[str] = None,
    lm_api_url: Optional[str] = None,
    request_options: Optional[Dict[str, Any]] = None,
    enable_web_search_tool: bool = True,
    profile: str = "general",
) -> None:
    try:
        extra: Dict[str, Any] = {}
        if profile == "anim_thin":
            skill = (Path(__file__).parent / "skills" / "anim_thin" / "instructions.md").read_text(encoding="utf-8")
            extra = {"enabled_tools": [], "system_prompt_name": "video_agent", "system_prompt_vars": {"skill": skill},
                     "runtime_options": {"terse_steps": True, "drop_toolless_updates": True, "assistant_keep_full": 2},
                     "compression_config": {"keep_recent_tool_messages": 8},
                     "history_memory_config": {"retain_recent_messages": 100000}}  # 影片任務不封存歷史
            enable_web_search_tool = False
        components = create_agent_components(
            conversation_id,
            storage_directory="chat_history",
            event_handler=_event_handler,
            provider=provider,
            model=model,
            api_key=("local" if provider == "local" else None),
            lm_api_url=lm_api_url,
            request_options=request_options,
            enable_web_search_tool=enable_web_search_tool,
            **extra,
        )
        if profile == "anim_thin":
            from src.tools.aam_tools import make_aam_tools
            vision_llm = components["llm"]

            def _vision(img: bytes, q: str) -> str:
                try:
                    return vision_llm.analyze_image_bytes(prompt=q, image_bytes=img, mime_type="image/jpeg",
                                                          system_prompt="你是嚴格的影片畫面檢查員，精簡條列。")
                except Exception as e:  # noqa: BLE001
                    return f"(vision failed: {e})"
            components["tool_executor"].register_tools(make_aam_tools(_vision))
        runtime_meta = _detect_runtime_model(components)
        event_store.set_runtime_meta(conversation_id, runtime_meta)
        event_store.publish(
            conversation_id,
            {
                "type": "run_started",
                "conversation_id": conversation_id,
                **runtime_meta,
            },
        )
        runtime = components["runtime"]
        result = runtime.run(prompt, max_steps=max_steps)
        event_store.publish(
            conversation_id,
            {
                "type": "run_finished",
                "conversation_id": conversation_id,
                "content": result,
            },
        )
    except Exception as exc:
        event_store.publish(
            conversation_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "content": str(exc),
            },
        )
    finally:
        event_store.mark_completed(conversation_id)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/agent")
def agent_ui() -> str:
    """Discord × Codex 風格的 Agent 工作台。"""
    return render_template("agent_ui.html")


@app.get("/runs")
def runs_ui() -> str:
    """分段 Agent 執行檢視：Sessions｜分段｜段落詳情（思考、工具）｜進度與分派。"""
    return render_template("runs.html")


@app.get("/api/seg-runs")
def api_seg_runs():
    from src.seg_run_view import list_runs
    return jsonify(list_runs())


@app.get("/api/seg-runs/<run_id>")
def api_seg_run(run_id: str):
    from src.seg_run_view import run_detail
    if not _safe_conversation_id(run_id):
        abort(400)
    aam_root = Path(os.getenv("AAM_ROOT", "E:/Repos/automatic-animation-maker"))
    return jsonify(run_detail(run_id, aam_root))


_FILE_ROOTS = [Path(__file__).resolve().parent,
               Path(os.getenv("AAM_ROOT", "E:/Repos/automatic-animation-maker")).resolve()]
_FILE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}


@app.get("/api/file")
def serve_file():
    """只提供工作區內的圖片／影片（給 UI 顯示縮圖表與成片）。"""
    raw = str(request.args.get("path", "")).strip()
    try:
        p = Path(raw).resolve()
    except OSError:
        abort(400)
    if p.suffix.lower() not in _FILE_EXT or not p.is_file():
        abort(404)
    if not any(str(p).lower().startswith(str(r).lower()) for r in _FILE_ROOTS):
        abort(403)
    from flask import send_file
    return send_file(p, conditional=True)


@app.get("/api/runtime-defaults")
def runtime_defaults():
    cfg = _resolve_runtime_config_from_env()
    running = [cid for cid in list(event_store._completed.keys()) if not event_store.is_completed(cid)]
    return jsonify({**cfg, "running": running})


def _build_docs_sidebar(cache: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build a sidebar-friendly module list for templates.

    Each item includes:
    - module_id
    - label (display name)
    - children: [{id,label}]
    - doc: raw module doc json (for module view rendering)
    """
    modules_order: List[str] = cache.get("modules_order") or []
    module_index: Dict[str, Any] = cache.get("module_index") or {}
    sidebar: List[Dict[str, Any]] = []

    for module_id in modules_order:
        module_obj = module_index.get(module_id) or {}
        doc = module_obj.get("doc") or {}
        module_entry = module_obj.get("module_entry") or {}
        module_label = module_entry.get("label") or (
            doc.get("module") or {}).get("name") or module_id

        sidebar.append(
            {
                "module_id": module_id,
                "label": module_label,
                "children": module_obj.get("sidebar_children") or [],
                "doc": doc,
            }
        )
    return sidebar


def _get_module_symbols(cache: Dict[str, Any], module_id: str) -> List[Dict[str, Any]]:
    module_obj = (cache.get("module_index") or {}).get(module_id) or {}
    children = module_obj.get("sidebar_children") or []
    symbol_index: Dict[str, Any] = cache.get("symbol_index") or {}

    symbols: List[Dict[str, Any]] = []
    for child in children:
        symbol_id = str(child.get("id") or "")
        if not symbol_id:
            continue
        idx = symbol_index.get(symbol_id)
        if idx is None:
            continue
        symbols.append(idx["symbol"])
    return symbols


def _how_to_base_dir() -> Path:
    return Path(__file__).resolve().parent / "docs" / "how-to"


def _how_to_list_slugs(lang: str) -> List[str]:
    d = _how_to_base_dir() / lang
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def _how_to_read_title(md_path: Path) -> str:
    try:
        first = md_path.read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return md_path.stem
    if first.startswith("#"):
        return first.lstrip("# ").strip()
    return md_path.stem


def _how_to_pick_slug_for_lang(lang: str, preferred_slug: str) -> Optional[str]:
    slugs = _how_to_list_slugs(lang)
    if not slugs:
        return None
    if preferred_slug in slugs:
        return preferred_slug
    return slugs[0]


def _render_how_to_markdown(text: str) -> str:
    try:
        import markdown as md_lib
    except ImportError:
        # Fallback when `markdown` is not installed yet (run: pip install -r requirements.txt).
        return f"<pre class=\"docs-pre docs-md-fallback\">{escape(text)}</pre>"
    return md_lib.markdown(
        text,
        extensions=["fenced_code", "tables"],
        output_format="html5",
    )


@app.get("/docs")
def sdk_docs_index():
    cache = _get_sdk_docs_cache()
    modules_order: List[str] = cache.get("modules_order") or []
    if not modules_order:
        abort(404)
    active_module_id = modules_order[0]
    return sdk_docs_module(active_module_id)


@app.get("/docs/module/<module_id>")
def sdk_docs_module(module_id: str):
    cache = _get_sdk_docs_cache()
    module_index: Dict[str, Any] = cache.get("module_index") or {}
    if module_id not in module_index:
        abort(404)

    sidebar = _build_docs_sidebar(cache)
    module_obj = module_index[module_id]
    doc = module_obj.get("doc") or {}
    module_symbols = _get_module_symbols(cache, module_id)

    return render_template(
        "sdk_docs.html",
        view="module",
        docs_tab="sdk",
        sidebar=sidebar,
        active_module_id=module_id,
        active_symbol_id=None,
        module_doc=doc,
        module_symbols=module_symbols,
    )


@app.get("/docs/symbol/<symbol_id>")
def sdk_docs_symbol(symbol_id: str):
    cache = _get_sdk_docs_cache()
    symbol_index: Dict[str, Any] = cache.get("symbol_index") or {}
    if symbol_id not in symbol_index:
        abort(404)

    sidebar = _build_docs_sidebar(cache)
    symbol_obj = symbol_index[symbol_id]["symbol"]
    active_module_id = symbol_index[symbol_id]["module_id"]
    module_symbols = _get_module_symbols(cache, active_module_id)

    return render_template(
        "sdk_docs.html",
        view="symbol",
        docs_tab="sdk",
        sidebar=sidebar,
        active_module_id=active_module_id,
        active_symbol_id=symbol_id,
        module_doc=(((cache.get("module_index") or {}).get(
            active_module_id) or {}).get("doc") or {}),
        module_symbols=module_symbols,
        symbol_doc=symbol_obj,
    )


@app.get("/docs/how-to")
def how_to_docs_redirect():
    preferred = "zh-Hant"
    slug = _how_to_pick_slug_for_lang(preferred, "01-quick-start")
    if slug is None:
        abort(404)
    return redirect(url_for("how_to_docs_page", lang=preferred, slug=slug))


@app.get("/docs/how-to/<lang>")
def how_to_docs_lang_index(lang: str):
    if lang not in _HOW_TO_LANG_ORDER:
        abort(404)
    slug = _how_to_pick_slug_for_lang(lang, "01-quick-start")
    if slug is None:
        abort(404)
    return redirect(url_for("how_to_docs_page", lang=lang, slug=slug))


@app.get("/docs/how-to/<lang>/<slug>")
def how_to_docs_page(lang: str, slug: str):
    if lang not in _HOW_TO_LANG_ORDER:
        abort(404)
    if not _HOW_TO_SLUG_RE.fullmatch(slug):
        abort(404)

    md_path = _how_to_base_dir() / lang / f"{slug}.md"
    if not md_path.is_file():
        abort(404)

    raw_md = md_path.read_text(encoding="utf-8")
    content_html = Markup(_render_how_to_markdown(raw_md))

    nav_items: List[Dict[str, Any]] = []
    for s in _how_to_list_slugs(lang):
        p = _how_to_base_dir() / lang / f"{s}.md"
        nav_items.append(
            {"slug": s, "title": _how_to_read_title(p), "active": s == slug})

    lang_tabs: List[Dict[str, Any]] = []
    for lid in _HOW_TO_LANG_ORDER:
        target_slug = _how_to_pick_slug_for_lang(lid, slug)
        if target_slug is None:
            continue
        lang_tabs.append(
            {
                "id": lid,
                "label": _HOW_TO_LANG_LABELS.get(lid, lid),
                "url": url_for("how_to_docs_page", lang=lid, slug=target_slug),
                "active": lid == lang,
            }
        )

    return render_template(
        "how_to.html",
        docs_tab="howto",
        lang=lang,
        lang_label=_HOW_TO_LANG_LABELS.get(lang, lang),
        slug=slug,
        content_html=content_html,
        nav_items=nav_items,
        lang_tabs=lang_tabs,
    )


@app.get("/api/conversations")
def list_conversations():
    conversation_ids = history_backend.list_conversations()
    items = []
    for conversation_id in conversation_ids:
        if conversation_id.endswith(".result"):  # run_video_*.py 的結果檔，不是對話
            continue
        conversation = history_backend.get_conversation(conversation_id) or {}
        messages = conversation.get("messages", [])
        preview = ""
        if messages:
            preview = str(messages[-1].get("content", ""))[:120]
        items.append(
            {
                "conversation_id": conversation_id,
                "created_at": conversation.get("created_at"),
                "message_count": len(messages),
                "preview": preview,
            }
        )
    return jsonify(items)


@app.get("/api/conversations/<conversation_id>")
def get_conversation(conversation_id: str):
    conversation = history_backend.get_conversation(conversation_id)
    if conversation is None:
        return jsonify({"error": "Conversation not found"}), 404
    payload = dict(conversation)
    payload["messages"] = _restore_archived(conversation_id, payload.get("messages", []))
    payload["runtime_meta"] = event_store.get_runtime_meta(conversation_id)
    return jsonify(payload)


def _restore_archived(conversation_id: str, messages: list) -> list:
    """工作台顯示用：把 [ARCHIVED_MESSAGE] 換回 .archive 裡保存的原始訊息（紀錄檔本身不動）。"""
    if not _safe_conversation_id(conversation_id) or not any(m.get("archive_ref") for m in messages):
        return messages
    path = Path("chat_history") / ".archive" / f"{conversation_id}.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, json.JSONDecodeError):
        return messages
    originals = {e.get("archive_ref"): (e.get("level0") or {}).get("raw_message") for e in entries}
    restored = []
    for m in messages:
        raw = originals.get(m.get("archive_ref"))
        restored.append({**raw, "archived": True} if isinstance(raw, dict) else m)
    return restored


def _safe_conversation_id(conversation_id: str) -> bool:
    cid = str(conversation_id or "")
    return bool(cid) and "/" not in cid and "\\" not in cid and ".." not in cid


@app.get("/api/conversations/<conversation_id>/todos")
def get_conversation_todos(conversation_id: str):
    """Same JSON file as manage_todo_list: chat_history/todos/<conversation_id>.json"""
    if not _safe_conversation_id(conversation_id):
        return jsonify({"error": "invalid conversation_id"}), 400
    path = Path("chat_history") / "todos" / f"{conversation_id}.json"
    try:
        path = path.resolve()
        path.relative_to(Path("chat_history").resolve() / "todos")
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not path.is_file():
        return jsonify({"items": [], "updated_at": None})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return jsonify({"items": [], "updated_at": None, "error": "invalid_todo_json"})
    if not isinstance(data, dict):
        return jsonify({"items": [], "updated_at": None})
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    return jsonify({"items": items, "updated_at": data.get("updated_at")})


@app.post("/api/chat")
def create_chat():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    max_steps = int(payload.get("max_steps", 12))
    enable_google_search_grounding = bool(
        payload.get("enable_google_search_grounding", False))
    enable_web_search_tool = bool(payload.get(
        "enable_web_search_tool", not enable_google_search_grounding))
    google_search_exclude_domains = payload.get(
        "google_search_exclude_domains")
    conversation_id = str(payload.get("conversation_id", "")).strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    if not conversation_id:
        conversation_id = f"web_{uuid4().hex[:12]}"

    request_options: Dict[str, Any] = {}
    if enable_google_search_grounding:
        request_options["enable_google_search_grounding"] = True
    if isinstance(google_search_exclude_domains, list):
        request_options["google_search_exclude_domains"] = google_search_exclude_domains

    runtime_cfg = _resolve_runtime_config_from_env()
    profile = str(payload.get("profile", "general")).strip() or "general"
    for key in ("provider", "model", "lm_api_url"):
        val = str(payload.get(key, "") or "").strip()
        if val:
            runtime_cfg[key] = val
    event_store.start_run(conversation_id)
    queued_runtime_meta = {
        "provider": runtime_cfg["provider"],
        "model": runtime_cfg["model"],
        "lm_api_url": runtime_cfg.get("lm_api_url"),
    }
    event_store.set_runtime_meta(conversation_id, queued_runtime_meta)
    thread = threading.Thread(
        target=_run_agent_in_background,
        args=(
            conversation_id,
            prompt,
            max_steps,
            runtime_cfg["provider"],
            runtime_cfg["model"] or None,
            runtime_cfg.get("lm_api_url"),
            request_options or None,
            enable_web_search_tool,
            profile,
        ),
        daemon=True,
    )
    thread.start()
    return jsonify(
        {
            "conversation_id": conversation_id,
            "runtime_meta": queued_runtime_meta,
            "profile": profile,
        }
    )


@app.get("/api/stream/<conversation_id>")
def stream_events(conversation_id: str):
    def generate():
        index = 0
        yield "retry: 1000\n\n"
        while True:
            events = event_store.get_events_since(conversation_id, index)
            if events:
                for event in events:
                    index += 1
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            elif event_store.is_completed(conversation_id):
                yield "event: done\ndata: {}\n\n"
                break
            else:
                yield ": keep-alive\n\n"
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    app.run(debug=False, port=15220, threaded=True)
