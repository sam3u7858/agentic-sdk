"""用本 SDK 的 Agent（Gemma 4、Gemini…）跑 anim-thin 素材成片。

例：
  python run_video_thin.py --topic temppad/haiku_test/t01_eosd --provider local --model gemma-4-27b-it --url http://127.0.0.1:1234/v1
  python run_video_thin.py --topic temppad/haiku_test/t01_eosd                      # 預設 Gemini（GEMINI_KEY）
視覺檢查預設用同一個模型；可用 --vision-provider/--vision-model/--vision-url 另外指定（例如主模型無視覺能力時）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from src.agent_factory import configure_logging, create_agent_components
from src.ai_core.llm import LMWrapper, resolve_default_llm_api_key
from src.tools.aam_tools import make_aam_tools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True, help="題目資料夾（相對 AAM_ROOT），內含 brief.md 與 media/")
    ap.add_argument("--provider", default="gemini")
    ap.add_argument("--model", default=None)
    ap.add_argument("--url", default=None, help="OpenAI 相容服務網址（provider=local 時）")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--vision-provider", default=None)
    ap.add_argument("--vision-model", default=None)
    ap.add_argument("--vision-url", default=None)
    ap.add_argument("--max-steps", type=int, default=160)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--no-slim", dest="slim", action="store_false",
                    help="改回舊版：system_core 通用守則＋lookup_skill／manage_todo_list＋冗長步驟提示")
    a = ap.parse_args()
    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    key = a.api_key or ("local" if a.provider == "local" else None)
    conv = f"{time.strftime('%Y%m%d-%H%M%S')}_thin_{Path(a.topic).name}"
    if a.slim:
        skill = (Path(__file__).parent / "skills" / "anim_thin" / "instructions.md").read_text(encoding="utf-8")
        slim_kwargs = dict(
            enabled_tools=[], system_prompt_name="video_agent", system_prompt_vars={"skill": skill},
            runtime_options={"terse_steps": True, "drop_toolless_updates": True, "assistant_keep_full": 2},
        )
    else:
        slim_kwargs = dict(enabled_tools=["lookup_skill", "manage_todo_list"])
    comps = create_agent_components(
        conv, provider=a.provider, model=a.model, api_key=key, lm_api_url=a.url,
        request_options={"temperature": a.temperature}, enable_web_search_tool=False,
        compression_config={"keep_recent_tool_messages": 8}, **slim_kwargs,
        # 影片任務不封存歷史：送給模型的內容已由 runtime 壓縮；封存會把紀錄檔本身改成 [ARCHIVED_MESSAGE]，
        # 模型會看不到自己的企劃，工作台也看不到過程
        history_memory_config={"retain_recent_messages": 100000},
    )
    vp = a.vision_provider or a.provider
    import os
    main_model = a.model or os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    vision_key = (a.api_key or ("local" if vp == "local" else None)) if vp != "gemini" else resolve_default_llm_api_key("gemini", None)
    vision_llm = LMWrapper(provider=vp, model=a.vision_model or main_model, api_key=vision_key,
                           lm_api_url=a.vision_url or (a.url if vp == a.provider else None), request_options={"temperature": 0.1})
    vision_llm.set_system_prompt("你是嚴格的影片畫面檢查員，只回答被問的檢查項目，精簡條列。")

    def vision(img: bytes, prompt: str) -> str:
        try:
            return vision_llm.analyze_image_bytes(prompt=prompt, image_bytes=img, mime_type="image/jpeg")
        except Exception as e:  # noqa: BLE001
            return f"(vision failed: {e})"

    comps["tool_executor"].register_tools(make_aam_tools(vision))
    lead = "照技能做出影片。" if a.slim else "請先用 lookup_skill 載入 anim_thin，然後照它做出影片。"
    prompt = (f"{lead}題目資料夾：{a.topic}。"
              "全程不要詢問我，完成後回報：run_id、成片路徑、風格包與理由、每段骨架與主要文字、素材使用表、遇到的錯誤。")
    t0 = time.time()
    answer = comps["runtime"].run(prompt, max_steps=a.max_steps)
    rec = {"topic": a.topic, "slim": a.slim, "provider": a.provider, "model": a.model, "seconds": round(time.time() - t0),
           "conversation": conv, "answer": answer}
    Path("chat_history").mkdir(exist_ok=True)
    Path(f"chat_history/{conv}.result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(answer)


if __name__ == "__main__":
    main()
