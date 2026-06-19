"""主编排端点：上传视频+文本 → 异步生成 → 轮询状态 → 下载。

对应 docs「### 7. 任务编排」的 /api/v1/generate。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import profile_store
from app.config import settings
from app.schemas import (
    AudioWithTimestamps,
    BackgroundMode,
    GenerateRequest,
    GenerationStatus,
    SubtitleSegment,
    VideoMetadata,
)
from app.tasks import store
from app.tasks.runner import submit_generation
from app.storage import new_id

router = APIRouter(prefix="/api/v1", tags=["generate"])

_SENTENCE_TERMINATORS = tuple("。！？.!?")


def _save_upload(upload: UploadFile, task_id: str) -> str:
    uploads = settings.workspace_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    ext = Path(upload.filename or "input.mp4").suffix or ".mp4"
    dst = uploads / f"{task_id}{ext}"
    with dst.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dst)


@router.post("/generate", status_code=202)
async def generate(
    video_file: UploadFile = File(...),
    text: str = Form(...),
    language: str = Form("zh"),
    background_mode: BackgroundMode = Form(BackgroundMode.static),
    emotion: str = Form("neutral"),
    speed: float = Form(1.0),
):
    task_id = new_id("gen")
    video_path = _save_upload(video_file, task_id)
    store.create(task_id)

    req = GenerateRequest(
        text=text,
        language=language,
        background_mode=background_mode,
        emotion=emotion,
        speed=speed,
    )
    # 提交到进程内单 worker 后台队列，立即返回；客户端轮询 /generate/{task_id} 获取进度
    submit_generation(task_id, video_path, req)

    return {"task_id": task_id, "status": "queued"}


@router.get("/generate/{task_id}", response_model=GenerationStatus)
async def get_generation(task_id: str):
    st = store.get(task_id)
    if st is None:
        raise HTTPException(status_code=404, detail="task not found")
    return st


@router.post("/generate-text-only", status_code=202)
async def generate_text_only(
    text: str = Form(...),
    language: str = Form("zh"),
    emotion: str = Form("neutral"),
    speed: float = Form(1.0),
    background_mode: BackgroundMode = Form(BackgroundMode.static),
    speaker_id: str | None = Form(None),
):
    """Agent 层专用端点：使用配置的默认数字人视频，无需上传视频文件。

    Agent 通过此端点调用渲染层，保持两层 HTTP 解耦。
    默认视频路径由 settings.default_avatar_video 配置。
    """
    avatar_path = settings.default_avatar_video
    if not avatar_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Default avatar video not found: {avatar_path}. "
                   "Please set DEFAULT_AVATAR_VIDEO in .env and place the file.",
        )

    # 默认音色兜底：分句流水线（render_scheduler）不传 speaker_id，
    # IndexTTS2 音色克隆需要参考音频，这里回退到配置的默认参考音色。
    if not speaker_id:
        speaker_path = profile_store.resolve_speaker_wav()
        if speaker_path:
            speaker_id = str(speaker_path)

    task_id = new_id("gen")
    store.create(task_id)

    req = GenerateRequest(
        text=text,
        language=language,
        background_mode=background_mode,
        emotion=emotion,
        speed=speed,
        speaker_id=speaker_id,
    )
    submit_generation(task_id, str(avatar_path), req)

    return {"task_id": task_id, "status": "queued"}


def _concat_videos(video_urls: list[str]) -> str | None:
    """Merge multiple MP4s into one browser-friendly continuous MP4."""
    import logging
    import subprocess
    import sys
    from pathlib import Path

    import imageio_ffmpeg

    _log = logging.getLogger(__name__)

    def _emit(level: str, message: str, *args: object) -> None:
        rendered = message % args
        getattr(_log, level)(rendered)
        print(rendered, file=sys.stderr, flush=True)

    workspace = Path(settings.workspace_dir).resolve()
    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    list_path = outputs_dir / f"concat_{new_id('merge')}.txt"
    merged_path = outputs_dir / f"gen_{new_id('gen')}.mp4"
    started = time.perf_counter()

    input_paths: list[Path] = []
    for video_url in video_urls:
        abs_path = (workspace / video_url.lstrip("/")).resolve()
        if not abs_path.exists():
            _emit("error", "[CONCAT] input missing: %s", abs_path)
            return None
        input_paths.append(abs_path)

    def _concat_file_path(path: Path) -> str:
        return path.as_posix().replace("'", "'\\''")

    try:
        with list_path.open("w", encoding="utf-8") as file_list:
            for path in input_paths:
                file_list.write(f"file '{_concat_file_path(path)}'\n")

        fps = float(settings.default_fps)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        _emit(
            "info",
            "[CONCAT] start inputs=%d output=%s fps=%s",
            len(input_paths),
            merged_path,
            fps,
        )
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-r", str(fps),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(merged_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.SubprocessError as exc:
        _emit("error", "[CONCAT] FAILED inputs=%d output=%s error=%s", len(input_paths), merged_path, exc)
        return None
    finally:
        list_path.unlink(missing_ok=True)

    if result.returncode != 0 or not merged_path.exists() or merged_path.stat().st_size == 0:
        _emit(
            "error",
            "[CONCAT] FAILED inputs=%d output=%s rc=%s exists=%s stderr=%s",
            len(input_paths),
            merged_path,
            result.returncode,
            merged_path.exists(),
            (result.stderr[-500:] if result.stderr else "(empty)"),
        )
        return None

    _emit(
        "info",
        "[CONCAT] OK inputs=%d output=%s size=%d elapsed=%.2fs",
        len(input_paths),
        merged_path,
        merged_path.stat().st_size,
        time.perf_counter() - started,
    )
    return f"/outputs/{merged_path.name}"


def _parse_sentence_list(sentences: str) -> list[str]:
    """Parse a JSON sentence array or newline-delimited text into clean sentences."""
    if sentences.lstrip().startswith("["):
        import json

        try:
            parsed = json.loads(sentences)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid sentences JSON") from exc
        if not isinstance(parsed, list):
            raise ValueError("sentences JSON must be an array")
        raw_sentences = parsed
    else:
        raw_sentences = sentences.splitlines()

    return [str(sentence).strip() for sentence in raw_sentences if str(sentence).strip()]


def _join_sentences_for_tts(sentence_list: list[str], language: str) -> str:
    """Join sentence fragments into one TTS input while preserving natural pauses."""
    is_chinese = language.lower().startswith("zh")
    terminator = "。" if is_chinese else "."
    pieces: list[str] = []

    for sentence in sentence_list:
        text = sentence.strip()
        if not text:
            continue
        if not text.endswith(_SENTENCE_TERMINATORS):
            text = f"{text}{terminator}"
        pieces.append(text)

    return "".join(pieces) if is_chinese else " ".join(pieces)


def _subtitle_weight(text: str) -> int:
    return max(1, sum(1 for char in text if not char.isspace()))


def _audio_duration_seconds(audio: AudioWithTimestamps, fps: float) -> float:
    if audio.duration_sec > 0:
        return float(audio.duration_sec)
    if audio.duration_frames > 0 and fps > 0:
        return float(audio.duration_frames) / float(fps)
    return 0.0


def _build_subtitle_segments(
    sentence_list: list[str],
    audio: AudioWithTimestamps,
    fps: float,
) -> list[SubtitleSegment]:
    """Allocate cleaned sentences over the full TTS audio duration."""
    duration_sec = _audio_duration_seconds(audio, fps)
    if not sentence_list or duration_sec <= 0:
        return []

    weights = [_subtitle_weight(sentence) for sentence in sentence_list]
    total_weight = sum(weights) or len(sentence_list)
    segments: list[SubtitleSegment] = []
    cursor = 0.0

    for index, (sentence, weight) in enumerate(zip(sentence_list, weights)):
        if index == len(sentence_list) - 1:
            end_sec = duration_sec
        else:
            end_sec = duration_sec * sum(weights[: index + 1]) / total_weight
        end_sec = max(cursor, min(duration_sec, end_sec))
        segments.append(
            SubtitleSegment(
                text=sentence,
                start_sec=round(cursor, 3),
                end_sec=round(end_sec, 3),
            )
        )
        cursor = end_sec

    return segments


def _default_avatar_metadata() -> VideoMetadata:
    """Return avatar metadata for image-driven FlashHead batch rendering."""
    image_path = profile_store.resolve_avatar_image()
    if not image_path.is_file() and settings.musetalk_backend == "mock":
        image_path = _create_mock_avatar_image(image_path)
    if not image_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Default avatar image not found. Set DEFAULT_AVATAR_IMAGE and place "
                f"the file: {image_path}"
            ),
        )

    try:
        import cv2

        image = cv2.imread(str(image_path))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot read default avatar image: {image_path}") from exc

    if image is None:
        raise HTTPException(status_code=503, detail=f"Cannot read default avatar image: {image_path}")

    frame_path = image_path.parent / "00000000.png"
    try:
        cv2.imwrite(str(frame_path), image)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot prepare default avatar frame: {frame_path}") from exc

    height, width = image.shape[:2]
    return VideoMetadata(
        video_id="default_avatar_image",
        fps=float(settings.default_fps),
        num_frames=1,
        duration_sec=1.0 / float(settings.default_fps),
        resolution=(width, height),
        face_bbox=(0, 0, width, height),
        frames_dir=str(image_path.parent),
        status="ready",
    )


def _create_mock_avatar_image(image_path: Path) -> Path:
    """Create a small built-in placeholder so Docker mock mode works from an empty workspace."""
    try:
        import cv2
        import numpy as np

        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = np.full((480, 360, 3), (42, 48, 56), dtype=np.uint8)
        cv2.circle(image, (180, 155), 82, (176, 142, 106), -1)
        cv2.rectangle(image, (95, 245), (265, 470), (72, 92, 112), -1)
        cv2.circle(image, (150, 140), 9, (24, 24, 24), -1)
        cv2.circle(image, (210, 140), 9, (24, 24, 24), -1)
        cv2.ellipse(image, (180, 185), (34, 12), 0, 0, 180, (70, 38, 48), 3)
        cv2.imwrite(str(image_path), image)
    except Exception:
        return image_path
    return image_path


def _avatar_upload_metadata(avatar_file: UploadFile) -> VideoMetadata:
    """Build one-frame avatar metadata from a multipart image upload."""
    ext = Path(avatar_file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=422, detail="avatar_file must be png, jpg, jpeg, or webp")

    task_id = new_id("avatar")
    avatar_dir = settings.workspace_dir / "uploads" / task_id
    avatar_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = avatar_dir / f"source{ext}"
    frame_path = avatar_dir / "00000000.png"
    with tmp_path.open("wb") as handle:
        shutil.copyfileobj(avatar_file.file, handle)

    try:
        import cv2

        image = cv2.imread(str(tmp_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("image cannot be decoded")
        if not cv2.imwrite(str(frame_path), image):
            raise ValueError("image cannot be written")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="avatar_file image cannot be decoded") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    height, width = image.shape[:2]
    return VideoMetadata(
        video_id="default_avatar_image",
        fps=float(settings.default_fps),
        num_frames=1,
        duration_sec=1.0 / float(settings.default_fps),
        resolution=(width, height),
        face_bbox=(0, 0, width, height),
        frames_dir=str(avatar_dir),
        status="ready",
    )


@router.post("/generate-text-batch", status_code=202)
async def generate_text_batch(
    sentences: str = Form(...),
    language: str = Form("zh"),
    emotion: str = Form("neutral"),
    speed: float = Form(1.0),
    speaker_id: str | None = Form(None),
    tts_api_url: str | None = Form(None),
    avatar_file: UploadFile | None = File(None),
):
    """Render multiple sentences as one continuous full-text video."""
    import logging
    import sys

    from app.config import settings
    from app.services.ingest import run_ingest
    from app.tasks.pipeline import run_generation_from_audio, run_tts_only

    _log = logging.getLogger(__name__)

    def _emit(level: str, message: str, *args: object) -> None:
        rendered = message % args
        getattr(_log, level)(rendered)
        print(rendered, file=sys.stderr, flush=True)

    try:
        sentence_list = _parse_sentence_list(sentences)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid sentences JSON") from exc

    if not sentence_list:
        raise HTTPException(status_code=422, detail="sentences must not be empty")

    full_text = _join_sentences_for_tts(sentence_list, language)
    if not full_text:
        raise HTTPException(status_code=422, detail="sentences must not be empty")

    if avatar_file is not None:
        video = _avatar_upload_metadata(avatar_file)
    else:
        avatar_path = settings.default_avatar_video
        if avatar_path.exists():
            video = run_ingest(str(avatar_path))
        else:
            video = _default_avatar_metadata()

    resolved_speaker = speaker_id
    if not resolved_speaker:
        speaker_path = profile_store.resolve_speaker_wav()
        if speaker_path:
            resolved_speaker = str(speaker_path)

    tts_started = time.perf_counter()
    _emit(
        "info",
        "[BATCH] full_text chars=%d sentences=%d",
        len(full_text),
        len(sentence_list),
    )
    audio = run_tts_only(
        "batch_tts_full",
        full_text,
        float(settings.default_fps),
        resolved_speaker,
        tts_api_url=(tts_api_url or "").strip() or None,
        language=language,
        emotion=emotion,
        speed=speed,
    )
    _emit(
        "info",
        "[BATCH] TTS full duration=%.2fs audio=%s",
        time.perf_counter() - tts_started,
        audio.audio_path,
    )
    subtitle_segments = _build_subtitle_segments(
        sentence_list,
        audio,
        float(settings.default_fps),
    )

    task_id = new_id("gen")
    store.create(task_id)
    render_started = time.perf_counter()
    result = run_generation_from_audio(task_id=task_id, video=video, audio=audio)
    _emit(
        "info",
        "[BATCH] render full task_id=%s duration=%.2fs url=%s",
        task_id,
        time.perf_counter() - render_started,
        result.video_url,
    )

    _emit("info", "[BATCH] completed merged_url=%s", result.video_url)
    duration_sec = _audio_duration_seconds(audio, float(settings.default_fps))
    return {
        "status": "completed",
        "video_urls": [result.video_url],
        "subtitle_segments": [segment.model_dump() for segment in subtitle_segments],
        "duration_sec": duration_sec,
    }
