"""分段 Agent 版：先由企劃 Agent 寫完整分鏡，再讓「每一段一個 Agent」依序把那段做完。

和 thin（一條長對話做完全部）比：每段的 Agent 都從乾淨的對話開始，只看得到 brief、
自己這段的分鏡與骨架 CONFIG，所以每次請求很小、進度清楚（第 3/11 段），出錯只影響那一段。
和 thick（程式代填）比：每段怎麼寫、怎麼修還是由 Agent 決定，可以自己看截圖檢查結果再改。

流程：
  1. 程式：讀題目、素材分析
  2. 企劃 Agent（一次呼叫，可開思考）：風格＋分鏡；程式檢查、自動補素材
  3. 程式：建專案、寫分鏡、放骨架、套設定、放素材
  4. 每段一個 Agent（依序）：config → 截圖檢查 → 有問題就修，最多 3 輪 → 回報
     結束後程式檢查：範例值沒換掉就改用保底標題卡，保證成片不留範本原文
  5. 程式：渲染、輸出、報告
"""
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper
from src.ai_core.runtime import AgentRuntime
from src.ai_core.session import ChatSession
from src.ai_core.tool_executor import BaseTool, ToolExecutor
from src.tools.aam_tools import AamSnapReviewTool, _run, _trim
from src.video_thick import BANNED, Pipeline, _config_chunks, _report_md
from src.video_thick_examples import fill_examples_text

SEG_SYSTEM = """你負責影片的「一段」。整支影片的企劃已經定好，你只做這一段，做完就結束。

做法：
1. 用 seg(["config", "--set", "鍵=值", ...]) 把 CONFIG 裡所有範例文字、數字換成這段的內容（一次改完）。
2. 呼叫 seg_review()，下一則訊息會附上截圖，你自己看。
3. 有問題：改 config（必要時用 seg(["media", 槽名, 素材檔名, "--cutout"]) 換素材），再 seg_review()。最多 3 輪。
   文字還在進場、淡入中不算問題；只修真的錯的地方。
4. 呼叫 seg_finish(checks, summary)：checks 對檢查表每一項回答 true（看到這個問題）或 false（沒看到）。
   只回答截圖上看得到的事，不用判斷內容對不對（那由真人確認）。然後回覆一句話，最後一行加 <?final>。

規則：
- 畫面上的名字、年份、數字只能來自 brief；字數照 CONFIG 註解的上限。
- 範例值一個都不能留：{banned}。
- 每次回覆都直接呼叫工具；不要重寫整段計畫。"""


def _jsonify(val: str) -> Optional[str]:
    """把 JS 物件寫法（{name:"x"}、{name="x"}、單引號）轉成合法 JSON；轉不了回傳 None。"""
    try:
        json.loads(val)
        return val
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*[:=]\s*", r'\1"\2": ', val)
    fixed = re.sub(r"'([^'\"]*)'", r'"\1"', fixed)
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)  # 結尾多的逗號
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        return None


def _leaf_texts(val: str) -> List[str]:
    """--set 的值若是 JSON（陣列、物件），只取出裡面的字串與數字；鍵名與設定類欄位（例如 from、image）不算內容。"""
    from src.video_thick import SETTING_FIELDS
    try:
        data = json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return [val]
    out: List[str] = []

    def walk(x: Any, key: str = "") -> None:
        if key in SETTING_FIELDS or key in ("from", "image", "side", "position"):
            return
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif not isinstance(x, bool) and x is not None:
            out.append(str(x))
    walk(data)
    return out


