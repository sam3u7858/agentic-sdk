"""thick 版：流程由程式固定，Agent 只做企劃與填字（給本地小模型用）。

例：
  python run_video_thick.py --topic temppad/haiku_test/t01_eosd --provider local --model gemma4-26b-a4b-uncensored-hauhaucs-balanced --url http://127.0.0.1:1234/v1
對話紀錄寫在 chat_history/video_thick_<題目>_<時間>.json，工作台 UI 可以即時看（含模型思考過程）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from src.agent_factory import configure_logging
from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper
from src.video_thick import Pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--provider", default="local")
    ap.add_argument("--model", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--api-key", default="local")
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument("--reasoning", choices=["off", "on"], default="off",
                    help="thick 版預設關閉思考：每次呼叫的輸出都是範例格式的 JSON，思考 token 對品質幫助很小")
    ap.add_argument("--no-think-body", default='{"chat_template_kwargs": {"enable_thinking": false}}',
                    help="關閉思考時附加到請求的 extra_body（JSON）；不同服務的開關不同，可自行調整")
    ap.add_argument("--max-tokens", type=int, default=3000, help="每次回覆的上限，防止思考或輸出失控")
    ap.add_argument("--fallback-provider", default=None, help="主模型修不好時接手的模型：gemini／openai／local…")
    ap.add_argument("--fallback-model", default=None)
    ap.add_argument("--fallback-url", default=None)
    ap.add_argument("--fallback-api-key", default=None)
    a = ap.parse_args()
    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    opts = {"temperature": a.temperature, "max_tokens": a.max_tokens}
    if a.reasoning == "off" and a.no_think_body.strip():
        opts["extra_body"] = json.loads(a.no_think_body)
    llm = LMWrapper(provider=a.provider, model=a.model, api_key=a.api_key, lm_api_url=a.url,
                    request_options=opts)
    llm.set_system_prompt("你是影片企劃與文案。只輸出要求的 JSON，不要其他文字。所有名字、年份、數字只能來自題目 brief。")
    vision_llm = LMWrapper(provider=a.provider, model=a.model, api_key=a.api_key, lm_api_url=a.url,
                           request_options={**opts, "temperature": 0.1})

    def vision(img: bytes, prompt: str) -> str:
        try:
            return vision_llm.analyze_image_bytes(prompt=prompt, image_bytes=img, mime_type="image/jpeg",
                                                  system_prompt="你是嚴格的影片畫面檢查員，只回答被問的檢查項目，精簡條列。")
        except Exception as e:  # noqa: BLE001
            return f"(vision failed: {e})"

    conv = f"{time.strftime('%Y%m%d-%H%M%S')}_thick_{Path(a.topic).name}"
    history = LocalChatHistory(storage_directory="chat_history", memory_config={"retain_recent_messages": 100000})
    history.create_conversation(conv)
    history.add_message(conv, {"role": "user", "content": f"thick 流程：{a.topic}（模型 {a.model}）"})
    fallback = None
    if a.fallback_model:
        fp = a.fallback_provider or a.provider
        fkey = a.fallback_api_key or ("local" if fp == "local" else None)
        if fp == "gemini" and not fkey:
            from src.ai_core.llm import resolve_default_llm_api_key
            fkey = resolve_default_llm_api_key("gemini", None)
        fallback = LMWrapper(provider=fp, model=a.fallback_model, api_key=fkey, lm_api_url=a.fallback_url,
                             request_options={"temperature": a.temperature})
        fallback.set_system_prompt(llm.system_prompt if hasattr(llm, "system_prompt") else "")
    pipe = Pipeline(llm, vision, history=history, conversation_id=conv, fallback_llm=fallback)
    t0 = time.time()
    try:
        result = pipe.run(a.topic)
    except Exception as e:  # noqa: BLE001
        result = {"error": str(e)}
        history.add_message(conv, {"role": "assistant", "content": f"流程中止：{e}\n<?final>"})
    rec = {"mode": "thick", "topic": a.topic, "model": a.model, "seconds": round(time.time() - t0),
           "conversation": conv, "result": result}
    Path(f"chat_history/{conv}.result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
