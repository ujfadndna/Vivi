"""数据契约（pydantic）。所有模块的输入/输出在此定义，是并行开发的接口基准。

对应 docs/digital-human-design.md 各模块的「接口契约」。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ── 通用 ───────────────────────────────────────────────────


class TaskState(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


Bbox = tuple[int, int, int, int]  # x1, y1, x2, y2
Resolution = tuple[int, int]      # width, height


# ── 1. 素材接入 ────────────────────────────────────────────


class VideoMetadata(BaseModel):
    video_id: str
    fps: float
    num_frames: int
    duration_sec: float
    resolution: Resolution
    face_bbox: Bbox                 # 主人脸
    frames_dir: str                 # 抽帧目录
    status: str = "ready"


# ── 2. 文本与语音 ──────────────────────────────────────────


class PhonemeInterval(BaseModel):
    phoneme: str
    start_frame: int
    end_frame: int


class AudioWithTimestamps(BaseModel):
    audio_id: str
    audio_path: str
    duration_sec: float
    duration_frames: int
    sample_rate: int
    phoneme_intervals: list[PhonemeInterval] = Field(default_factory=list)


class SubtitleSegment(BaseModel):
    text: str
    start_sec: float
    end_sec: float


class SynthesizeRequest(BaseModel):
    text: str
    language: str = "zh"            # zh | en | ja | ko
    speaker_id: Optional[str] = None
    tts_api_url: Optional[str] = None
    emotion: str = "neutral"        # neutral | happy | sad | angry
    speed: float = 1.0


# ── 3. 嘴型同步（MuseTalk）─────────────────────────────────


class FrameSequence(BaseModel):
    output_frames_dir: str
    num_frames: int
    fps: float
    full_frame: bool = True


# ── 4. 人像分割（RVM）──────────────────────────────────────


class SegmentedFrames(BaseModel):
    foreground_frames_dir: str
    mask_dir: str
    num_frames: int


# ── 5. 背景处理 ────────────────────────────────────────────


class BackgroundMode(str, Enum):
    static = "static"
    dynamic_video = "dynamic_video"
    generated = "generated"


class BackgroundFrames(BaseModel):
    background_frames_dir: str
    num_frames: int


# ── 6. 视频合成 ────────────────────────────────────────────


class CompositeResult(BaseModel):
    video_path: str
    size_mb: float
    duration_sec: float


# ── 7. 任务编排 ────────────────────────────────────────────


class GenerateRequest(BaseModel):
    text: str
    language: str = "zh"
    background_mode: BackgroundMode = BackgroundMode.static
    emotion: str = "neutral"
    speed: float = 1.0
    speaker_id: Optional[str] = None


class StageProgress(BaseModel):
    ingest: str = "pending"
    audio_synthesis: str = "pending"
    musetalk: str = "pending"
    segmentation: str = "pending"
    background: str = "pending"
    composite: str = "pending"


class GenerationStatus(BaseModel):
    task_id: str
    status: TaskState
    progress: StageProgress = Field(default_factory=StageProgress)
    video_url: Optional[str] = None
    error: Optional[str] = None
