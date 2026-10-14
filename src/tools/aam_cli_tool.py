"""aam(args)：把 automatic-animation-maker 的 scripts/aam.py 包成單一通用工具。

只開放做影片需要的子指令；失敗一律回傳 {ok:false, cmd, error, fix, usage, example}，
讓小模型看一次就知道怎麼改參數。
"""
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.ai_core.tool_executor import BaseTool
from src.tools.aam_background import AamWaitTool, BackgroundJobs, WithBackground
from src.tools.aam_tools import (AAM_ROOT, AamMediaSheetTool, AamSnapReviewTool, AamStoryboardCommitTool,
                                 AamStoryboardSegmentTool, _AamTool, _run, _safe_rel, _trim)

AAM_USAGE = {
    "brief": ('["brief", 題目資料夾]', '["brief", "temppad/haiku_test/t01_eosd"]'),
    "blocks": ('["blocks", "--theme", 風格, ("--query", 關鍵字)]', '["blocks", "--theme", "collage"]'),
    "create": ('["create", "--title", 英數標題, "--theme", 風格, "--script", 全片口白]',
               '["create", "--title", "eosd-intro", "--theme", "collage", "--script", "東方紅魔鄉是…"]'),
    "add": ('["add", run_id, seg_id, pk-骨架]', '["add", RUN, "seg_01", "pk-title-card"]'),
    "show": ('["show", run_id, seg_id]', '["show", RUN, "seg_01"]'),
    "config": ('["config", run_id, seg_id, "--set", "鍵=值", ...]（陣列、物件的值寫成 JSON）',
               '["config", RUN, "seg_01", "--set", "title=紅魔館", "--set", "items=[\\"琪露諾\\",\\"美鈴\\"]"]'),
    "media": ('["media", run_id, seg_id, 槽名, 素材路徑, ("--cutout"), ("--fit", "contain"|"cover")]',
              '["media", RUN, "seg_02", "hero", "temppad/haiku_test/t01_eosd/media/cirno.png", "--cutout"]'),
    "render": ('["render", run_id]（會等到渲染完成）', '["render", RUN]'),
    "export": ('["export", run_id, ("--transition", 轉場)]', '["export", RUN, "--transition", "fade"]'),
    "transitions": ('["transitions"]', '["transitions"]'),
}
AAM_ALLOWED = tuple(AAM_USAGE)


def _fail(cmd: str, error: str, fix: str, **extra: Any) -> str:
    out: Dict[str, Any] = {"ok": False, "cmd": cmd, "error": error, "fix": fix}
    if cmd in AAM_USAGE:
        out["usage"], out["example"] = AAM_USAGE[cmd]
    out.update(extra)
    return _trim(out)


def _dir_listing(path: str) -> List[str]:
    try:
        return sorted(p.name for p in _safe_rel(path).parent.glob("*") if p.is_file())[:30]
    except Exception:  # noqa: BLE001
        return []


def _explain(cmd: str, err: str, args: List[str]) -> str:
    """把 aam 的錯誤轉成「原因＋怎麼改」。"""
    e = err or ""
    low = e.lower()
    if "aam 後端沒有回應" in e:
        return _fail(cmd, e[:200], "後端已自動重啟過仍失敗：換下一段繼續做，最後在報告裡列出這段")
    if any(k in e for k in ("the following arguments are required", "unrecognized arguments",
                            "invalid choice", "expected one argument")):
        return _fail(cmd, "參數格式不對：" + e.split("error:")[-1].strip()[:200], "照 usage 的順序與旗標重送")
    if "run id" in e and "找不到" in e:
        return _fail(cmd, "run_id 不存在", "用 create 回傳的完整 run_id（例如 20261008-181801-eosd-intro）")
    if "分鏡中沒有" in e:
        return _fail(cmd, "這個 seg_id 不在分鏡裡",
                     "先用 aam_storyboard_segment 送這段，再呼叫 aam_storyboard_commit；或改用已存在的 seg_id")
    if "block" in low and ("not found" in low or "找不到" in e or "unknown" in low):
        return _fail(cmd, "沒有這個骨架", '用 ["blocks", "--theme", 風格] 查正確的 pk-* 名稱')
    if "filenotfound" in low or "no such file" in low or "不存在" in e:
        src = args[4] if cmd == "media" and len(args) > 4 else ""
        return _fail(cmd, "找不到檔案", "從 available 挑正確檔名，路徑相對專案根目錄",
                     available=_dir_listing(src) if src else [])
    if "timeout" in low:
        return _fail(cmd, e[:200], "重試一次；仍逾時就跳過並在最後回報")
    last = e.strip().splitlines()[-1][:300] if e.strip() else "未知錯誤"
    return _fail(cmd, last, "讀 error 判斷要改哪個參數；不要原封不動重送")


