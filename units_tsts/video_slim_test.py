# units_tsts/video_slim_test.py
# 影片 Agent 瘦身版的離線測試：aam 工具錯誤格式、壓縮後訊息順序、送模型前的歷史瘦身。
# 執行：.venv/Scripts/python.exe -X utf8 units_tsts/video_slim_test.py
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.ai_core.compression import SessionCompressionConfig, SessionToolResultCompressor
from src.ai_core.runtime import AgentRuntime
from src.tools.aam_cli_tool import AamCliTool


def _tool_turn(i, name, content, args='{}'):
    tid = f"call_{i}"
    return [
        {"role": "assistant", "content": f"step {i}", "tool_calls": [
            {"id": tid, "type": "function", "function": {"name": name, "arguments": args}}]},
        {"role": "tool", "tool_call_id": tid, "name": name, "content": content},
    ]


def assert_tool_results_follow_calls(msgs):
    pending = set()
    for m in msgs:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            pending = {tc["id"] for tc in m["tool_calls"]}
        elif m.get("role") == "tool":
            assert m["tool_call_id"] in pending, f"工具結果 {m['tool_call_id']} 沒有接在它的呼叫後面"
            pending.discard(m["tool_call_id"])


def test_aam_errors():
    t = AamCliTool()
    for args, key in [([], "args 是空的"), (["rm", "-rf"], "不支援的子指令"),
                      (["config", "R", "seg_01", "--set", 'items=["a"'], "JSON 壞掉"),
                      (["config", "R", "seg_01", "--set", "title"], "缺少「=」"),
                      (["brief", "temppad/haiku_test/does_not_exist"], "沒有 brief.md"),
                      (["media", "R", "seg_01", "hero", "../secret.png"], "")]:
        r = json.loads(t.execute(args=args))
        assert r["ok"] is False and "fix" in r, r
        assert key in r["error"], (key, r)
    # 字串形式的 args 也要能吃
    r = json.loads(t.execute(args='["nope"]'))
    assert r["cmd"] == "nope" and "allowed" in r
    print("ok  aam 錯誤格式")


def test_compression_keeps_order():
    msgs = [{"role": "user", "content": "go"}]
    for i in range(20):
        msgs += _tool_turn(i, "aam", '{"ok": true}')
    comp = SessionToolResultCompressor(SessionCompressionConfig(
        keep_recent_tool_messages=4, level1_window=6, level2_window=10, compress_min_step=0))
    out = comp.compress_messages(msgs, loop_step=30)
    assert out[0]["role"] == "user", "第一則應該還是使用者訊息"
    assert len(out) == len(msgs)
    assert any("ActionLoop" in str(m.get("content")) for m in out)
    assert_tool_results_follow_calls(out)
    print("ok  壓縮後順序")


def test_slim_for_model():
    rt = AgentRuntime.__new__(AgentRuntime)
    rt.terse_steps, rt.drop_toolless_updates, rt.assistant_keep_full, rt.assistant_trim_chars = True, True, 2, 20
    msgs = [{"role": "user", "content": "go"}]
    msgs += _tool_turn(1, "aam_storyboard_segment", '{"ok": false, "error": "key_text 太長"}', args='{"big": "x"}')
    msgs.append({"role": "assistant", "content": "很好，我已經" * 30})
    msgs += _tool_turn(2, "aam_storyboard_segment", '{"ok": true}')
    msgs.append({"role": "assistant", "content": "最後一則沒呼叫工具"})
    msgs += _tool_turn(3, "aam", '{"ok": false, "error": "還沒修正"}')
    out = rt._slim_for_model(msgs)

    assert_tool_results_follow_calls(out)
    first_fail = next(m for m in out if m.get("tool_call_id") == "call_1")
    assert first_fail["content"].startswith("[失敗，已在後續修正]"), first_fail
    owner = next(m for m in out if m.get("tool_calls") and m["tool_calls"][0]["id"] == "call_1")
    assert "_omitted" in owner["tool_calls"][0]["function"]["arguments"]
    still_fail = next(m for m in out if m.get("tool_call_id") == "call_3")
    assert "還沒修正" in still_fail["content"], "還沒修正的失敗要完整保留"
    toolless = [m for m in out if m.get("role") == "assistant" and not m.get("tool_calls")]
    assert [m["content"] for m in toolless] == ["最後一則沒呼叫工具"], toolless
    assert len(msgs[3]["content"]) > 100, "原始歷史不能被改到"
    print("ok  送模型前瘦身")