class SegCliTool(BaseTool):
    """只能操作「這一段」的 aam：run_id 與 seg_id 由程式帶入，Agent 不會改到別段。"""

    ALLOWED = ("config", "show", "media")
    LOCKED = {"duration", "layout"}

    def __init__(self, run_id: str, seg_id: str, media_dir: str, brief: str = ""):
        self.run_id, self.seg_id, self.media_dir = run_id, seg_id, media_dir
        self.brief = brief
        self._last_config: List[str] = []
        self.fail_streak = 0
        self.on_stuck: Optional[Callable[[List[str]], str]] = None

    def ungrounded(self, rest: List[str]) -> List[str]:
        """--set 的值裡，brief 沒出現過的數字（兩位數以上）與英文名稱（三個字母以上）。"""
        from src.video_thick import SETTING_FIELDS
        brief = self.brief.replace(",", "")
        low = brief.lower()
        bad = []
        for a in rest:
            if "=" not in a:
                continue
            key, val = a.split("=", 1)
            if key in SETTING_FIELDS:
                continue
            for text in _leaf_texts(val):  # 只看「值」，JSON 的鍵名（name、text…）不算內容
                for num in re.findall(r"\d{2,}", text.replace(",", "")):
                    if num not in brief:
                        bad.append(num)
                for word in re.findall(r"[A-Za-z][A-Za-z_]{2,}", text):
                    if word.lower() not in low:
                        bad.append(word)
        return sorted(set(bad))

    def _merge_dotted(self, rest: List[str]) -> Any:
        """caption.small=2023年、caption.side=right 這種「點號子欄位」：讀出目前的 caption 物件，
        改好再整個送出（aam config 只認最外層欄位）。值不是 JSON 時當字串。"""
        dotted: Dict[str, Dict[str, Any]] = {}
        out: List[str] = []
        for a in rest:
            key, sep, val = a.partition("=")
            if sep and "." in key and not key.startswith("-"):
                root, sub = key.split(".", 1)
                v = val.strip()
                try:
                    parsed = json.loads(v) if v else ""
                except json.JSONDecodeError:
                    parsed = v
                dotted.setdefault(root, {})[sub] = parsed
            else:
                out.append(a)
        if not dotted:
            return rest
        current = _config_chunks(str(_run(["show", self.run_id, self.seg_id]).get("config") or ""))
        for root, subs in dotted.items():
            base_text = current.get(root)
            base = json.loads(_jsonify(base_text) or "null") if base_text else None
            if not isinstance(base, dict):
                return _trim({"ok": False, "error": f"{root} 不是物件，不能用 {root}.子欄位 的寫法",
                              "fix": f"直接寫 {root}=新的值"})
            for sub, v in subs.items():
                base[sub.split(".")[0]] = v
            if out and out[-1] != "--set":
                out.append("--set")
            elif not out:
                out.append("--set")
            out.append(f"{root}={json.dumps(base, ensure_ascii=False)}")
        # 清掉因為移除點號欄位而留下的多餘 --set
        cleaned: List[str] = []
        for a in out:
            if a == "--set" and cleaned and cleaned[-1] == "--set":
                continue
            cleaned.append(a)
        if cleaned and cleaned[-1] == "--set":
            cleaned.pop()
        return cleaned

    @property
    def name(self) -> str:
        return "seg"

    @property
    def description(self) -> str:
        return ('操作這一段（run 與段落由程式帶入）。args 第一項是子指令：'
                '["config", "--set", "title=紅魔館", "--set", "items=[\\"甲\\",\\"乙\\"]"]、["show"]、'
                '["media", 槽名, 素材檔名, ("--cutout")]')

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                "required": ["args"]}

    def execute(self, args: Any = None, **_: Any) -> str:
        out = self._execute(args)
        try:
            ok = json.loads(out).get("ok", True)
        except (json.JSONDecodeError, AttributeError):
            ok = True
        self.fail_streak = 0 if ok else self.fail_streak + 1
        if not ok and self.fail_streak == 3 and self.on_stuck:  # 連續三次工具失敗也算卡住
            note = self.on_stuck(["tool_error"])
            if note:
                data = json.loads(out)
                data["next"] = note
                out = _trim(data)
        return out

    def _execute(self, args: Any = None) -> str:
        from src.tools.aam_cli_tool import AamCliTool
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = args.split()
        args = [str(a) for a in (args or [])]
        if len(args) == 1 and " " in args[0]:  # 整串指令放在一個字串裡（例如 "config --set title=紅魔館"）就拆開
            head, *flags = re.split(r"\s+(?=--[\w-])", args[0].strip())  # 只在 --旗標 前切，值裡的 JSON 不動
            args = head.split()
            for f in flags:
                name, _, val = f.partition(" ")
                args += [name] + ([val.strip()] if val.strip() else [])
        if not args or args[0] not in self.ALLOWED:
            return _trim({"ok": False, "error": f"只能用 {list(self.ALLOWED)}", "fix": '例如 ["show"]'})
        cmd, rest = args[0], args[1:]
        if cmd == "config":
            rest = self._merge_dotted(rest)
            if isinstance(rest, str):  # 合併失敗時回傳錯誤訊息
                return rest
            for i, a in enumerate(rest):  # 值寫成 JS 物件（鍵名沒加引號、用 = 當冒號）就自動轉成 JSON
                key, sep, val = a.partition("=")
                if sep and val.strip()[:1] in "[{":
                    fixed = _jsonify(val.strip())
                    if fixed is None:
                        return _trim({"ok": False, "error": f"{key} 的值不是合法 JSON",
                                      "fix": '鍵名和字串都要用雙引號，例如 items=[{"name":"早鬼","text":"組長"}]'})
                    rest[i] = f"{key}={fixed}"
            locked = sorted({a.split("=", 1)[0] for a in rest if "=" in a} & self.LOCKED)
            if locked:  # 秒數、排法由程式依企劃設定；改了會和素材張數對不上
                return _trim({"ok": False, "error": f"{locked} 由程式設定，不能改",
                              "fix": "只改文字欄位；清單項數要等於素材張數"})
            if rest == self._last_config:
                return _trim({"ok": False, "error": "和上一次的 config 完全一樣，沒有任何改變",
                              "fix": "截圖看起來沒問題就呼叫 seg_finish(passed=true)；有問題就改不同的內容"})
            self._last_config = list(rest)
            made_up = self.ungrounded(rest)
            if made_up:  # 字串比對就能判斷，不需要模型知道答案
                return _trim({"ok": False, "error": f"這些數字或英文名稱不在 brief 裡：{made_up}",
                              "fix": "只能用 brief 出現過的數字與名稱；沒有合適的就換成中文描述，或留空"})
            hits = sorted({w for a in rest for w in BANNED if w in a})
            if hits:  # 當場擋下，讓 Agent 自己換字，而不是事後改成保底卡
                return _trim({"ok": False, "error": f"不能用範例字：{hits}",
                              "fix": "換成這段自己的內容；結尾的動作字可用「追蹤」「收藏」「下次見」「一起逛」等"})
        if cmd == "media" and len(rest) >= 2 and "/" not in rest[1] and "\\" not in rest[1]:
            rest[1] = f"{self.media_dir}/{rest[1]}"
        return AamCliTool().execute(args=[cmd, self.run_id, self.seg_id, *rest])


