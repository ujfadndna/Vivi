"""SoulX-FlashHead backend registered under the MuseTalk module contract."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, Iterator

from app import storage
from app.config import settings
from app.schemas import AudioWithTimestamps, FrameSequence, VideoMetadata
from app.services.base import register
from app.services.flashhead.persistent import worker_manager
from app.services.musetalk.service import MuseTalkBackend


@register("musetalk", "local")
class FlashHeadReal(MuseTalkBackend):
    def run(
        self,
        video: VideoMetadata,
        audio: AudioWithTimestamps,
        task_id: str,
    ) -> FrameSequence:
        audio_path = Path(audio.audio_path).expanduser().resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(f"FlashHead input audio does not exist: {audio_path}")

        image_path = _resolve_avatar_image(video)
        out_dir = storage.musetalk_dir(task_id).resolve()
        _clear_output_frames(out_dir)

        job = {
            "task_id": task_id,
            "image_path": str(image_path),
            "audio_path": str(audio_path),
            "output_dir": str(out_dir),
            "fps": video.fps,
        }
        result = _submit_flashhead_job(job)
        num_frames = _result_num_frames(result)

        return FrameSequence(
            output_frames_dir=str(out_dir),
            num_frames=num_frames,
            fps=video.fps,
            full_frame=True,
        )

    def run_streaming(
        self,
        video: VideoMetadata,
        pcm_chunks: Iterator[bytes],
        task_id: str,
    ) -> FrameSequence:
        image_path = _resolve_avatar_image(video)
        out_dir = storage.musetalk_dir(task_id).resolve()
        _clear_output_frames(out_dir)
        pcm_chunk_list = list(pcm_chunks)

        try:
            result = worker_manager.stream_tts_to_flashhead(
                task_id=task_id,
                image_path=str(image_path),
                output_dir=str(out_dir),
                fps=video.fps,
                pcm_chunks_iter=iter(pcm_chunk_list),
            )
        except RuntimeError as exc:
            if "not running" not in str(exc):
                raise
            worker_manager.start()
            result = worker_manager.stream_tts_to_flashhead(
                task_id=task_id,
                image_path=str(image_path),
                output_dir=str(out_dir),
                fps=video.fps,
                pcm_chunks_iter=iter(pcm_chunk_list),
            )

        num_frames = _result_num_frames(result)
        return FrameSequence(
            output_frames_dir=str(out_dir),
            num_frames=num_frames,
            fps=video.fps,
            full_frame=True,
        )


def _resolve_avatar_image(video: VideoMetadata) -> Path:
    if video.video_id == "default_avatar_image":
        for frame_path in _frame_candidates(Path(video.frames_dir).expanduser().resolve()):
            if frame_path.is_file():
                return frame_path.resolve()

    default_image = Path(settings.default_avatar_image).expanduser().resolve()
    if default_image.is_file():
        return default_image

    raise FileNotFoundError(
        "FlashHead avatar image is not configured. Upload an avatar image or set "
        f"DEFAULT_AVATAR_IMAGE to the correct reference image. Expected file: {default_image}"
    )


def _frame_candidates(frames_dir: Path) -> Iterable[Path]:
    preferred = frames_dir / "00000000.png"
    if preferred.exists():
        yield preferred
    for path in sorted(frames_dir.iterdir(), key=_frame_sort_key):
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"} and path != preferred:
            yield path


def _frame_sort_key(path: Path) -> tuple[int, int | str]:
    try:
        return (0, int(path.stem))
    except ValueError:
        return (1, path.name)


def _clear_output_frames(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for frame_path in out_dir.glob("*.png"):
        frame_path.unlink()
    work_dir = out_dir / "_musetalk_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)


def _submit_flashhead_job(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return worker_manager.submit_job(job)
    except RuntimeError as exc:
        if "not running" not in str(exc):
            raise
        worker_manager.start()
        return worker_manager.submit_job(job)


def _result_num_frames(result: dict[str, Any]) -> int:
    if result.get("status") != "ok":
        raise RuntimeError(
            "FlashHead persistent worker inference failed: "
            f"{_tail(result.get('error_msg'))}"
        )

    num_frames = int(result.get("num_frames") or 0)
    if num_frames <= 0:
        raise RuntimeError("FlashHead inference produced no frames")
    return num_frames


def _tail(value: object, limit: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[-limit:]
