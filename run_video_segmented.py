"""分段 Agent 版：企劃 Agent 寫分鏡，再讓每一段一個 Agent 依序做完。

例：
  python run_video_segmented.py --topic temppad/haiku_test/t02_newchars --model qwen/qwen3.8-27b --url http://<LM Studio 主機>:1234/v1
工作台：主對話 <日期-時間>_seg_<題目>，每段的子對話 <主對話>__seg_03。
"""
import argparse
import json
import sys
import time
from pathlib import Path

from src.agent_factory import configure_logging
from src.ai_core.history import LocalChatHistory
from src.ai_core.llm import LMWrapper
from src.video_segmented import SegmentedPipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--provider", default="local")
    ap.add_argument("--model", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--api-key", default="local")
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument("--plan-reasoning", choices=["on", "off"], default="on", help="企劃要不要開思考（只呼叫一次）")
    ap.add_argument("--seg-reasoning", choices=["on", "off"], default="off", help="每段 Agent 要不要開思考")
    ap.add_argument("--vision-reasoning", choices=["on", "off"], default="off", help="截圖檢查要不要開思考")
    ap.add_argument("--no-think-body", default='{"reasoning_effort": "none"}',
                    help="關閉思考時附加的 extra_body；不同服務開關不同")
    ap.add_argument("--seg-max-steps", type=int, default=14)
    ap.add_argument("--seg-think-tokens", type=int, default=2000,
                    help="某段連續兩次沒過檢查時，那段改開思考，回覆上限這麼多 token；0＝不開")
    ap.add_argument("--seg-think-mode", choices=["prompt", "native"], default="prompt",
                    help="卡住時怎麼思考：prompt＝提示模型先寫 <think> 推理（任何模型都能用）；native＝開伺服器的思考開關")
    ap.add_argument("--tool-mode", choices=["native", "text"], default="native",
                    help="text：不用伺服器的原生工具呼叫，改成提示裡說明工具、從回覆 JSON 解析（範本不支援工具的模型用）")
    ap.add_argument("--plan-model", default=None, help="企劃改用另一個模型（例如判斷力較好的 Qwen）；不填就用 --model")
    ap.add_argument("--plan-url", default=None, help="企劃模型的端點；不填就用 --url")
    ap.add_argument("--plan-tool-mode", choices=["native", "text"], default=None, help="企劃模型的工具模式（企劃不用工具，通常不必設）")
    a = ap.parse_args()
    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    no_think = json.loads(a.no_think_body) if a.no_think_body.strip() else {}

    def make_llm(reasoning: str, temperature: float, max_tokens: int, model: str = "", url: str = "",
                 tool_mode: str = "") -> LMWrapper:
        opts = {"temperature": temperature, "max_tokens": max_tokens, "tool_mode": tool_mode or a.tool_mode}
        if reasoning == "off" and no_think:
            opts["extra_body"] = no_think
        return LMWrapper(provider=a.provider, model=model or a.model, api_key=a.api_key, lm_api_url=url or a.url,
                         request_options=opts)

    # 企劃可以用另一個模型：判斷力好的模型排分鏡、分配素材（只呼叫一次），每段交給快的模型
    planner = make_llm(a.plan_reasoning, a.temperature, 12000 if a.plan_reasoning == "on" else 4000,
                       model=a.plan_model or "", url=a.plan_url or "", tool_mode=a.plan_tool_mode or "")
    planner.set_system_prompt("你是影片企劃。只輸出要求的 JSON，不要其他文字。所有名字、年份、數字只能來自題目 brief。")
    vision_llm = make_llm(a.vision_reasoning, 0.1, 2000)

    def vision(img: bytes, prompt: str) -> str:
        try:
            return vision_llm.analyze_image_bytes(prompt=prompt, image_bytes=img, mime_type="image/jpeg",
                                                  system_prompt="你是嚴格的影片畫面檢查員，只回答被問的檢查項目，精簡條列。")
        except Exception as e:  # noqa: BLE001
            return f"(vision failed: {e})"

    conv = f"{time.strftime('%Y%m%d-%H%M%S')}_seg_{Path(a.topic).name}"
    history = LocalChatHistory(storage_directory="chat_history", memory_config={"retain_recent_messages": 100000})
    history.create_conversation(conv)
    model_label = f"{a.model}" if not a.plan_model else f"企劃 {a.plan_model}＋每段 {a.model}"
    history.add_message(conv, {"role": "user", "content": f"分段 Agent 流程：{a.topic}（模型 {model_label}）"})
    pipe = SegmentedPipeline(planner, vision, history=history, conversation_id=conv,
                             seg_llm_factory=lambda: make_llm(a.seg_reasoning, a.temperature, 4000),
                             seg_max_steps=a.seg_max_steps, seg_think_tokens=a.seg_think_tokens,
                             seg_think_mode=a.seg_think_mode)
    t0 = time.time()
    try:
        result = pipe.run(a.topic)
    except Exception as e:  # noqa: BLE001
        result = {"error": f"{type(e).__name__}: {e}"}
        history.add_message(conv, {"role": "assistant", "content": f"流程中止：{e}\n<?final>"})
    rec = {"mode": "segmented", "topic": a.topic, "model": model_label, "seconds": round(time.time() - t0),
           "conversation": conv, "result": result}
    Path(f"chat_history/{conv}.result.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