# 自我檢查只問「只看畫面就能回答、不需要任何背景知識」的事；圖文對不對、內容合不合理交給真人確認
CHECKLIST = {
    "text_cut": "有文字超出畫面邊緣或被切掉",
    "overlap": "有文字和文字、或文字和圖片互相重疊蓋住",
    "empty_slot": "有該放圖卻沒有圖的框（灰色或白色的空方框）；純色塊、裝飾線條不算",
    "tiny_text": "有小到看不清楚的字",
    "person_cropped": "人物被切到看不見臉",
    "edge_artifact": "去背的人物邊緣有白邊、色塊或缺角",
    "comma_year": "畫面上有像 2,019 這種中間有逗號的年份",
    "leftover_words": "畫面上看得到這些字：" + "、".join(BANNED),
}
REVIEW_CHECKLIST = "檢查表（每項都看截圖回答有或沒有）：" + "；".join(f"{k}：{v}" for k, v in CHECKLIST.items())


class SegReviewTool(BaseTool):
    """截圖這一段，圖片直接給這段的 Agent 看（對話很短，自己看比另一個模型看更準）。"""

    def __init__(self, run_id: str, seg_id: str, shots: List[str]):
        self.run_id, self.seg_id, self.shots = run_id, seg_id, shots

    @property
    def name(self) -> str:
        return "seg_review"

    @property
    def description(self) -> str:
        return ("截圖這一段（段落中間的三個時間點，避開進場與退場動畫），下一則訊息會附上截圖讓你自己檢查。"
                + REVIEW_CHECKLIST)

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def execute(self, **_: Any) -> str:
        cfg = str(_run(["show", self.run_id, self.seg_id]).get("config", ""))
        m = re.search(r"duration:\s*([\d.]+)", cfg)
        dur = float(m.group(1)) if m else 7.0
        times = [round(dur * 0.35, 1), round(dur * 0.55, 1), round(dur * 0.75, 1)]  # 避開進場與退場動畫
        r = _run(["snap", self.run_id, self.seg_id, *[str(t) for t in times]], timeout=600)
        sheet = r.get("sheet")
        if not r.get("ok") or not sheet:
            return _trim({"ok": False, "error": r.get("error") or "截圖失敗", "fix": "再呼叫一次 seg_review"})
        self.shots.append(sheet)
        return _trim({"ok": True, "times": times, "attach_image": sheet,
                      "next": "看下一則訊息的截圖。沒問題就呼叫 seg_finish(passed=true)；有問題就改 config 再 seg_review。"})


