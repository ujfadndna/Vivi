"""工作区路径管理。统一中间产物落盘位置，便于缓存与排查。

布局对应 docs/digital-human-design.md「数据流设计 / 文件组织」。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings

ROOT = settings.workspace_dir


def _ensure(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── 各阶段目录 ─────────────────────────────────────────────


def video_dir(video_id: str) -> Path:
    return _ensure(ROOT / "videos" / video_id)


def video_frames_dir(video_id: str) -> Path:
    return _ensure(video_dir(video_id) / "frames")


def audio_dir(audio_id: str) -> Path:
    return _ensure(ROOT / "audio" / audio_id)


def musetalk_dir(task_id: str) -> Path:
    return _ensure(ROOT / "processing" / "musetalk" / task_id)


def segment_dir(task_id: str) -> Path:
    return _ensure(ROOT / "processing" / "segmentation" / task_id)


def background_dir(task_id: str) -> Path:
    return _ensure(ROOT / "processing" / "background" / task_id)


def output_dir() -> Path:
    return _ensure(ROOT / "outputs")


def preview_dir() -> Path:
    return _ensure(ROOT / "preview")
