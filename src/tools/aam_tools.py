"""automatic-animation-maker（anim-thin）的 aam CLI 包裝工具。

讓本 SDK 的 Agent（例如本機 Gemma 4）不用 shell 就能做 video-set-thin：
每個工具只呼叫白名單內的一個 aam 子指令，參數用 JSON Schema 限制，回傳精簡 JSON。

環境變數：
- AAM_ROOT：automatic-animation-maker 專案根目錄（預設 E:/Repos/automatic-animation-maker）
- AAM_PYTHON：該專案的 python（預設 <AAM_ROOT>/.venv/Scripts/python.exe）
素材與題目路徑一律相對於 AAM_ROOT，且只允許 temppad/、temp/、runs/ 底下。
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.ai_core.tool_executor import BaseTool

logger = logging.getLogger(__name__)

AAM_ROOT = Path(os.getenv("AAM_ROOT", "E:/Repos/automatic-animation-maker")).resolve()
AAM_PYTHON = os.getenv("AAM_PYTHON", str(AAM_ROOT / ".venv" / "Scripts" / "python.exe"))
ALLOWED_PREFIXES = ("temppad/", "temp/", "runs/")
THEMES = ["bauhaus", "infographic", "slash", "stellar", "chroma", "collage", "explore", "cosmos", "speckle", "atelier"]
MAX_RETURN = 6000


def _safe_rel(path: str) -> Path:
    rel = str(path).replace("\\", "/")
    root = str(AAM_ROOT).replace("\\", "/").rstrip("/") + "/"
    if rel.lower().startswith(root.lower()):
        rel = rel[len(root):]
    rel = rel.lstrip("./")
    p = (AAM_ROOT / rel).resolve()
    if not str(p).replace("\\", "/").startswith(str(AAM_ROOT).replace("\\", "/")):
        raise ValueError(f"路徑超出專案：{path}")
    if not any(rel.startswith(x) for x in ALLOWED_PREFIXES):
        raise ValueError(f"只允許 {ALLOWED_PREFIXES} 底下的路徑：{path}")
    return p


BACKEND_ERROR_MARKERS = ("ensure_server", "後端沒有啟動", "in alive", "ConnectionRefused", "ConnectionReset",
                         "RemoteDisconnected", "WinError 10054", "WinError 10061")


def _last_error_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def _run_once(args: List[str], timeout: int) -> Dict[str, Any]:
    cmd = [AAM_PYTHON, "-X", "utf8", "scripts/aam.py", *args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        out = subprocess.run(cmd, cwd=str(AAM_ROOT), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    text = (out.stdout or "").strip()
    if "{" in text:
        try:
            return json.loads(text[text.index("{"):])
        except json.JSONDecodeError:
            pass
    raw = (out.stderr or "") + "\n" + text
    # 保留最後一行（真正的例外類型與訊息），traceback 本體對模型沒用
    return {"ok": False, "error": _last_error_line(raw) or "aam 沒有輸出", "raw_tail": raw[-600:]}


def _is_backend_error(r: Dict[str, Any]) -> bool:
    blob = f"{r.get('error', '')}\n{r.get('raw_tail', '')}"
    return not r.get("ok", False) and any(m in blob for m in BACKEND_ERROR_MARKERS)


def _run(args: List[str], timeout: int = 1800) -> Dict[str, Any]:
    """執行 aam 子指令，回傳解析後的 JSON（失敗時 ok=false）。

    常駐後端暫時沒回應時自動重試：等一下 → 再試 → 重啟後端 → 再試。
    """
    import time
    r = _run_once(args, timeout)
    for attempt, wait in enumerate((3, 10), start=1):
        if not _is_backend_error(r):
            break
        logger.warning("aam 後端沒回應（第 %s 次），%ss 後重試：%s", attempt, wait, r.get("error"))
        time.sleep(wait)
        if attempt == 2:
            _run_once(["stop"], 60)
            _run_once(["start"], 120)
        r = _run_once(args, timeout)
    if _is_backend_error(r):
        r["error"] = f"aam 後端沒有回應（已自動重試並重啟）：{r.get('error')}"
        r["backend_down"] = True
    r.pop("raw_tail", None)
    return r


def _trim(obj: Any) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= MAX_RETURN else s[:MAX_RETURN] + "…(truncated)"


class _AamTool(BaseTool):
    _name = ""
    _desc = ""
    _params: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._params


class AamMediaSheetTool(_AamTool):
    _name = "aam_media_sheet"
    _desc = ("把素材資料夾拼成縮圖表並用視覺模型描述每一張（插畫或照片、主體、能否去背、是否為 UI 截圖）。"
             "回傳每張素材的描述，不必再逐張看圖。")
    _params = {"type": "object", "properties": {
        "media_dir": {"type": "string", "description": "素材資料夾，例如 temppad/haiku_test/t01_eosd/media"}},
        "required": ["media_dir"]}

    def __init__(self, vision: Callable[[bytes, str], str]):
        self._vision = vision

    def execute(self, media_dir: str, **_: Any) -> str:
        src = _safe_rel(media_dir)
        out_dir = src.parent / "tmp" / "sheets"
        script = AAM_ROOT / "exp-thin/.claude/skills/anim-thin-from-media/scripts/contact_sheet.py"
        r = subprocess.run([AAM_PYTHON, str(script), str(src), "--out", str(out_dir)], cwd=str(AAM_ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        table = (r.stdout or "")[-3000:]
        notes = []
        for sheet in sorted(out_dir.glob("sheet_*.jpg")):
            notes.append(self._vision(sheet.read_bytes(),
                                      "這是一張素材縮圖表，每格標有 #編號 與檔名。逐格用一行描述："
                                      "檔名｜插畫或照片或 UI 截圖｜主體是什麼｜能否去背（單色底、主體完整才可以）。不要多寫。"))
        return _trim({"ok": r.returncode == 0, "table": table, "descriptions": notes})


SCHEMA_PATH = AAM_ROOT / "skills" / "video-set-thin" / "references" / "storyboard_schema.json"
VALIDATE_SNIPPET = (
    "import json,sys,jsonschema;s=json.load(open(sys.argv[1],encoding='utf-8'));"
    "d=json.load(open(sys.argv[2],encoding='utf-8'));v=jsonschema.Draft202012Validator(s);"
    "print(json.dumps([{'field':'.'.join(str(x) for x in list(e.path)[1:]) or '(段落)','message':e.message} "
    "for e in v.iter_errors(d)],ensure_ascii=False))")
SEGMENT_KEYS = ("id", "script", "key_text", "visual_type", "duration_sec", "block_hint", "media", "theme")


def _draft_path(run_id: str) -> Path:
    return AAM_ROOT / "temppad" / "agent_runs" / f"{run_id}_storyboard.json"


def _load_draft(run_id: str) -> List[Dict[str, Any]]:
    f = _draft_path(run_id)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


class AamStoryboardSegmentTool(_AamTool):
    _name = "aam_storyboard_segment"
    _desc = ("新增或覆寫分鏡的一段（一次只送一段，同 id 再送會覆蓋）。全部段落送完後呼叫 aam_storyboard_commit。"
             "key_text 最多 4 項、每項最多 5 個字（含英數，例如「東方」而不是「東方Project」）。")
    _params = {"type": "object", "properties": {
        "run_id": {"type": "string"},
        "id": {"type": "string", "description": "seg_01、seg_02…連號"},
        "script": {"type": "string", "description": "這段的一句口白"},
        "key_text": {"type": "array", "items": {"type": "string"}, "description": "畫面文字，1–4 項，每項 ≤5 字"},
        "visual_type": {"type": "string", "enum": ["big_number", "comparison", "list", "process", "chart",
                                                   "social", "title", "quote", "random"]},
        "duration_sec": {"type": "number", "description": "6–12"},
        "block_hint": {"type": "string", "description": "pk-* 骨架名"},
        "media": {"type": "object", "description": "選填：{槽名: {src: 素材路徑, cutout: bool, fit: 'contain'}}"}},
        "required": ["run_id", "id", "script", "key_text", "visual_type", "duration_sec", "block_hint"]}

    def execute(self, run_id: str, **kw: Any) -> str:
        # executor 會塞 _runtime_event_handler 等內部參數，只取分鏡欄位
        seg = {k: kw[k] for k in SEGMENT_KEYS if kw.get(k) not in (None, "", {})}
        for slot in (seg.get("media") or {}).values():
            if isinstance(slot, dict) and slot.get("src") and not os.path.isabs(slot["src"]):
                slot["src"] = str(_safe_rel(slot["src"]))
        f = _draft_path(run_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".check.json")
        tmp.write_text(json.dumps([seg], ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([AAM_PYTHON, "-X", "utf8", "-c", VALIDATE_SNIPPET, str(SCHEMA_PATH), str(tmp)],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        try:
            errors = json.loads(p.stdout.strip() or "[]")
        except json.JSONDecodeError:
            errors = [{"field": "(驗證器)", "message": (p.stderr or p.stdout)[-500:]}]
        if errors:
            return _trim({"ok": False, "id": seg.get("id"), "errors": errors,
                          "hint": "只修正這些欄位，再送一次這一段"})
        draft = [s for s in _load_draft(run_id) if s.get("id") != seg["id"]] + [seg]
        draft.sort(key=lambda s: s.get("id", ""))
        f.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
        return _trim({"ok": True, "saved": seg["id"], "segments_so_far": [s["id"] for s in draft]})


class AamStoryboardCommitTool(_AamTool):
    _name = "aam_storyboard_commit"
    _desc = "把已送出的所有段落寫進 run，建立各段資料夾。所有段落都用 aam_storyboard_segment 送完後呼叫一次。"
    _params = {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]}

    def execute(self, run_id: str, **_: Any) -> str:
        draft = _load_draft(run_id)
        if not draft:
            return _trim({"ok": False, "error": "還沒有任何段落，先用 aam_storyboard_segment 一段一段送"})
        problems = _check_storyboard(draft)
        if problems:
            return _trim({"ok": False, "error": "分鏡還不符合規則，尚未寫入", "problems": problems,
                          "segments_so_far": [f"{s.get('id')}:{s.get('block_hint')}" for s in draft],
                          "fix": "用 aam_storyboard_segment 補段落或覆寫指定段落（同 id 再送即覆蓋），改完再 commit"})
        return _trim(_run(["storyboard", run_id, str(_draft_path(run_id))]))


def _check_storyboard(draft: List[Dict[str, Any]]) -> List[str]:
    """commit 前的結構檢查：段數、骨架種類、頭尾骨架、連號、素材都有用到。"""
    problems: List[str] = []
    n = len(draft)
    if n < 8:
        problems.append(f"只有 {n} 段，至少要 8 段（再送 seg_{n + 1:02d} 起的段落）")
    if n > 12:
        problems.append(f"有 {n} 段，最多 12 段")
    ids = [s.get("id") for s in draft]
    expected = [f"seg_{i:02d}" for i in range(1, n + 1)]
    if ids != expected:
        problems.append(f"id 要從 seg_01 連號，目前是 {ids}")
    blocks = [s.get("block_hint") for s in draft]
    kinds = len(set(blocks))
    if kinds < min(6, n):
        problems.append(f"只用了 {kinds} 種骨架，至少 6 種（目前：{blocks}）")
    for i in range(len(blocks) - 2):
        if blocks[i] == blocks[i + 1] == blocks[i + 2]:
            problems.append(f"{ids[i]}–{ids[i + 2]} 連續 3 段都是 {blocks[i]}，換掉中間那段")
            break
    if blocks and blocks[0] != "pk-title-card":
        problems.append("第一段要用 pk-title-card")
    if blocks and blocks[-1] != "pk-outro-cta":
        problems.append("最後一段要用 pk-outro-cta")
    used: set = set()
    media_dir: Optional[Path] = None
    for s in draft:
        for v in (s.get("media") or {}).values():
            src = v.get("src") if isinstance(v, dict) else v
            if isinstance(src, str) and src:
                p = Path(src)
                used.add(p.name)
                media_dir = media_dir or p.parent
    if media_dir and media_dir.exists():
        unused = sorted(p.name for p in media_dir.glob("*") if p.is_file() and p.name not in used)
        if unused:
            problems.append(f"這些素材還沒用到：{unused}")
    return problems


class AamSnapReviewTool(_AamTool):
    _name = "aam_snap_review"
    _desc = ("截圖某段（預設 1 秒、中段、結尾前 0.7 秒）並由視覺模型檢查：文字溢出或被裁、字太小、"
             "去背缺角或留色卡、空素材槽、範例字（帕魯、金幣、bmon 等）沒改、版面重疊。回傳問題清單；沒有問題回傳 PASS。")
    _params = {"type": "object", "properties": {
        "run_id": {"type": "string"}, "seg_id": {"type": "string"},
        "times": {"type": "array", "items": {"type": "number"}, "description": "截圖秒數，可留空"}},
        "required": ["run_id", "seg_id"]}

    def __init__(self, vision: Callable[[bytes, str], str]):
        self._vision = vision

    def execute(self, run_id: str, seg_id: str, times: Optional[List[float]] = None, **_: Any) -> str:
        if not times:
            import re
            cfg = str(_run(["show", run_id, seg_id]).get("config", ""))
            m = re.search(r"duration:\s*([\d.]+)", cfg)
            dur = float(m.group(1)) if m else 7.0
            times = [1.0, round(dur / 2, 1), round(dur - 0.7, 1)]
        r = _run(["snap", run_id, seg_id, *[str(t) for t in times]], timeout=900)
        sheet = r.get("sheet")
        if not r.get("ok") or not sheet or not Path(sheet).exists():
            return _trim({"ok": False, "error": r.get("error") or "snap failed"})
        verdict = self._vision(Path(sheet).read_bytes(),
                               "這是一段 16:9 動畫在幾個時間點的截圖（左到右）。只檢查以下問題並逐條列出（指出時間點與位置）："
                               "1 文字溢出、被裁切、重疊；2 字太小看不清；3 去背缺角、留下色卡或白邊；4 空的素材槽或灰色占位；"
                               "5 出現與主題無關的範例字（帕魯、金幣、碎岩龜、bmon、訂閱等）；6 版面明顯失衡。"
                               "完全沒有問題就只回答 PASS。")
        return _trim({"ok": True, "times": times, "sheet": sheet, "review": verdict})




def make_aam_tools(vision: Callable[[bytes, str], str]) -> List[BaseTool]:
    """舊名稱相容：現在等同 aam_cli_tool.make_aam_cli_tools。"""
    from src.tools.aam_cli_tool import make_aam_cli_tools
    return make_aam_cli_tools(vision)
