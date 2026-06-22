"""Background task tracking shared by web routes."""

import threading
import time as _time
import uuid

_task_store: dict[str, dict] = {}
_task_lock = threading.Lock()
_card_gen_lock = threading.Lock()


def _start_bg_task(target):
    """启动后台任务, 返回 task_id"""
    task_id = str(uuid.uuid4())[:8]
    with _task_lock:
        _task_store[task_id] = {
            "status": "running",
            "progress": 0,
            "status_text": "启动中...",
            "result": None,
            "error": None,
            "started_at": _time.time(),
        }

    def _runner():
        try:
            result = target(task_id)
            with _task_lock:
                _task_store[task_id]["status"] = "done"
                _task_store[task_id]["progress"] = 100
                _task_store[task_id]["result"] = result
        except Exception as e:
            with _task_lock:
                _task_store[task_id]["status"] = "error"
                _task_store[task_id]["error"] = str(e)[:500]

    threading.Thread(target=_runner, daemon=True).start()
    return task_id