def _shape(cmd: str, r: Dict[str, Any], args: List[str]) -> str:
    """成功時只回下一步需要的欄位。"""
    if cmd == "blocks":
        bl = [{"name": b.get("name"), "use": (b.get("description") or "")[:90]}
              for b in r.get("blocks", []) if str(b.get("name", "")).startswith("pk-")]
        return _trim({"ok": True, "blocks": bl})
    if cmd == "create":
        return _trim({"ok": True, "run_id": r.get("run_id")})
    if cmd in ("add", "show"):
        return _trim({"ok": True, "config": r.get("config"),
                      "slots": [f"{s.get('name')}：{s.get('label', '')}" for s in r.get("slots", [])]})
    if cmd == "config":
        errs = r.get("errors") or []
        vio = (r.get("style") or {}).get("violations") or []
        if errs or vio:
            return _trim({"ok": False, "cmd": cmd, "error": "lint 未通過", "errors": errs, "violations": vio,
                          "fix": "只改被點名的鍵（字數、項數照 CONFIG 註解的上限），再 config 一次"})
        return _trim({"ok": True})
    if cmd == "media":
        return _trim({"ok": True, "cutout": r.get("cutout")})
    if cmd == "render":
        return _trim({"ok": True, "next": '["export", RUN]'})
    if cmd == "export":
        runs = list((AAM_ROOT / "runs").glob(f"{args[1]}*")) if len(args) > 1 else []
        return _trim({"ok": True, "outputs": [str(p) for d in runs for p in (d / "export").glob("*.mp4")]})
    return _trim(r)


def _check_config_sets(args: List[str]) -> str:
    for i, a in enumerate(args):
        if i and args[i - 1] == "--set":
            if "=" not in a:
                return _fail("config", f"--set 的值 {a!r} 缺少「=」", "寫成 鍵=值")
            key, v = a.split("=", 1)
            v = v.strip()
            if v[:1] in "[{":
                try:
                    json.loads(v)
                except json.JSONDecodeError as je:
                    return _fail("config", f"{key} 的 JSON 壞掉：{je.msg}（第 {je.pos} 字元）",
                                 '陣列寫成 ["甲","乙"]，字串用雙引號，括號要成對')
    return ""