class SegFinishTool(BaseTool):
    """這段 Agent 的結論：對固定檢查表逐項回答，程式依答案判定通過與否（不讓模型只回一句「通過」）。"""

    def __init__(self, verdict: Dict[str, Any], on_stuck: Optional[Callable[[List[str]], str]] = None,
                 stuck_after: int = 2):
        self.verdict = verdict
        self.on_stuck = on_stuck      # 同一段連續沒過時呼叫（例如改開思考），回傳要告訴 Agent 的話
        self.stuck_after = stuck_after
        self.fail_count = 0

    @property
    def name(self) -> str:
        return "seg_finish"

    @property
    def description(self) -> str:
        return ("這段做完時呼叫。checks 對檢查表每一項回答 true（截圖上看得到這個問題）或 false（看不到）。"
                + REVIEW_CHECKLIST)

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "checks": {"type": "object", "description": "每個檢查項目回答 true／false",
                       "properties": {k: {"type": "boolean", "description": v} for k, v in CHECKLIST.items()},
                       "required": list(CHECKLIST)},
            "summary": {"type": "string", "description": "一句話：這段放了什麼字"}},
            "required": ["checks", "summary"]}

    def execute(self, checks: Any = None, summary: str = "", **kw: Any) -> str:
        checks = checks if isinstance(checks, dict) else {}
        missing = [k for k in CHECKLIST if not isinstance(checks.get(k), bool)]
        if missing:
            return _trim({"ok": False, "error": f"檢查表沒填完：{missing}",
                          "fix": "checks 要包含每一項，值是 true 或 false"})
        failed = [k for k in CHECKLIST if checks[k]]
        self.verdict.update({"passed": not failed, "checks": checks, "failed": failed,
                             "issues": [CHECKLIST[k] for k in failed], "summary": str(summary)[:160]})
        if failed:
            self.fail_count += 1
            note = ""
            if self.on_stuck and self.fail_count == self.stuck_after:
                note = self.on_stuck(failed)
            return _trim({"ok": True, "passed": False, "failed": failed,
                          "next": (note + " " if note else "") +
                                  "還有問題：改 config 再 seg_review，修好後重新 seg_finish；已經修了 3 輪就直接結束。"})
        return _trim({"ok": True, "passed": True, "next": "已記錄。回覆一句話並在最後一行加 <?final>。"})


