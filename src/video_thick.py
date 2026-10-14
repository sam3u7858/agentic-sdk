"""thick 版影片流程：流程由程式固定，決定交給 Agent，該填的東西由程式保證填到。

給本地小模型（例如 Gemma 4）用。模型只在兩個節點被呼叫，每次都是乾淨的小 context：
  A. 企劃：選風格、排段落（骨架、口白、畫面文字、每段用哪些素材、要不要去背）
  B. 填字：把一段的 CONFIG 文字欄位填好
其餘（素材分析、建專案、寫分鏡、放骨架、放素材、規則檢查、截圖檢查、渲染、輸出、報告）都由程式做。
模型的輸出不符合規則時，程式把問題清單丟回去重寫，不會放行。
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.tools.aam_tools import AAM_ROOT, AamMediaSheetTool, AamSnapReviewTool, _run, _safe_rel
from src.video_thick_examples import fill_examples_text, plan_example_text, remember

logger = logging.getLogger(__name__)

BLOCKS_DIR = AAM_ROOT / "blocks"
THEME_HINTS = {
    "slash": "角色主色吵、照片多", "infographic": "資料、數字", "atelier": "高質感作品",
    "speckle": "安靜文青", "cosmos": "宇宙科技", "explore": "紀錄片、夜景", "chroma": "柔和情緒",
    "collage": "藝術人物、拼貼", "bauhaus": "幾何海報", "stellar": "科幻規格",
}
# 不是「內容」的欄位：版面、動畫、數字格式等設定，可以保留預設值
SETTING_FIELDS = {
    "duration", "decimals", "grouping", "hot", "layout", "enter", "browser", "outline", "winner", "perScene",
    "perNode", "perStage", "perTerm", "spacing", "position", "nameColor", "titleColor", "size", "enterAt",
    "zoom", "x", "y", "side", "axis", "axisMax", "track", "compare", "gap", "step", "widths", "focus",
    "highlight", "times",
}
# 數字型的內容欄位：數字一定要來自 brief
NUMERIC_CONTENT = {"value", "before", "after", "cost", "price", "stat", "likes", "result"}
# 素材數量由哪個清單欄位決定
COUNT_FIELD = {"pk-album": "captions", "pk-base-roster": "items", "pk-showcase": "items",
               "pk-stage-list": "stages", "pk-timeline-pan": "events", "pk-recipe-formula": "items"}
GRID_LAYOUT = {2: "2", 3: "3", 4: "4", 6: "3x2"}
CONTAIN_BLOCKS = {"pk-media-frame", "pk-site-mockup", "pk-map-pin"}  # 預設 cover，放人物圖會被裁
BANNED = ["帕魯", "金幣", "碎岩龜", "塑鋼", "弦月", "bmon", "訂閱", "挖礦", "原油", "傳奇"]
# 分鏡 schema 允許的 visual_type；骨架登錄檔可能有 schema 沒有的值（character、outro…）
VISUAL_TYPES = ("big_number", "comparison", "list", "process", "chart", "social", "title", "quote", "random")
CJK = re.compile(r"[㐀-鿿]")


# ---------- 骨架目錄 ----------

def _js_type(default: str) -> str:
    d = default.strip()
    if d.startswith('"') or d.startswith("'"):
        return "string"
    if d.startswith("["):
        return "array"
    if d.startswith("{"):
        return "object"
    if d in ("true", "false"):
        return "boolean"
    return "number"


def load_catalog() -> Dict[str, Dict[str, Any]]:
    cat = {}
    for f in sorted(BLOCKS_DIR.glob("pk-*/registry-item.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        slots = sorted((s["name"] for s in d.get("slots", [])), key=_slot_order)
        fields = {x["name"]: {"default": x.get("default", ""), "hint": x.get("hint", ""),
                              "type": _js_type(x.get("default", ""))} for x in d.get("fields", [])}
        cat[d["name"]] = {"use": (d.get("description") or "").split("外觀由")[0].strip("；，。 ")[:70],
                          "slots": slots, "fields": fields, "visual_type": next((v for v in d.get("visual_types") or [] if v in VISUAL_TYPES), "random")}
    return cat


def _slot_order(name: str) -> Tuple[int, str]:
    m = re.search(r"\d+", name)
    return (int(m.group()) if m else 99, name)


def slot_range(block: str, cat: Dict[str, Any]) -> Tuple[int, int]:
    n = len(cat[block]["slots"])
    if block == "pk-media-grid":
        return 2, 6
    if block in COUNT_FIELD:
        return (2 if block != "pk-recipe-formula" else 3), n
    return n, n


def catalog_text(cat: Dict[str, Any]) -> str:
    lines = []
    for name, b in cat.items():
        lo, hi = slot_range(name, cat)
        media = "不用素材" if hi == 0 else (f"素材 {lo} 張" if lo == hi else f"素材 {lo}–{hi} 張")
        if name == "pk-media-grid":
            media = "素材 2、3、4 或 6 張"
        if needs_numbers(name, cat):
            media += "，需要 brief 裡的數字"
        lines.append(f"- {name}（{media}）：{b['use']}")
    return "\n".join(lines)


NUMBER_BLOCKS = {"pk-big-stat", "pk-versus", "pk-price-drop", "pk-profit-ratio", "pk-equation", "pk-calc-chain",
                 "pk-column-chart", "pk-rank-bars", "pk-pie", "pk-stack-bar", "pk-map-pin", "pk-profile"}


def needs_numbers(block: str, cat: Dict[str, Any]) -> bool:
    return block in NUMBER_BLOCKS


# ---------- 呼叫模型 ----------

def extract_json(text: str) -> Any:
    text = re.sub(r"```(?:json)?", "", text or "")
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("回覆裡沒有 JSON")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            esc = (c == "\\") and not esc
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("JSON 沒有結束（括號不成對）")


class Pipeline:
    def __init__(self, llm, vision: Callable[[bytes, str], str], history=None, conversation_id: str = "",
                 max_fix_rounds: int = 3, fallback_llm=None):
        self.llm = llm
        self.fallback_llm = fallback_llm  # 主模型修不好時接手的強模型（可不設）
        self.vision = vision
        self.history = history
        self.conv = conversation_id
        self.max_fix = max_fix_rounds
        self.cat = load_catalog()
        self.log: List[str] = []
        self._call_n = 0

    # --- 對話紀錄（讓工作台 UI 看得到每一步與 Gemma 的思考） ---
    def _record(self, msg: Dict[str, Any]) -> None:
        if self.history:
            self.history.add_message(self.conv, msg)

    def step(self, name: str, args: Dict[str, Any], result: Any) -> Any:
        self._call_n += 1
        cid = f"prog_{self._call_n}"
        self._record({"role": "assistant", "content": "", "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]})
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        self._record({"role": "tool", "tool_call_id": cid, "name": name, "content": content[:6000]})
        return result

    def ask(self, prompt: str, label: str) -> Dict[str, Any]:
        """問模型一次，回傳解析後的 JSON；格式錯就把錯誤丟回去重問。"""
        msgs = [{"role": "user", "content": prompt}]
        self._record({"role": "user", "content": f"[{label}]\n{prompt}"})
        last_err = ""
        for attempt in range(self.max_fix):
            resp = self.llm.get_completion(msgs)
            self._record({**resp, "content": resp.get("content") or ""})
            try:
                return extract_json(resp.get("content", ""))
            except (ValueError, json.JSONDecodeError) as e:
                last_err = str(e)
                msgs += [{"role": "assistant", "content": resp.get("content", "")},
                         {"role": "user", "content": f"上一個回覆的 JSON 無法解析：{e}。只輸出一個 JSON，不要其他文字。"}]
        raise RuntimeError(f"{label}：模型連續 {self.max_fix} 次沒有給出合法 JSON（{last_err}）")

    def ask_valid(self, prompt: str, label: str, validate: Callable[[Any], List[str]],
                  repair: Optional[Callable[[Any], List[str]]] = None) -> Any:
        """問模型 → 程式檢查 → 不過就帶著問題清單重問，直到通過或用完次數。"""
        current = prompt
        for attempt in range(self.max_fix):
            out = self.ask(current, label if attempt == 0 else f"{label}（第 {attempt + 1} 次）")
            if repair:
                fixed = repair(out)
                if fixed:
                    self.step("repair_" + label, {"attempt": attempt + 1}, {"fixed": fixed})
            problems = validate(out)
            self.step("check_" + label, {"attempt": attempt + 1}, {"ok": not problems, "problems": problems})
            if not problems:
                return out
            current = (prompt + "\n\n## 你上一次的輸出\n" + json.dumps(out, ensure_ascii=False) +
                       "\n\n## 程式檢查沒過，請只修正這些問題後輸出完整 JSON\n- " + "\n- ".join(problems))
        raise RuntimeError(f"{label}：{self.max_fix} 次仍未通過檢查：{problems}")

    # ---------- 1. 素材與事實（程式） ----------

    def read_topic(self, topic: str) -> Dict[str, Any]:
        d = _safe_rel(topic)
        brief = (d / "brief.md").read_text(encoding="utf-8")
        media = sorted(p.name for p in (d / "media").glob("*") if p.is_file())
        sheet = json.loads(AamMediaSheetTool(self.vision).execute(media_dir=f"{topic.rstrip('/')}/media"))
        alpha = self._alpha_map(d / "media", media)
        info = {"topic": topic, "brief": brief, "media": media, "media_notes": sheet.get("descriptions", []),
                "transparent": [m for m in media if alpha.get(m)]}
        return self.step("read_topic", {"topic": topic}, info)

    @staticmethod
    def _alpha_map(media_dir: Path, names: List[str]) -> Dict[str, bool]:
        code = ("import sys,json;from PIL import Image;r={}\n"
                "for p in sys.argv[1:]:\n"
                "  try:\n    im=Image.open(p);r[p.split('\\\\')[-1].split('/')[-1]]=im.mode in('RGBA','LA') and im.getextrema()[-1][0]<250\n"
                "  except Exception: pass\nprint(json.dumps(r))")
        import subprocess
        from src.tools.aam_tools import AAM_PYTHON
        paths = [str(media_dir / n) for n in names if n.lower().endswith((".png", ".webp"))]
        if not paths:
            return {}
        p = subprocess.run([AAM_PYTHON, "-X", "utf8", "-c", code, *paths], capture_output=True, text=True,
                           encoding="utf-8")
        try:
            return json.loads(p.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return {}

    # ---------- 2. 企劃（Agent 決定） ----------

    def plan(self, info: Dict[str, Any]) -> Dict[str, Any]:
        themes = "\n".join(f"- {k}：{v}" for k, v in THEME_HINTS.items())
        notes = "\n".join(info["media_notes"]) or "（無）"
        prompt = f"""你要企劃一支 16:9 動畫短片。所有決定由你做，程式會照你的企劃製作。

