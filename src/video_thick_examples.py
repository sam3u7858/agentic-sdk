"""thick 版的範例：用範例取代模型的長思考。

- PLAN_EXAMPLE：一份合法企劃（虛構題目），讓模型照格式與規則直接寫。
- 填字範例庫：每次某骨架填字通過檢查，就把「這段的方向 → 填好的值」存起來；
  下次遇到同一骨架，附上最近的成功範例（其他題目），模型照格式填，不用自己推理。
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from src.tools.aam_tools import AAM_ROOT

STORE = AAM_ROOT / "temppad" / "agent_runs" / "fill_examples.json"
KEEP_PER_BLOCK = 3

PLAN_EXAMPLE_BRIEF = """# 主題：台灣夜市三大小吃（虛構範例）
- 士林夜市 1909 年開始形成。
- 臭豆腐：外酥內嫩，配台式泡菜。
- 大腸包小腸：糯米腸夾香腸。
- 珍珠奶茶：1980 年代出現。"""

PLAN_EXAMPLE = {
    "theme": "slash", "theme_reason": "照片多、顏色鮮豔，斜切版面有夜市的熱鬧感", "title": "night-market-snacks",
    "cutout": ["tofu.png", "sausage.png"],
    "segments": [
        {"block": "pk-title-card", "script": "夜市必吃的三樣小吃，一次看完。", "key_text": ["夜市", "必吃"],
         "media": ["night.jpg"], "duration": 7},
        {"block": "pk-big-stat", "script": "士林夜市從 1909 年就開始形成。", "key_text": ["1909", "士林"],
         "media": [], "duration": 7},
        {"block": "pk-media-grid", "script": "今天的主角有三位。", "key_text": ["三大", "小吃"],
         "media": ["tofu.png", "sausage.png", "tea.jpg"], "duration": 8},
        {"block": "pk-pal-card", "script": "第一名是外酥內嫩的臭豆腐。", "key_text": ["臭豆腐", "外酥"],
         "media": ["tofu.png"], "duration": 7},
        {"block": "pk-headline-card", "script": "大腸包小腸，用糯米腸夾住香腸。", "key_text": ["大腸包", "小腸"],
         "media": ["sausage.png"], "duration": 7},
        {"block": "pk-media-frame", "script": "珍珠奶茶在 1980 年代出現。", "key_text": ["珍奶", "1980"],
         "media": ["tea.jpg"], "duration": 7},
        {"block": "pk-album", "script": "逛一圈，三樣都吃到了。", "key_text": ["吃一圈"],
         "media": ["night.jpg", "tofu.png", "tea.jpg"], "duration": 8},
        {"block": "pk-outro-cta", "script": "下次逛夜市就照這個順序吃。", "key_text": ["去逛吧"],
         "media": ["tofu.png"], "duration": 6},
    ],
}


def plan_example_text() -> str:
    return ("## 範例（另一個題目，只參考格式與規則，內容不要照抄）\n"
            f"brief：\n{PLAN_EXAMPLE_BRIEF}\n素材：night.jpg, tofu.png, sausage.png, tea.jpg\n輸出：\n"
            + json.dumps(PLAN_EXAMPLE, ensure_ascii=False))


def _load() -> Dict[str, List[Dict[str, Any]]]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _topic_key(topic: str) -> str:
    return Path(str(topic)).name


def remember(block: str, seg: Dict[str, Any], values: Dict[str, Any], topic: str) -> None:
    data = _load()
    item = {"topic": _topic_key(topic), "script": seg.get("script"), "key_text": seg.get("key_text"),
            "media_count": len(seg.get("media") or []), "values": values}
    items = [x for x in data.get(block, []) if x.get("values") != values] + [item]
    data[block] = items[-KEEP_PER_BLOCK:]
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def fill_examples_text(block: str, topic: str, limit: int = 2) -> str:
    items = [x for x in _load().get(block, []) if x.get("topic") != _topic_key(topic)][-limit:]
    if not items:
        return ""
    lines = ["## 同一骨架的成功範例（其他題目，只參考格式、長度與欄位寫法，內容不要照抄）"]
    for x in items:
        if x.get("script"):
            lines.append(f"方向：{x['script']}｜重點字：{'、'.join(x.get('key_text') or [])}｜素材 {x['media_count']} 張")
        lines.append("輸出：" + json.dumps(x["values"], ensure_ascii=False))
    return "\n".join(lines)


def seed_from_history(history_dir: Path) -> int:
    """從過去 thick 執行的結果檔撈出「填字與截圖檢查都通過」的段落，當作初始範例。"""
    count = 0
    for f in sorted(set(history_dir.glob("*_thick_*.result.json"))):  # 舊名 video_thick_… 與新名 <日期-時間>_thick_… 都算
        rec = json.loads(f.read_text(encoding="utf-8"))
        for s in (rec.get("result") or {}).get("segments", []):
            if s.get("review") == "PASS" and s.get("text"):
                values = {k: v for k, v in s["text"].items() if k != "duration"}
                remember(s["block"], {"media": list((s.get("media") or {}).values())}, values, rec.get("topic", ""))
                count += 1
    return count