class SegmentedPipeline(Pipeline):
    def __init__(self, llm, vision, *, seg_llm_factory: Callable[[], LMWrapper], history: LocalChatHistory,
                 conversation_id: str, seg_max_steps: int = 14, seg_think_tokens: int = 2000,
                 seg_think_mode: str = "prompt", **kw: Any):
        super().__init__(llm, vision, history=history, conversation_id=conversation_id, **kw)
        self.seg_llm_factory = seg_llm_factory
        self.seg_max_steps = seg_max_steps
        self.seg_think_tokens = seg_think_tokens  # 卡住時改開思考的 token 上限；0 表示不開
        self.seg_think_mode = seg_think_mode      # prompt：用提示請模型寫 <think>；native：開伺服器的思考開關

    def seg_prompt(self, info: Dict[str, Any], seg: Dict[str, Any], done: List[Dict[str, Any]], total: int) -> str:
        fields = self.content_fields(seg["block"])
        req = self.required_count(seg)
        extra = f"\n- {req[0]} 要剛好 {req[1]} 項（對應 {req[1]} 張素材）" if req else ""
        prev = "\n".join(f"- {d['seg']}（{d['block']}）：{d['summary']}" for d in done[-4:]) or "（這是第一段）"
        return f"""## 題目 brief
{info['brief']}

## 你的段落：{seg['id']}（第 {int(seg['id'][4:])}/{total} 段）
骨架：{seg['block']}
口白：{seg['script']}
重點字：{', '.join(seg['key_text'])}
已放好的素材（槽名 → 檔名，順序固定）：
{chr(10).join(f"- {k} = {v}" for k, v in seg['slots'].items()) or '（無）'}
清單類欄位（captions、items…）的第 1 項對應第 1 個槽，依此類推；名字一定要對上圖。
（秒數與版面已由程式設定，不用改 duration、layout）

## 目前的 CONFIG（文字與數字都是範例，要換掉）
{seg.get('config', '')}

## 要填的欄位
{chr(10).join(f'- {n}：{f["hint"]}' for n, f in fields.items())}{extra}

## 前面幾段已完成（保持用詞一致，不要重複同一句）
{prev}

{fill_examples_text(seg['block'], info['topic'])}"""

    def run_segment_agent(self, run_id: str, info: Dict[str, Any], seg: Dict[str, Any],
                          done: List[Dict[str, Any]], total: int) -> Dict[str, Any]:
        sub_id = f"{self.conv}__{seg['id']}"
        self.step("segment_agent", {"seg": seg["id"], "block": seg["block"], "conversation": sub_id},
                  {"status": "started", "progress": f"{int(seg['id'][4:])}/{total}"})
        shots: List[str] = []
        verdict: Dict[str, Any] = {}
        tools = ToolExecutor()
        media_dir = f"{info['topic'].rstrip('/')}/media"
        llm = self.seg_llm_factory()

        def think_harder(failed: List[str]) -> str:
            """同一段第二次沒過：讓模型先想清楚再改（回覆上限 seg_think_tokens）。

            prompt 模式（預設）：用提示請模型把推理寫在 <think>…</think> 裡再呼叫工具；任何模型都能用
            （LMWrapper 會把 <think> 抽成思考過程，工作台照樣看得到）。
            native 模式：改開伺服器的思考開關（模型與伺服器要支援）。
            """
            backend = getattr(llm, "backend", None)
            opts = getattr(backend, "request_options", None)
            if opts is None or escalated:  # 一段只升級一次
                return ""
            escalated.append(True)
            opts["max_tokens"] = self.seg_think_tokens
            if self.seg_think_mode == "native":
                extra = dict(opts.get("extra_body") or {})
                extra.pop("reasoning_effort", None)
                extra.pop("chat_template_kwargs", None)
                if extra:
                    opts["extra_body"] = extra
                else:
                    opts.pop("extra_body", None)
            self.step("think_harder", {"seg": seg["id"], "failed": failed, "mode": self.seg_think_mode},
                      {"max_tokens": self.seg_think_tokens})
            problems ="、".join(CHECKLIST.get(k, "工具連續回報錯誤") for k in failed)
            if self.seg_think_mode == "native":
                return (f"已經卡住（{problems}）：接下來先想清楚再動手，"
                        "想想錯誤訊息要你改什麼、怎麼在字數上限內保留原意，或換一種寫法。")
            return (f"已經卡住（{problems}）。下一次回覆請先在 <think> 和 </think> 之間寫下推理（300 字以內）："
                    "錯誤訊息或截圖說了什麼、問題出在哪個欄位、有哪幾種改法、選哪一個；寫完再照平常的格式呼叫工具"
                    '（例如 seg(["config", "--set", "feature=龜殼龍角"])）。')

        escalated: List[bool] = []
        stuck = think_harder if self.seg_think_tokens else None
        cli = SegCliTool(run_id, seg["id"], media_dir, info["brief"])
        cli.on_stuck = stuck  # 連續三次工具失敗
        tools.register_tools([cli, SegReviewTool(run_id, seg["id"], shots),
                              SegFinishTool(verdict, on_stuck=stuck)])  # 檢查表第二次沒過
        llm.set_system_prompt(SEG_SYSTEM.format(banned="、".join(BANNED)))
        hist = LocalChatHistory(storage_directory="chat_history", memory_config={"retain_recent_messages": 100000})
        hist.create_conversation(sub_id)
        runtime = AgentRuntime(ChatSession(llm=llm, history_backend=hist, conversation_id=sub_id), tools,
                               # 每段的對話很短，不壓縮：壓縮會把錯誤訊息換成摘要，模型就看不到自己錯在哪
                               compression_config={"keep_recent_tool_messages": 1000, "compress_min_step": 1000},
                               runtime_options={"terse_steps": True, "drop_toolless_updates": True,
                                                "assistant_keep_full": 2, "stop_after_blocked_repeats": 3})
        t0 = time.time()
        try:
            answer = runtime.run(self.seg_prompt(info, seg, done, total), max_steps=self.seg_max_steps)
        except Exception as e:  # noqa: BLE001
            answer = f"段落 Agent 失敗：{type(e).__name__}: {e}"
        passed = bool(verdict.get("passed"))
        count_issue = self.count_mismatch(run_id, seg)
        if count_issue:
            passed = False
            verdict.setdefault("issues", []).append(count_issue)
        if not shots:
            review = "沒有做截圖檢查"
        elif passed:
            review = "PASS"
        else:
            review = "；".join(verdict.get("issues") or []) or "沒有呼叫 seg_finish"
        leftovers = self.leftover_samples(run_id, seg)
        result = {"seg": seg["id"], "block": seg["block"], "media": seg["slots"], "seconds": round(time.time() - t0),
                  "reviews": len(shots), "review": review,
                  "summary": verdict.get("summary") or re.sub(r"<\?final>", "", str(answer)).strip()[:160],
                  "checks": verdict.get("checks"), "conversation": sub_id,
                  "human_check": self.human_checklist(run_id, seg)}
        if leftovers:
            values = self.safe_segment(run_id, info, seg, f"範例值沒換掉：{leftovers}")
            result.update({"block": "pk-title-card", "review": f"保底：{leftovers} 沒換掉，改用標題卡",
                           "summary": f"保底標題卡：{values['lines']}"})
        self.step("segment_agent", {"seg": seg["id"]},
                  {"status": "done", "review": result["review"][:200], "seconds": result["seconds"]})
        return result

    def count_mismatch(self, run_id: str, seg: Dict[str, Any]) -> str:
        """清單項數要等於素材張數（不然會出現空框或沒有圖的說明）。純計數，不需要知識。"""
        req = self.required_count(seg)
        if not req:
            return ""
        chunk = _config_chunks(str(_run(["show", run_id, seg["id"]]).get("config") or "")).get(req[0], "")
        n = len(re.findall(r"\{", chunk)) or len(re.findall(r'"[^"]*"', chunk))
        return f"{req[0]} 有 {n} 項，但素材有 {req[1]} 張" if n and n != req[1] else ""

    def human_checklist(self, run_id: str, seg: Dict[str, Any]) -> List[str]:
        """需要背景知識才能判斷的事，列給真人確認。"""
        items = []
        texts = _config_chunks(str(_run(["show", run_id, seg["id"]]).get("config") or ""))
        shown = "；".join(f"{k}={v}" for k, v in texts.items() if k in self.content_fields(seg["block"]))[:200]
        if seg.get("slots"):
            items.append("圖和名字對得上：" + "、".join(f"{k}={v}" for k, v in seg["slots"].items()))
        if shown:
            items.append("文字內容正確、符合 brief：" + shown)
        items.append(f"骨架 {seg['block']} 適合這段內容")
        return items

    def leftover_samples(self, run_id: str, seg: Dict[str, Any]) -> List[str]:
        """這段的內容欄位還有沒有範例原文（和放骨架時的 CONFIG 一字不差）。"""
        before = _config_chunks(seg.get("config", ""))
        now = _config_chunks(str(_run(["show", run_id, seg["id"]]).get("config") or ""))
        return [n for n in self.content_fields(seg["block"]) if n in before and before[n] == now.get(n)]

    def run(self, topic: str) -> Dict[str, Any]:
        t0 = time.time()
        info = self.read_topic(topic)
        plan = self.plan(info)
        run_id, segs = self.build(info, plan)
        done: List[Dict[str, Any]] = []
        for seg in segs:
            done.append(self.run_segment_agent(run_id, info, seg, done, len(segs)))
        self.step("aam render", {"run_id": run_id}, _run(["render", run_id, "--wait"], timeout=3600))
        r2 = self.step("aam export", {"run_id": run_id},
                       _run(["export", run_id, "concat", "--transition", "fade"], timeout=1800))
        from src.tools.aam_tools import AAM_ROOT
        outs = [str(p) for d in (AAM_ROOT / "runs").glob(f"{run_id}*") for p in (d / "export").glob("*.mp4")]
        result = {"run_id": run_id, "video": outs[0] if outs else None, "theme": plan["theme"],
                  "theme_reason": plan.get("theme_reason"), "segments": done,
                  "seconds": round(time.time() - t0), "export_error": r2.get("error")}
        self._record({"role": "assistant", "content": _report_md(result) + "\n<?final>"})
        return result
