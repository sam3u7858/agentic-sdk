"""背景工作：截圖檢查與渲染不再卡住 Agent。

- aam_snap_review 改成「送出就回」：截圖＋看圖在背景跑，Agent 直接做下一段。
- render 也在背景跑；export 前程式會自動等渲染完成。
- 完成的結果會附在之後任何一個 aam 工具的回傳裡（background 欄位），也可以呼叫 aam_wait 主動等。
"""
import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.ai_core.tool_executor import BaseTool


class BackgroundJobs:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="aam-bg")
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, key: str, kind: str, fn: Callable[[], Dict[str, Any]]) -> str:
        """同一個 key（例如 review:seg_03）再送一次會取代舊的、還沒回報的結果。"""
        with self._lock:
            self._jobs[key] = {"key": key, "kind": kind, "future": self._pool.submit(fn),
                               "started": time.time(), "reported": False}
        return key

    def pending(self) -> List[str]:
        with self._lock:
            return [k for k, j in self._jobs.items() if not j["future"].done()]

    def collect(self) -> List[Dict[str, Any]]:
        """取出已完成、還沒回報過的結果（每筆只回報一次）。"""
        out = []
        with self._lock:
            for k, j in self._jobs.items():
                f: Future = j["future"]
                if f.done() and not j["reported"]:
                    j["reported"] = True
                    try:
                        res = f.result()
                    except Exception as e:  # noqa: BLE001
                        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                    out.append({"job": k, "seconds": round(time.time() - j["started"]), **res})
        return out

    def wait(self, timeout: float, keys: Optional[List[str]] = None, every: bool = False) -> None:
        """等到任一（every=True 時為全部）指定工作完成，或逾時。"""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                jobs = [j for k, j in self._jobs.items() if keys is None or k in keys]
            if not jobs:
                return
            if every and all(j["future"].done() for j in jobs):
                return
            if not every and any(j["future"].done() and not j["reported"] for j in jobs):
                return
            time.sleep(1)


def attach_background(result: str, jobs: BackgroundJobs) -> str:
    """把背景完成的結果附在工具回傳裡，Agent 不用另外查詢。"""
    done = jobs.collect()
    pending = jobs.pending()
    if not done and not pending:
        return result
    try:
        data = json.loads(result)
        if not isinstance(data, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        data = {"result": result}
    if done:
        data["background_done"] = done
    if pending:
        data["background_pending"] = pending
    return json.dumps(data, ensure_ascii=False)


class WithBackground(BaseTool):
    """包住任何工具：回傳時順便附上背景完成的結果。"""

    def __init__(self, inner: BaseTool, jobs: BackgroundJobs):
        self._inner = inner
        self._jobs = jobs

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def description(self) -> str:
        return self._inner.description

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._inner.parameters

    def execute(self, **kwargs: Any) -> str:
        return attach_background(str(self._inner.execute(**kwargs)), self._jobs)


class AamWaitTool(BaseTool):
    def __init__(self, jobs: BackgroundJobs):
        self._jobs = jobs

    @property
    def name(self) -> str:
        return "aam_wait"

    @property
    def description(self) -> str:
        return ("等背景工作（截圖檢查、渲染）完成並取回結果。all=true 等全部完成；否則有一個完成就回。"
                "沒有其他事可做時才呼叫。")

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {
            "seconds": {"type": "number", "description": "最多等幾秒，預設 180"},
            "all": {"type": "boolean", "description": "true＝等全部完成"}}, "required": []}

    def execute(self, seconds: float = 180, all: bool = False, **_: Any) -> str:  # noqa: A002
        self._jobs.wait(float(seconds or 180), every=bool(all))
        done, pending = self._jobs.collect(), self._jobs.pending()
        return json.dumps({"ok": True, "background_done": done, "background_pending": pending,
                           "note": "還有工作在跑，可以先做別的再回來" if pending else "背景工作都完成了"},
                          ensure_ascii=False)