def test_storyboard_checks():
    from src.tools.aam_tools import _check_storyboard
    seg = lambda i, b: {"id": f"seg_{i:02d}", "block_hint": b}
    six_album = [seg(1, "pk-title-card")] + [seg(i, "pk-album") for i in range(2, 6)] + [seg(6, "pk-outro-cta")]
    p = " ".join(_check_storyboard(six_album))
    assert "至少要 8 段" in p and "種骨架" in p and "連續 3 段" in p, p
    blocks = ["pk-title-card", "pk-media-grid", "pk-album", "pk-versus", "pk-big-stat",
              "pk-flow", "pk-table", "pk-outro-cta"]
    good = [seg(i + 1, b) for i, b in enumerate(blocks)]
    assert _check_storyboard(good) == [], _check_storyboard(good)
    print("ok  分鏡 commit 檢查")


def test_create_title_ascii():
    r = json.loads(AamCliTool().execute(args=["create", "--title", "東方project速覽", "--theme", "collage"]))
    assert r["ok"] is False and "英文" in r["fix"], r
    print("ok  create 標題限英數")


def test_history_keeps_task(tmp=Path(__file__).parent / "_tmp_hist"):
    import shutil
    from src.ai_core.history import LocalChatHistory
    shutil.rmtree(tmp, ignore_errors=True)
    h = LocalChatHistory(storage_directory=str(tmp), memory_config={"retain_recent_messages": 4})
    h.create_conversation("c")
    h.add_message("c", {"role": "user", "content": "任務：做 t01"})
    for i in range(12):
        h.add_message("c", {"role": "assistant", "content": f"步驟 {i}"})
    msgs = h.get_conversation("c")["messages"]
    shutil.rmtree(tmp, ignore_errors=True)
    assert msgs[0]["content"] == "任務：做 t01", msgs[0]
    assert any(m["content"] == "[ARCHIVED_MESSAGE]" for m in msgs), "其他舊訊息仍應封存"
    print("ok  任務訊息不被封存")


def test_thick_fill_checks():
    from src.video_thick import Pipeline, _config_chunks, load_catalog
    cfg = '''const CONFIG = {
        events: [
          { year: "1999", top: "10.8億", label: "", image: true },
          { year: "2007", top: "", label: "委辦", image: true },
        ], // 註解
        spacing: "time", // 間距
        duration: 9,
      };'''
    ch = _config_chunks(cfg)
    assert set(ch) == {"events", "spacing", "duration"}, ch
    p = Pipeline.__new__(Pipeline)
    p.cat = load_catalog()
    seg = {"id": "s", "block": "pk-timeline-pan", "media": ["a", "b"], "config": cfg}
    brief = "2002 紅魔鄉 2003 妖妖夢"
    good = {"events": [{"year": "2002", "label": "紅魔鄉"}, {"year": "2003", "label": "妖妖夢"}], "spacing": "time"}
    assert p.check_fill(good, seg, {"brief": brief}) == [], "設定欄位 spacing 不該被當成範例字"
    bad = {"events": [{"year": "1999", "top": "10.8億", "label": "委辦"}, {"year": "2003", "label": "妖妖夢"}]}
    probs = " ".join(p.check_fill(bad, seg, {"brief": brief}))
    assert "委辦" in probs and "1999" in probs, probs
    print("ok  thick 填字檢查只看內容欄位")


def test_background_jobs():
    import time
    from src.tools.aam_background import BackgroundJobs, attach_background
    jobs = BackgroundJobs(workers=2)
    jobs.submit("review:seg_01", "review", lambda: (time.sleep(1), {"ok": True, "review": "PASS"})[1])
    first = json.loads(attach_background('{"ok": true}', jobs))
    assert first.get("background_pending") == ["review:seg_01"], first
    jobs.wait(5, every=True)
    second = json.loads(attach_background('{"ok": true}', jobs))
    assert second["background_done"][0]["review"] == "PASS", second
    third = attach_background('{"ok": true}', jobs)
    assert third == '{"ok": true}', "同一筆結果只回報一次"
    print("ok  背景工作")


if __name__ == "__main__":
    test_background_jobs()
    test_thick_fill_checks()
    test_aam_errors()
    test_compression_keeps_order()
    test_slim_for_model()
    test_storyboard_checks()
    test_create_title_ascii()
    test_history_keeps_task()
    print("全部通過")