class AamCliTool(_AamTool):
    _name = "aam"
    _desc = ("執行 aam 影片 CLI。args 是字串陣列，第一項是子指令（" + "、".join(AAM_ALLOWED) +
             "），用法見技能。失敗時回傳 error（原因）、fix（怎麼改）、example（正確寫法）。")
    _params = {"type": "object", "properties": {
        "args": {"type": "array", "items": {"type": "string"},
                 "description": '例如 ["add", "20261008-181801-eosd-intro", "seg_01", "pk-title-card"]'}},
        "required": ["args"]}

    def execute(self, args: Any = None, **_: Any) -> str:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = args.split()
        args = [str(a) for a in (args or [])]
        if not args:
            return _fail("", "args 是空的", "第一項放子指令", allowed=list(AAM_ALLOWED))
        cmd = args[0]
        if cmd not in AAM_USAGE:
            return _fail(cmd, f"不支援的子指令 {cmd!r}", "改用 allowed 裡的子指令", allowed=list(AAM_ALLOWED))
        try:
            if cmd == "brief":
                return self._brief(args)
            if cmd == "config":
                bad = _check_config_sets(args)
                if bad:
                    return bad
            if cmd == "media" and len(args) > 4:
                args[4] = str(_safe_rel(args[4]))
                if not Path(args[4]).exists():
                    return _fail(cmd, f"找不到素材 {args[4]}", "從 available 挑正確檔名",
                                 available=sorted(p.name for p in Path(args[4]).parent.glob("*") if p.is_file())[:30])
            if cmd == "render" and "--wait" not in args:
                args.append("--wait")
            if cmd == "export" and (len(args) < 3 or args[2].startswith("--")):
                args.insert(2, "concat")
            if cmd == "create" and "--title" in args:
                i = args.index("--title")
                title = args[i + 1] if i + 1 < len(args) else ""
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{1,39}", title):
                    return _fail(cmd, f"--title {title!r} 只能用英文字母、數字、連字號（2–40 字）",
                                 "改成英文短標題，例如 touhou-intro；中文標題放在 --script 和畫面文字裡")
            if cmd == "create" and "--script" in args:
                i = args.index("--script")
                if i + 1 < len(args):
                    f = AAM_ROOT / "temppad" / "agent_runs" / "script.txt"
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(args[i + 1], encoding="utf-8")
                    args[i:i + 2] = ["--script-file", str(f)]
        except ValueError as ve:
            return _fail(cmd, str(ve), "路徑要在 temppad/、temp/、runs/ 底下（相對專案根目錄）")
        jobs = getattr(self, "jobs", None)
        if jobs is not None and cmd == "render":
            jobs.submit("render", "render", lambda a=list(args): json.loads(self._call(cmd, a)))
            return _trim({"ok": True, "queued": "render",
                          "note": "渲染在背景進行；export 會自動等它完成，也可以用 aam_wait 查看"})
        if jobs is not None and cmd == "export" and "render" in jobs.pending():
            jobs.wait(3600, keys=["render"], every=True)
        return self._call(cmd, args)

    def _call(self, cmd: str, args: List[str]) -> str:
        r = _run(args, timeout=3600 if cmd in ("render", "export") else 600)
        if cmd == "render" and "ok" not in r and isinstance(r.get("render"), dict):
            # render --wait 回傳 {render:{ok…}, status:{ok, counts…}}，沒有最外層 ok
            st = r.get("status") or {}
            failed = {k: v for k, v in (st.get("counts") or {}).items() if k != "done" and v}
            r = {"ok": bool(r["render"].get("ok") and st.get("ok", True) and not failed),
                 "error": f"有段落渲染失敗：{failed}" if failed else r["render"].get("error")}
        if not r.get("ok", False):
            return _explain(cmd, str(r.get("error") or ""), args)
        return _shape(cmd, r, args)

    @staticmethod
    def _brief(args: List[str]) -> str:
        if len(args) < 2:
            return _fail("brief", "缺題目資料夾", "第二項放題目資料夾路徑")
        d = _safe_rel(args[1])
        if not (d / "brief.md").exists():
            return _fail("brief", f"{args[1]} 底下沒有 brief.md", "用完整資料夾名稱（例如 t01_eosd）",
                         siblings=sorted(p.name for p in d.parent.glob("*") if p.is_dir())[:20])
        media = sorted(p.name for p in (d / "media").glob("*") if p.is_file()) if (d / "media").exists() else []
        return _trim({"ok": True, "brief": (d / "brief.md").read_text(encoding="utf-8"),
                      "media_dir": f"{args[1].rstrip('/')}/media", "media": media})


class AamSnapReviewAsyncTool(AamSnapReviewTool):
    """截圖檢查改成背景執行：送出就回，Agent 先做下一段。"""
    _desc = ("送出某段的截圖檢查（背景執行，不用等）：截圖後由視覺模型檢查文字溢出或被裁、字太小、去背缺角、"
             "空素材槽、範例字沒改、版面重疊。送出後直接做下一段；結果會出現在之後任何工具回傳的 background_done，"
             "review 不是 PASS 就回頭修那一段再送一次。")

    def __init__(self, vision: Callable[[bytes, str], str], jobs: BackgroundJobs):
        super().__init__(vision)
        self.jobs = jobs

    def execute(self, run_id: str, seg_id: str, times: Optional[List[float]] = None, **_: Any) -> str:
        def work() -> Dict[str, Any]:
            res = json.loads(AamSnapReviewTool.execute(self, run_id=run_id, seg_id=seg_id, times=times))
            return {"seg": seg_id, **{k: v for k, v in res.items() if k in ("ok", "review", "error")}}
        self.jobs.submit(f"review:{seg_id}", "review", work)
        return _trim({"ok": True, "queued": f"review:{seg_id}", "note": "已在背景檢查，先做下一段"})


def make_aam_cli_tools(vision: Callable[[bytes, str], str], background: bool = True) -> List[BaseTool]:
    if not background:
        return [AamCliTool(), AamMediaSheetTool(vision), AamStoryboardSegmentTool(), AamStoryboardCommitTool(),
                AamSnapReviewTool(vision)]
    jobs = BackgroundJobs(workers=2)
    cli = AamCliTool()
    cli.jobs = jobs
    tools: List[BaseTool] = [cli, AamMediaSheetTool(vision), AamStoryboardSegmentTool(), AamStoryboardCommitTool(),
                             AamSnapReviewAsyncTool(vision, jobs)]
    return [WithBackground(t, jobs) for t in tools] + [AamWaitTool(jobs)]
