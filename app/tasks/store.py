"""生成任务状态存储。

MVP 用进程内字典（配合 Celery eager 模式同进程足够）。生产环境应换成
Redis / PostgreSQL（见 docs 的 tasks 表设计），接口保持不变即可替换。
"""
from __future__ import annotations

import threading
from typing import Optional

from app.schemas import GenerationStatus, TaskState

_LOCK = threading.Lock()
_STATUS: dict[str, GenerationStatus] = {}


def create(task_id: str) -> None:
    with _LOCK:
        _STATUS[task_id] = GenerationStatus(task_id=task_id, status=TaskState.queued)


def get(task_id: str) -> Optional[GenerationStatus]:
    with _LOCK:
        return _STATUS.get(task_id)


def set_status(task_id: str, status: TaskState) -> None:
    with _LOCK:
        _STATUS[task_id].status = status


def set_stage(task_id: str, stage: str, value: str) -> None:
    with _LOCK:
        setattr(_STATUS[task_id].progress, stage, value)


def finish(task_id: str, video_url: str) -> None:
    with _LOCK:
        st = _STATUS[task_id]
        st.status = TaskState.completed
        st.video_url = video_url


def fail(task_id: str, error: str) -> None:
    with _LOCK:
        st = _STATUS[task_id]
        st.status = TaskState.failed
        st.error = error
