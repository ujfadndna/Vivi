"""各模块独立端点，对应 docs 每节的「接口契约」。

与文档的差异（有意为之，便于 MVP 单测与可插拔验证）：
- 同步返回结果，不走 202 异步任务轮询；
- 上游产物以 schema 对象（JSON body）直接前传，而非用 id 在服务端重建状态。
真实异步/缓存留待编排层（/api/v1/generate）与 v2。
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas import (
    AudioWithTimestamps,
    BackgroundFrames,
    BackgroundMode,
    CompositeResult,
    FrameSequence,
    Resolution,
    SegmentedFrames,
    SynthesizeRequest,
    VideoMetadata,
)
from app.services.background import run_background
from app.services.composite import run_composite
from app.services.ingest import run_ingest
from app.services.musetalk.service import run_musetalk
from app.services.segment import run_segment
from app.services.tts import run_tts
import shutil
from pathlib import Path

from app.config import settings
from app.storage import new_id

router = APIRouter(prefix="/api/v1", tags=["modules"])


# ── 1. 素材接入 ────────────────────────────────────────────


@router.post("/videos/ingest", response_model=VideoMetadata)
async def ingest_video(video_file: UploadFile = File(...)):
    uploads = settings.workspace_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    ext = Path(video_file.filename or "input.mp4").suffix or ".mp4"
    dst = uploads / f"{new_id('vid_in')}{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(video_file.file, f)
    try:
        return run_ingest(str(dst))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 2. 文本与语音 ──────────────────────────────────────────


@router.post("/audio/synthesize", response_model=AudioWithTimestamps)
async def synthesize(req: SynthesizeRequest, fps: float = settings.default_fps):
    return run_tts(req, fps=fps)


# ── 3. 嘴型同步 ────────────────────────────────────────────


@router.post("/musetalk/generate", response_model=FrameSequence)
async def musetalk(video: VideoMetadata, audio: AudioWithTimestamps):
    return run_musetalk(video, audio, task_id=new_id("mt"))


# ── 4. 人像分割 ────────────────────────────────────────────


@router.post("/segment/person", response_model=SegmentedFrames)
async def segment(frames: FrameSequence):
    return run_segment(frames, task_id=new_id("seg"))


# ── 5. 背景处理 ────────────────────────────────────────────


@router.post("/background/prepare", response_model=BackgroundFrames)
async def background(
    mode: BackgroundMode,
    num_frames: int,
    resolution: Resolution,
    bg_image_path: str | None = None,
    description: str | None = None,
):
    return run_background(
        mode, num_frames, resolution, task_id=new_id("bg"),
        bg_image_path=bg_image_path, description=description,
    )


# ── 6. 视频合成 ────────────────────────────────────────────


@router.post("/composite/render", response_model=CompositeResult)
async def composite(
    fg: SegmentedFrames,
    bg: BackgroundFrames,
    audio: AudioWithTimestamps,
    fps: float = settings.default_fps,
):
    return run_composite(fg, bg, audio, fps=fps, task_id=new_id("cmp"))
