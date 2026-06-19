"""端到端编排：素材→语音→嘴型→分割→背景→合成。

对应 docs「### 7. 任务编排」的 DAG。MVP 用顺序编排 + 逐阶段状态更新，
逻辑清晰、便于排查；并行（musetalk 与 background 可并行）留待 v2 优化。
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings
from app.schemas import (
    AudioWithTimestamps,
    BackgroundMode,
    GenerateRequest,
    SynthesizeRequest,
    TaskState,
    VideoMetadata,
)
from app.services.background import run_background
from app.services.composite import run_composite
from app.services.ingest import run_ingest
from app.services.musetalk.service import run_musetalk
from app.services.segment import run_segment
from app.services.tts import run_tts
from app.tasks import store
from app.tasks.celery_app import celery_app


class GenerationOutput(str):
    """String-compatible generation result with both file path and public URL."""

    video_path: str
    video_url: str

    def __new__(cls, video_path: str, video_url: str) -> "GenerationOutput":
        obj = str.__new__(cls, video_path)
        obj.video_path = video_path
        obj.video_url = video_url
        return obj


@contextmanager
def _timed(stage: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        print(f"[TIMING] {stage}: {time.perf_counter() - t0:.1f}s", file=sys.stderr, flush=True)


def run_generation(task_id: str, video_path: str, req: GenerateRequest) -> GenerationOutput:
    """同步跑完整条链路，返回最终视频的对外 URL。逐阶段写状态。

    自包含：若状态条目尚未创建（如 CLI 直接调用）则补建，故可独立运行。
    """
    if store.get(task_id) is None:
        store.create(task_id)
    store.set_status(task_id, TaskState.processing)

    # 1. 素材接入
    store.set_stage(task_id, "ingest", "processing")
    with _timed("ingest"):
        video = run_ingest(video_path)
    store.set_stage(task_id, "ingest", "completed")

    # 2. 文本与语音
    store.set_stage(task_id, "audio_synthesis", "processing")
    synth_req = SynthesizeRequest(
        text=req.text, language=req.language, emotion=req.emotion, speed=req.speed,
        speaker_id=req.speaker_id,
    )
    with _timed("audio_synthesis"):
        audio = run_tts(synth_req, fps=video.fps)
    store.set_stage(task_id, "audio_synthesis", "completed")

    return run_generation_from_audio(
        task_id=task_id,
        video=video,
        audio=audio,
        background_mode=req.background_mode,
    )


def run_generation_from_audio(
    task_id: str,
    video: VideoMetadata,
    audio: AudioWithTimestamps | None = None,
    audio_path: str | None = None,
    background_mode: BackgroundMode = BackgroundMode.static,
) -> GenerationOutput:
    """从已合成音频开始跑渲染链路，供分句流水线复用单 worker 串行 MuseTalk。"""
    if audio is None:
        if audio_path is None:
            raise ValueError("audio or audio_path is required")
        audio = _audio_from_path(audio_path, fps=video.fps)

    if store.get(task_id) is None:
        store.create(task_id)
    store.set_status(task_id, TaskState.processing)
    store.set_stage(task_id, "ingest", "completed")
    store.set_stage(task_id, "audio_synthesis", "completed")

    # 3. 嘴型同步
    store.set_stage(task_id, "musetalk", "processing")
    with _timed("musetalk"):
        frames = run_musetalk(video, audio, task_id)
    store.set_stage(task_id, "musetalk", "completed")

    use_direct_frames = settings.skip_rvm and frames.full_frame
    if use_direct_frames:
        store.set_stage(task_id, "segmentation", "skipped")
        store.set_stage(task_id, "background", "skipped")
        seg = frames
        bg = None
    else:
        # 4. 人像分割
        store.set_stage(task_id, "segmentation", "processing")
        with _timed("segmentation"):
            seg = run_segment(frames, task_id)
        store.set_stage(task_id, "segmentation", "completed")

        # 5. 背景处理（帧数/分辨率对齐前景）
        store.set_stage(task_id, "background", "processing")
        with _timed("background"):
            bg = run_background(
                mode=background_mode,
                num_frames=frames.num_frames,
                resolution=video.resolution,
                task_id=task_id,
            )
        store.set_stage(task_id, "background", "completed")

    # 6. 视频合成
    store.set_stage(task_id, "composite", "processing")
    with _timed("composite"):
        result = run_composite(seg, bg, audio, fps=video.fps, task_id=task_id)
    store.set_stage(task_id, "composite", "completed")

    video_url = f"/outputs/{task_id}.mp4"
    store.finish(task_id, video_url)
    return GenerationOutput(video_path=result.video_path, video_url=video_url)


def run_tts_only(
    task_id: str,
    text: str,
    fps: float = 25.0,
    speaker_id: str | None = None,
    tts_api_url: str | None = None,
    language: str = "zh",
    emotion: str = "neutral",
    speed: float = 1.0,
) -> AudioWithTimestamps:
    """Run only TTS and return audio. For batch pipeline: TTS first, FlashHead later."""
    synth_req = SynthesizeRequest(
        text=text, language=language, emotion=emotion, speed=speed,
        tts_api_url=tts_api_url,
        speaker_id=speaker_id,
    )
    with _timed(f"tts_only:{task_id}"):
        return run_tts(synth_req, fps=fps)


def _audio_from_path(audio_path: str, fps: float) -> AudioWithTimestamps:
    path = Path(audio_path)
    duration_sec, sample_rate = _probe_audio(path)
    return AudioWithTimestamps(
        audio_id=path.stem or "audio",
        audio_path=str(path),
        duration_sec=duration_sec,
        duration_frames=max(1, round(duration_sec * fps)),
        sample_rate=sample_rate,
        phoneme_intervals=[],
    )


def _probe_audio(path: Path) -> tuple[float, int]:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        if info.frames > 0 and info.samplerate > 0:
            return info.frames / info.samplerate, int(info.samplerate)
    except Exception:
        pass

    try:
        import wave

        with wave.open(str(path), "rb") as wav:
            frames = wav.getnframes()
            sample_rate = wav.getframerate()
            if frames > 0 and sample_rate > 0:
                return frames / sample_rate, sample_rate
    except Exception as exc:
        raise RuntimeError(f"Unable to read audio metadata: {path}") from exc

    raise RuntimeError(f"Unable to read audio metadata: {path}")


@celery_app.task(name="generate")
def generate_task(task_id: str, video_path: str, req_dict: dict) -> str:
    """Celery 任务包装。eager 模式下同步执行；失败写状态后抛出以便重试。"""
    try:
        return run_generation(task_id, video_path, GenerateRequest(**req_dict))
    except Exception as e:  # noqa: BLE001 — 顶层兜底，记录后上抛
        store.fail(task_id, str(e))
        raise