## 題目 brief（畫面上的名字、年份、數字只能來自這裡）
{info['brief']}

## 素材（{len(info['media'])} 張，每張至少用一次）
檔名：{', '.join(info['media'])}
已經是透明背景：{', '.join(info['transparent']) or '（無）'}
看圖描述：
{notes}

## 風格（全片選一個）
{themes}

## 可用骨架
{catalog_text(self.cat)}

## 規則
- 8–12 段；第一段 pk-title-card，最後一段 pk-outro-cta；至少 6 種骨架；同一骨架不要連續 3 段。
- 每段一個概念；script 是一句口白；key_text 1–4 項、每項最多 5 個字。
- media 依骨架需要的張數給檔名清單（順序就是素材槽順序；不用素材的骨架給 []）。人物圖要對到正確的人。
- cutout：需要去背的檔名清單（單色底的人物插圖；照片、截圖、透明背景的不要）。
- duration 6–12 秒。title 用英文小寫與連字號。

{plan_example_text()}

## 只輸出這個題目的 JSON（格式同範例），不要說明、不要思考過程"""
        return self.ask_valid(prompt, "plan", lambda p: self.check_plan(p, info),
                              repair=lambda p: self.repair_plan(p, info))

    def repair_plan(self, p: Any, info: Dict[str, Any]) -> List[str]:
        """機械性的小錯由程式直接修，不再問模型：沒用到的素材塞進還有空位的段落。"""
        if not isinstance(p, dict) or not isinstance(p.get("segments"), list):
            return []
        fixed = []
        # 骨架名稱打錯（底線、大小寫、少了 pk-）：對到最接近的正確名稱
        import difflib
        for i, s in enumerate(p["segments"], 1):
            if isinstance(s, dict) and s.get("block") not in self.cat and s.get("block"):
                raw = str(s["block"]).strip().lower().replace("_", "-")
                raw = raw if raw.startswith("pk-") else "pk-" + raw
                guess = raw if raw in self.cat else next(iter(difflib.get_close_matches(raw, self.cat, n=1, cutoff=0.8)), None)
                if guess:
                    fixed.append(f"第 {i} 段骨架 {s['block']} → {guess}")
                    s["block"] = guess
        segs = [s for s in p["segments"] if isinstance(s, dict) and s.get("block") in self.cat]
        used = {m for s in segs for m in s.get("media") or []}
        # 重點字超過 5 字：先去空白；還太長就丟掉（至少留一項，只剩長的就截斷）；空的就從口白取
        for i, s in enumerate(p["segments"], 1):
            if not isinstance(s, dict):
                continue
            kt = [str(k).replace(" ", "") for k in (s.get("key_text") or []) if str(k).strip()]
            if not kt:
                words = re.findall(r"[㐀-鿿]{2,5}", str(s.get("script", "")))
                kt = words[:2] or ["…"]
            keep = [k for k in kt if len(k) <= 5] or ([kt[0][:5]] if kt else [])
            if keep[:4] != s.get("key_text"):
                fixed.append(f"第 {i} 段重點字 {s.get('key_text')} → {keep[:4]}")
                s["key_text"] = keep[:4]
        for name in [m for m in info["media"] if m not in used]:
            for s in segs:
                b, media = s["block"], list(s.get("media") or [])
                lo, hi = slot_range(b, self.cat)
                if b == "pk-media-grid":
                    ok = len(media) + 1 in GRID_LAYOUT
                elif b == "pk-recipe-formula":
                    ok = False  # 最後一張是成品，不亂插
                else:
                    ok = lo != hi and len(media) < hi
                if ok:
                    s["media"] = media + [name]
                    fixed.append(f"{name} → {b}")
                    break
            else:
                # 沒有可加的段落：換掉某個「素材在別段也出現過」的單張素材段
                counts = {m: sum(m in (x.get("media") or []) for x in segs) for m in used}
                for s in segs:
                    media = list(s.get("media") or [])
                    dup = [i for i, m in enumerate(media) if counts.get(m, 0) > 1]
                    if dup:
                        old = media[dup[0]]
                        media[dup[0]] = name
                        s["media"] = media
                        counts[old] -= 1
                        fixed.append(f"{name} 取代 {s['block']} 裡重複的 {old}")
                        break
        return fixed

    def check_plan(self, p: Any, info: Dict[str, Any]) -> List[str]:
        if not isinstance(p, dict) or not isinstance(p.get("segments"), list):
            return ["要有 segments 陣列"]
        probs: List[str] = []
        if p.get("theme") not in THEME_HINTS:
            probs.append(f"theme 要是其中之一：{list(THEME_HINTS)}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", str(p.get("title", ""))):
            probs.append("title 只能英文小寫、數字、連字號")
        segs = p["segments"]
        if not 8 <= len(segs) <= 12:
            probs.append(f"現在 {len(segs)} 段，要 8–12 段")
        blocks = [s.get("block") for s in segs]
        unknown = [b for b in blocks if b not in self.cat]
        if unknown:
            probs.append(f"沒有這些骨架：{unknown}")
        if blocks and blocks[0] != "pk-title-card":
            probs.append("第一段要 pk-title-card")
        if blocks and blocks[-1] != "pk-outro-cta":
            probs.append("最後一段要 pk-outro-cta")
        if len(set(blocks)) < 6:
            probs.append(f"只有 {len(set(blocks))} 種骨架，至少 6 種")
        for i in range(len(blocks) - 2):
            if blocks[i] == blocks[i + 1] == blocks[i + 2]:
                probs.append(f"第 {i + 1}–{i + 3} 段都是 {blocks[i]}")
        used = set()
        for i, s in enumerate(segs, 1):
            b = s.get("block")
            kt = s.get("key_text") or []
            if not (1 <= len(kt) <= 4) or any(len(str(k)) > 5 for k in kt):
                probs.append(f"第 {i} 段 key_text 要 1–4 項、每項 ≤5 字：{kt}")
            if not str(s.get("script", "")).strip():
                probs.append(f"第 {i} 段缺 script")
            try:
                dur = float(s.get("duration", 0))
            except (TypeError, ValueError):
                dur = 0
            if not 6 <= dur <= 12:
                probs.append(f"第 {i} 段 duration 要 6–12")
            media = s.get("media") or []
            bad = [m for m in media if m not in info["media"]]
            if bad:
                probs.append(f"第 {i} 段用了不存在的素材：{bad}")
            used.update(media)
            if b in self.cat:
                lo, hi = slot_range(b, self.cat)
                ok = len(media) in GRID_LAYOUT if b == "pk-media-grid" else lo <= len(media) <= hi
                if not ok:
                    need = "2、3、4 或 6" if b == "pk-media-grid" else (f"{lo}" if lo == hi else f"{lo}–{hi}")
                    probs.append(f"第 {i} 段 {b} 要 {need} 張素材，現在 {len(media)} 張")
        unused = [m for m in info["media"] if m not in used]
        if unused:
            probs.append(f"這些素材沒用到：{unused}")
        bad_cut = [c for c in p.get("cutout") or [] if c not in info["media"]]
        if bad_cut:
            probs.append(f"cutout 裡有不存在的檔名：{bad_cut}")
        return probs

    # ---------- 3. 建專案、分鏡、放骨架與素材（程式） ----------

    def build(self, info: Dict[str, Any], plan: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
        script = "\n".join(s["script"] for s in plan["segments"])
        sf = AAM_ROOT / "temppad" / "agent_runs" / f"{plan['title']}_script.txt"
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(script, encoding="utf-8")
        r = self.step("aam create", {"title": plan["title"], "theme": plan["theme"]},
                      _run(["create", "--title", plan["title"], "--theme", plan["theme"], "--script-file", str(sf)]))
        if not r.get("ok"):
            raise RuntimeError(f"create 失敗：{r.get('error')}")
        run_id = r["run_id"]
        media_dir = _safe_rel(info["topic"]) / "media"
        storyboard, segs = [], []
        for i, s in enumerate(plan["segments"], 1):
            sid = f"seg_{i:02d}"
            b = s["block"]
            storyboard.append({"id": sid, "script": s["script"], "key_text": s["key_text"],
                               "visual_type": self.cat[b]["visual_type"], "duration_sec": float(s["duration"]),
                               "block_hint": b})
            slots = self.cat[b]["slots"]
            if b == "pk-recipe-formula":  # 最後一張是成品
                media = s["media"]
                assign = dict(zip(slots[:len(media) - 1], media[:-1]))
                assign["product"] = media[-1]
            else:
                assign = dict(zip(slots, s["media"]))
            segs.append({"id": sid, **s, "slots": assign})
        sb = AAM_ROOT / "temppad" / "agent_runs" / f"{run_id}_storyboard.json"
        sb.write_text(json.dumps(storyboard, ensure_ascii=False, indent=1), encoding="utf-8")
        r = self.step("aam storyboard", {"run_id": run_id, "segments": len(storyboard)},
                      _run(["storyboard", run_id, str(sb)]))
        if not r.get("ok"):
            raise RuntimeError(f"storyboard 失敗：{r.get('errors') or r.get('error')}")
        cut = set(plan.get("cutout") or [])
        for s in segs:
            r = self.step("aam add", {"seg": s["id"], "block": s["block"]}, _run(["add", run_id, s["id"], s["block"]]))
            if not r.get("ok"):
                raise RuntimeError(f"add {s['id']} 失敗：{r.get('error')}")
            s["config"] = str(r.get("config") or "")
            self.apply_settings(run_id, s)
            for slot, name in s["slots"].items():
                args = ["media", run_id, s["id"], slot, str(media_dir / name)]
                if name in cut:
                    args.append("--cutout")
                if s["block"] in CONTAIN_BLOCKS and (name in cut or name in info.get("transparent", [])):
                    args += ["--fit", "contain"]  # 人物插圖放進大框時不要裁成局部
                r = self.step("aam media", {"seg": s["id"], "slot": slot, "file": name, "cutout": name in cut},
                              _run(args, timeout=600))
                if not r.get("ok"):
                    raise RuntimeError(f"media {s['id']}/{slot} 失敗：{r.get('error')}")
        return run_id, segs

    # ---------- 4. 填字（Agent 決定，程式保證填滿） ----------

    def content_fields(self, block: str) -> Dict[str, Dict[str, Any]]:
        out = {}
        for name, f in self.cat[block]["fields"].items():
            if name in SETTING_FIELDS:
                continue
            if CJK.search(f["default"]) or name in NUMERIC_CONTENT or f["type"] in ("array", "object") \
                    or any(w.lower() in f["default"].lower() for w in BANNED):
                out[name] = f
        return out

    def required_count(self, seg: Dict[str, Any]) -> Optional[Tuple[str, int]]:
        b = seg["block"]
        if b in COUNT_FIELD:
            n = len(seg["media"]) - (1 if b == "pk-recipe-formula" else 0)
            return COUNT_FIELD[b], n
        if b == "pk-media-grid":
            return "captions", len(seg["media"])
        return None

    def fill(self, info: Dict[str, Any], seg: Dict[str, Any], feedback: str = "") -> Dict[str, Any]:
        fields = self.content_fields(seg["block"])
        req = self.required_count(seg)
        spec = "\n".join(f"- {n}（{f['type']}）：{f['hint']}" for n, f in fields.items())
        extra = f"\n- {req[0]} 一定要剛好 {req[1]} 項（對應 {req[1]} 張素材：{', '.join(seg['media'])}）" if req else ""
        prompt = f"""幫影片的一段填畫面文字。這段的方向已經決定，你決定具體寫法。

## 題目 brief（名字、年份、數字只能來自這裡）
{info['brief']}

## 這一段
骨架：{seg['block']}
口白：{seg['script']}
重點字：{', '.join(seg['key_text'])}
素材（依序）：{', '.join(seg['media']) or '（無）'}

## 骨架目前的 CONFIG（裡面的文字與數字都是範例，要換成這段的內容）
{seg.get('config', '')}

## 要填的欄位（全部都要填，範例值一個都不能留）
{spec}{extra}
- 字數照提示的上限；數字只能用 brief 裡出現過的；不要出現 {('、'.join(BANNED))}。
{('## 截圖檢查發現的問題（這次要修正）' + chr(10) + feedback) if feedback else ''}
{fill_examples_text(seg['block'], info['topic'])}
## 只輸出 JSON：{{"欄位名": 值, ...}}，值的型別要跟範例一樣（物件的鍵名也要一樣），不要說明"""
        return self.ask_valid(prompt, f"fill_{seg['id']}", lambda v: self.check_fill(v, seg, info))

    def check_fill(self, v: Any, seg: Dict[str, Any], info: Dict[str, Any]) -> List[str]:
        if not isinstance(v, dict):
            return ["要輸出一個物件 {欄位: 值}"]
        fields = self.content_fields(seg["block"])
        probs = []
        missing = [n for n in fields if n not in v]
        if missing:
            probs.append(f"缺少欄位：{missing}")
        unknown = [n for n in v if n not in self.cat[seg["block"]]["fields"]]
        if unknown:
            probs.append(f"沒有這些欄位：{unknown}")
        brief = info["brief"]
        chunks = _config_chunks(seg.get("config", ""))
        for n, val in v.items():
            f = self.cat[seg["block"]]["fields"].get(n)
            if not f or n not in fields:  # 版面、動畫等設定欄位不檢查內容
                continue
            sample = chunks.get(n) or f["default"]
            t = {str: "string", list: "array", dict: "object", bool: "boolean", int: "number", float: "number"}.get(type(val))
            if t != f["type"]:
                probs.append(f"{n} 要是 {f['type']}，現在是 {t}")
                continue
            if json.dumps(val, ensure_ascii=False).replace(" ", "") == \
                    re.sub(r"(\w+)\s*:", r'"\1":', sample).replace(" ", "").replace("\n", ""):
                probs.append(f"{n} 還是範例值，要換掉")
            m = re.search(r"(\d+)\s*字以內|(\d+)[–-](\d+)\s*字", f["hint"])
            limit = int(m.group(1) or m.group(3)) if m else None
            for s in _strings(val):
                if limit and len(s) > limit:
                    probs.append(f"{n} 的「{s}」超過 {limit} 字")
                hit = [w for w in BANNED + _sample_words(sample)
                       if w and w in s and w not in brief and w not in self.cat[seg["block"]]["fields"]]
                if hit:
                    probs.append(f"{n} 留著範例字 {hit}")
            for num in _numbers(val):
                if num >= 2 and not _num_in_brief(num, brief):
                    probs.append(f"{n} 的數字 {num:g} 不在 brief 裡（只能用 brief 的數字）")
        if (req := self.required_count(seg)) and isinstance(v.get(req[0]), list) and len(v[req[0]]) != req[1]:
            probs.append(f"{req[0]} 要剛好 {req[1]} 項，現在 {len(v[req[0]])} 項")
        return probs

    def settings_for(self, seg: Dict[str, Any]) -> Dict[str, Any]:
        """由程式決定、不經模型的設定：秒數、圖格排法。放骨架時就套用，填字失敗也不會漏掉。"""
        out: Dict[str, Any] = {"duration": float(seg["duration"])}
        if seg["block"] == "pk-media-grid":
            out["layout"] = GRID_LAYOUT[len(seg["media"])]
        return out

    def apply_settings(self, run_id: str, seg: Dict[str, Any]) -> None:
        args = ["config", run_id, seg["id"]]
        for k, val in self.settings_for(seg).items():
            args += ["--set", f"{k}={json.dumps(val, ensure_ascii=False)}"]
        self.step("aam config（設定）", {"seg": seg["id"], "set": self.settings_for(seg)}, _run(args))

    def apply_fill(self, run_id: str, seg: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
        values = {**dict(values), **self.settings_for(seg)}
        args = ["config", run_id, seg["id"]]
        for k, val in values.items():
            args += ["--set", f"{k}={json.dumps(val, ensure_ascii=False)}"]
        r = self.step("aam config", {"seg": seg["id"], "set": values}, _run(args))
        lint = (r.get("errors") or []) + ((r.get("style") or {}).get("violations") or [])
        return {"ok": r.get("ok", False) and not lint, "lint": lint, "error": r.get("error")}

    # ---------- 4b. 填字失敗的保底（保證不留範本原文） ----------

    def fill_with_fallback(self, info: Dict[str, Any], seg: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.fill(info, seg)
        except RuntimeError as first:
            if not self.fallback_llm:
                raise
            self.step("escalate", {"seg": seg["id"], "to": "fallback_llm"}, {"reason": str(first)[:300]})
            main, self.llm = self.llm, self.fallback_llm
            try:
                return self.fill(info, seg)
            finally:
                self.llm = main

    def safe_segment(self, run_id: str, info: Dict[str, Any], seg: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """主模型與備援都填不好：整段換成標題卡，文字全部由程式從企劃的重點字產生。"""
        clean = [str(k)[:7] for k in (seg.get("key_text") or []) if not any(w in str(k) for w in BANNED)]
        lines = clean[:2] or [str(info.get("title_hint") or "…")]
        hero = (seg.get("media") or info["media"])[0]
        seg.update({"block": "pk-title-card", "media": [hero], "slots": {"hero": hero}})
        self.step("safe_segment", {"seg": seg["id"], "reason": reason[:300]}, {"block": "pk-title-card", "lines": lines})
        r = _run(["add", run_id, seg["id"], "pk-title-card"])
        if not r.get("ok"):
            raise RuntimeError(f"保底骨架安裝失敗：{r.get('error')}")
        seg["config"] = str(r.get("config") or "")
        media_dir = _safe_rel(info["topic"]) / "media"
        self.step("aam media", {"seg": seg["id"], "slot": "hero", "file": hero},
                  _run(["media", run_id, seg["id"], "hero", str(media_dir / hero)], timeout=600))
        values = {"lines": lines, "hot": len(lines) - 1}
        self.apply_fill(run_id, seg, values)
        return values

    # ---------- 5. 截圖檢查（程式強制，每段都做） ----------

    def review(self, run_id: str, seg: Dict[str, Any]) -> str:
        r = json.loads(AamSnapReviewTool(self.vision).execute(run_id=run_id, seg_id=seg["id"]))
        self.step("snap_review", {"seg": seg["id"]}, r)
        text = str(r.get("review") or r.get("error") or "")
        return "" if re.fullmatch(r"\W*PASS\W*", text.strip(), re.I) or not r.get("ok") else text

    # ---------- 6. 主流程 ----------

    def run(self, topic: str) -> Dict[str, Any]:
        t0 = time.time()
        info = self.read_topic(topic)
        plan = self.plan(info)
        run_id, segs = self.build(info, plan)
        report = []
        for seg in segs:
            try:
                values = self.fill_with_fallback(info, seg)
            except RuntimeError as e:
                values = self.safe_segment(run_id, info, seg, str(e))
                report.append({"seg": seg["id"], "block": seg["block"], "text": values, "media": seg["slots"],
                               "review": f"保底：填字失敗，改用標題卡（{str(e)[:80]}）"})
                continue
            res = self.apply_fill(run_id, seg, values)
            try:
                if not res["ok"]:
                    values = self.fill(info, seg, feedback=f"lint：{res['lint'] or res['error']}")
                    res = self.apply_fill(run_id, seg, values)
                issues = self.review(run_id, seg)
                if issues:
                    values = self.fill(info, seg, feedback=issues)
                    self.apply_fill(run_id, seg, values)
                    issues = self.review(run_id, seg)
            except RuntimeError as e:
                issues = f"修正失敗：{e}"
            if not issues:  # 填字與截圖檢查都通過才收進範例庫
                remember(seg["block"], seg, {k: v for k, v in values.items() if k != "duration"}, info["topic"])
            report.append({"seg": seg["id"], "block": seg["block"], "text": values, "media": seg["slots"],
                           "review": issues or "PASS"})
        r1 = self.step("aam render", {"run_id": run_id}, _run(["render", run_id, "--wait"], timeout=3600))
        r2 = self.step("aam export", {"run_id": run_id},
                       _run(["export", run_id, "concat", "--transition", "fade"], timeout=1800))
        outs = [str(p) for d in (AAM_ROOT / "runs").glob(f"{run_id}*") for p in (d / "export").glob("*.mp4")]
        result = {"run_id": run_id, "video": outs[0] if outs else None, "theme": plan["theme"],
                  "theme_reason": plan.get("theme_reason"), "segments": report,
                  "seconds": round(time.time() - t0), "render_ok": bool(outs), "export_error": r2.get("error")}
        self._record({"role": "assistant", "content": _report_md(result) + "\n<?final>"})
        return result


def _strings(v: Any) -> List[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    return []


def _numbers(v: Any) -> List[float]:
    if isinstance(v, bool):
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    if isinstance(v, str):
        return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", v)]
    if isinstance(v, list):
        return [n for x in v for n in _numbers(x)]
    if isinstance(v, dict):
        return [n for x in v.values() for n in _numbers(x)]
    return []


def _num_in_brief(num: float, brief: str) -> bool:
    s = f"{num:g}"
    return s in brief.replace(",", "")


def _config_chunks(cfg: str) -> Dict[str, str]:
    """把 CONFIG 文字切成「最外層欄位 → 該欄位的範例值文字」（去掉註解）。"""
    body = _strip_comments(cfg)
    if "{" not in body:
        return {}
    body = body[body.index("{") + 1: body.rindex("}") if "}" in body else len(body)]
    keys = [(m.start(), m.group(1), len(m.group(0)) - len(m.group(0).lstrip()))
            for m in re.finditer(r"^[ \t]*(\w+)\s*:", body, re.M)]
    if not keys:
        return {}
    top = min(ind for _, _, ind in keys)
    keys = [(pos, name) for pos, name, ind in keys if ind == top]
    out = {}
    for i, (pos, name) in enumerate(keys):
        end = keys[i + 1][0] if i + 1 < len(keys) else len(body)
        out[name] = body[pos:end].split(":", 1)[1].strip().rstrip(",").strip()
    return out


def _strip_comments(cfg: str) -> str:
    return re.sub(r"//[^\n]*", "", cfg)


def _sample_words(default: str) -> List[str]:
    return [w for w in re.findall(r"[㐀-鿿]{2,}|[A-Za-z]{4,}", default)]


def _report_md(r: Dict[str, Any]) -> str:
    lines = [f"**run_id**：`{r['run_id']}`", f"**成片**：`{r['video']}`",
             f"**風格**：{r['theme']}（{r.get('theme_reason') or ''}）", f"**耗時**：{r['seconds']} 秒", "", "| 段 | 骨架 | 素材 | 截圖檢查 |",
             "|---|---|---|---|"]
    for s in r["segments"]:
        media = "、".join(s["media"].values()) or "—"
        rv = "PASS" if s["review"] == "PASS" else "⚠️ " + s["review"][:60].replace("\n", " ")
        lines.append(f"| {s['seg']} | {s['block']} | {media} | {rv} |")
    return "\n".join(lines)
