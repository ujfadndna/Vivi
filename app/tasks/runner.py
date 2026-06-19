"""进程内异步任务执行：单 worker 线程串行执行渲染任务（GPU 安全），提交即返回。

为什么不直接用 Celery eager：eager 在请求协程内同步跑完整条渲染链路，会阻塞 FastAPI
事件循环，导致分句流水线（render_scheduler）的并发提交 / 轮询全部排队甚至超时。
单 worker 线程池在不引入 Redis 的前提下提供真实异步：提交立即返回 task_id，轮询不被
事件循环阻塞；GPU 推理不可并发，故 worker 数固定为 1，任务按提交顺序串行执行。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from app.schemas import AudioWithTimestamps, GenerateRequest, VideoMetadata
from app.tasks import store
from app.tasks.pipeline import run_generation, run_generation_from_audio

logger = logging.getLogger(__name__)

# 单 worker：GPU 推理串行执行，避免显存争用与模型非线程安全问题
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render-worker")


def submit_generation(task_id: str, video_path: str, req: GenerateRequest) -> None:
    """提交渲染任务到后台串行队列，立即返回（不阻塞调用方）。"""
    _executor.submit(_run_safe, task_id, video_path, req)


def submit_generation_from_audio(
    task_id: str,
    video: VideoMetadata,
    audio: AudioWithTimestamps | None = None,
    audio_path: str | None = None,
) -> None:
    """提交已完成 TTS 的渲染任务到后台串行队列，立即返回。"""
    _executor.submit(_run_from_audio_safe, task_id, video, audio, audio_path)


def _run_safe(task_id: str, video_path: str, req: GenerateRequest) -> None:
    try:
        result = run_generation(task_id, video_path, req)
        _ensure_video_url_finished(task_id, result)
    except Exception as exc:  # noqa: BLE001 — 顶层兜底，写失败状态而非让线程静默退出
        logger.exception("render task failed: %s", task_id)
        store.fail(task_id, str(exc))


def _run_from_audio_safe(
    task_id: str,
    video: VideoMetadata,
    audio: AudioWithTimestamps | None,
    audio_path: str | None,
) -> None:
    try:
        result = run_generation_from_audio(
            task_id=task_id,
            video=video,
            audio=audio,
            audio_path=audio_path,
        )
        _ensure_video_url_finished(task_id, result)
    except Exception as exc:  # noqa: BLE001 — 顶层兜底，写失败状态而非让线程静默退出
        logger.exception("render task failed: %s", task_id)
        store.fail(task_id, str(exc))


def _ensure_video_url_finished(task_id: str, result: object) -> None:
    """Keep the task store authoritative even if a runner path returns metadata."""
    video_url = getattr(result, "video_url", None)
    if not isinstance(video_url, str) or not video_url:
        video_url = f"/outputs/{task_id}.mp4"

    status = store.get(task_id)
    if status is None:
        store.create(task_id)
    store.finish(task_id, video_url)
