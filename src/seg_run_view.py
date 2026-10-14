"""把分段 Agent 流程的對話紀錄整理成「執行檢視」用的結構：階段、企劃、每段狀態、截圖、子對話。

資料來源都是 chat_history 裡的紀錄檔（主對話 <id>.json、每段子對話 <id>__seg_NN.json、結果 <id>.result.json），
所以 CLI 跑的流程也能即時看到，不需要另外的狀態服務。
"""
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HISTORY = Path("chat_history")
STAGES = [("topic", "讀題目與素材"), ("plan", "企劃（分鏡）"), ("build", "建專案、放骨架與素材"),
          ("segments", "每段 Agent"), ("render", "渲染"), ("export", "輸出成片")]


def _load(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json(text: Any) -> Any:
    try:
        return json.loads(text) if isinstance(text, str) else text
    except json.JSONDecodeError:
        return None


def list_runs() -> List[Dict[str, Any]]:
    out = []
    for p in sorted(HISTORY.glob("*_seg_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".result.json") or "__seg_" in p.stem:
            continue
        m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})_seg_(.+)$", p.stem)
        res = _load(p.with_name(p.stem + ".result.json"))
        subs = len(list(HISTORY.glob(f"{p.stem}__seg_*.json")))
        out.append({"id": p.stem, "topic": m.group(7) if m else p.stem,
                    "when": f"{m.group(2)}/{m.group(3)} {m.group(4)}:{m.group(5)}" if m else "",
                    "model": (res or {}).get("model") or _model_from_first(p),
                    "done": res is not None, "seconds": (res or {}).get("seconds"),
                    "error": ((res or {}).get("result") or {}).get("error"),
                    "segments_started": subs, "live": res is None and time.time() - p.stat().st_mtime < 600})
    return out


def _model_from_first(p: Path) -> str:
    d = _load(p) or {}
    first = next((m for m in d.get("messages", []) if m.get("role") == "user"), {})
    m = re.search(r"模型 ([^）)]+)", str(first.get("content", "")))
    return m.group(1) if m else ""


def run_detail(run_id: str, aam_root: Path) -> Dict[str, Any]:
    d = _load(HISTORY / f"{run_id}.json")
    if d is None:
        return {"error": "找不到這個執行"}
    msgs = d.get("messages", [])
    result = _load(HISTORY / f"{run_id}.result.json")
    calls = []  # (工具名, 參數, 結果)
    for i, m in enumerate(msgs):
        for tc in m.get("tool_calls") or []:
            res = next((x for x in msgs[i + 1:i + 4] if x.get("tool_call_id") == tc.get("id")), None)
            calls.append((tc["function"]["name"], _json(tc["function"].get("arguments")) or {},
                          _json(res.get("content")) if res else None))
    names = [c[0] for c in calls]

    # 企劃：最後一個 [plan…] 提問之後的模型回覆
    plan, plan_msg = None, None
    for i, m in enumerate(msgs):
        if m.get("role") == "user" and str(m.get("content", "")).startswith("[plan"):
            ans = next((x for x in msgs[i + 1:] if x.get("role") == "assistant" and not x.get("tool_calls")), None)
            if ans:
                plan_msg = ans
                plan = _extract(ans.get("content", ""))
    plan_checks = [c[2] for c in calls if c[0] == "check_plan" and isinstance(c[2], dict)]
    repairs = [c[2] for c in calls if c[0] == "repair_plan" and isinstance(c[2], dict)]

    run = next((c[2].get("run_id") for c in calls if c[0] == "aam create" and isinstance(c[2], dict)), None)
    theme = (plan or {}).get("theme")

    # 每段狀態
    segs: Dict[str, Dict[str, Any]] = {}
    for name, args, res in calls:
        if name == "aam add":
            segs.setdefault(args.get("seg"), {}).update({"block": args.get("block")})
        if name == "aam media" and args.get("seg"):
            segs.setdefault(args["seg"], {}).setdefault("media", {})[args.get("slot")] = args.get("file")
        if name == "segment_agent" and isinstance(res, dict):
            s = segs.setdefault(args.get("seg"), {})
            if res.get("status") == "started":
                s.update({"status": "running", "sub": args.get("conversation"), "progress": res.get("progress")})
            elif res.get("status") == "done":
                s.update({"status": "done", "review": res.get("review"), "seconds": res.get("seconds")})
        if name == "safe_segment":
            segs.setdefault(args.get("seg"), {})["fallback"] = True
    final = {s["seg"]: s for s in ((result or {}).get("result") or {}).get("segments", [])}
    plan_segs = (plan or {}).get("segments") or []
    out_segs = []
    for idx, seg_id in enumerate(sorted(k for k in segs if k)):
        s = segs[seg_id]
        f = final.get(seg_id, {})
        p = plan_segs[idx] if idx < len(plan_segs) else {}
        sheet = aam_root / "runs" / str(run) / "segments" / seg_id / "snapshots" / "cli-sheet.jpg" if run else None
        review = f.get("review") or s.get("review")
        state = s.get("status") or "queued"
        if state == "done":
            state = "pass" if review == "PASS" else ("fallback" if str(review).startswith("保底") or s.get("fallback")
                                                      else "warn")
        out_segs.append({"id": seg_id, "block": f.get("block") or s.get("block") or p.get("block"),
                         "script": p.get("script"), "key_text": p.get("key_text"),
                         "media": s.get("media") or {}, "state": state, "review": review,
                         "summary": f.get("summary"), "seconds": f.get("seconds") or s.get("seconds"),
                         "shots": f.get("reviews"), "sub": s.get("sub") or f.get("conversation"),
                         "checks": f.get("checks"), "human_check": f.get("human_check") or [],
                         "sheet": str(sheet) if sheet and sheet.exists() else None})

    has = lambda n: n in names  # noqa: E731
    stage_state = {
        "topic": "done" if has("read_topic") else "running",
        "plan": "done" if plan_checks and plan_checks[-1].get("ok") else ("running" if has("read_topic") else "todo"),
        "build": "done" if has("segment_agent") else ("running" if has("aam create") else "todo"),
        "segments": ("done" if out_segs and all(s["state"] not in ("running", "queued") for s in out_segs)
                     and has("aam render") else ("running" if has("segment_agent") else "todo")),
        "render": "done" if has("aam export") else ("running" if has("aam render") else "todo"),
        "export": "done" if result else ("running" if has("aam export") else "todo"),
    }
    if result and (result.get("result") or {}).get("error"):
        stage_state = {k: ("error" if v == "running" else v) for k, v in stage_state.items()}
    video = ((result or {}).get("result") or {}).get("video")
    return {"id": run_id, "run_id": run, "theme": theme, "theme_reason": (plan or {}).get("theme_reason"),
            "stages": [{"key": k, "label": label, "state": stage_state[k]} for k, label in STAGES],
            "plan": {"attempts": len(plan_checks), "problems": [c.get("problems") for c in plan_checks],
                     "repairs": [r.get("fixed") for r in repairs],
                     "reasoning": (plan_msg or {}).get("reasoning"), "usage": (plan_msg or {}).get("usage")},
            "segments": out_segs, "done": result is not None, "seconds": (result or {}).get("seconds"),
            "model": (result or {}).get("model") or _model_from_first(HISTORY / f"{run_id}.json"),
            "video": video, "error": ((result or {}).get("result") or {}).get("error")}


def _extract(text: str) -> Optional[Dict[str, Any]]:
    try:
        from src.video_thick import extract_json
        v = extract_json(text)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None
