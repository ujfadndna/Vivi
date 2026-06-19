from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a looping idle avatar MP4.")
    parser.add_argument("--input", default="./workspace/avatar/default.png", help="Avatar image path.")
    parser.add_argument("--output", default="./workspace/avatar/idle.mp4", help="Output MP4 path.")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds.")
    parser.add_argument("--fps", type=float, default=25.0, help="Frames per second.")
    parser.add_argument(
        "--mode",
        choices=("flashhead", "synthetic"),
        default="flashhead",
        help="flashhead uses the real avatar renderer; synthetic is an OpenCV fallback.",
    )
    parser.add_argument(
        "--audio-level",
        type=float,
        default=0.0015,
        help="Low-level idle audio amplitude used by FlashHead mode.",
    )
    parser.add_argument(
        "--eye-center",
        default="0.575,0.345",
        help="Synthetic fallback eye center as normalized x,y coordinates.",
    )
    parser.add_argument(
        "--eye-size",
        default="0.155,0.035",
        help="Synthetic fallback eye size as normalized width,height.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "flashhead":
        render_flashhead_idle_video(
            image_path=input_path,
            output_path=output_path,
            duration_sec=args.duration,
            fps=args.fps,
            audio_level=args.audio_level,
        )
        print(output_path)
        return

    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Unable to read input image: {input_path}")

    eye_center = _parse_pair(args.eye_center, "--eye-center")
    eye_size = _parse_pair(args.eye_size, "--eye-size")
    render_synthetic_idle_video(
        image=image,
        output_path=output_path,
        duration_sec=args.duration,
        fps=args.fps,
        eye_center=eye_center,
        eye_size=eye_size,
    )
    print(output_path)


def render_flashhead_idle_video(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    fps: float,
    audio_level: float,
) -> None:
    """Render idle video through Her's real FlashHead pipeline."""
    import app.services.flashhead.real  # noqa: F401 - registers FlashHead as musetalk/local.

    from app.config import settings
    from app.schemas import AudioWithTimestamps, VideoMetadata
    from app.storage import new_id
    from app.tasks.pipeline import run_generation_from_audio

    image_path = image_path.expanduser().resolve()
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"Unable to read input image: {image_path}")

    height, width = image.shape[:2]
    task_id = new_id("idle")
    audio_path = output_path.with_suffix(".idle.wav")
    _write_idle_audio(audio_path, duration_sec=duration_sec, sample_rate=16000, level=audio_level)

    old_default_image = settings.default_avatar_image
    try:
        settings.default_avatar_image = image_path
        video = VideoMetadata(
            video_id="idle_avatar_image",
            fps=float(fps),
            num_frames=1,
            duration_sec=1.0 / float(fps),
            resolution=(width, height),
            face_bbox=(0, 0, width, height),
            frames_dir=str(image_path.parent),
            status="ready",
        )
        audio = AudioWithTimestamps(
            audio_id=f"{task_id}_idle_audio",
            audio_path=str(audio_path),
            duration_sec=float(duration_sec),
            duration_frames=max(1, round(float(duration_sec) * float(fps))),
            sample_rate=16000,
            phoneme_intervals=[],
        )
        result = run_generation_from_audio(task_id=task_id, video=video, audio=audio)
    finally:
        settings.default_avatar_image = old_default_image

    rendered = Path(result.video_path)
    if not rendered.is_file() or rendered.stat().st_size == 0:
        raise RuntimeError(f"FlashHead idle render did not produce a valid MP4: {rendered}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rendered, output_path)


def _write_idle_audio(
    path: Path,
    duration_sec: float,
    sample_rate: int,
    level: float,
) -> None:
    """Write a near-silent waveform with gentle breath-like energy changes."""
    frame_count = max(1, int(round(duration_sec * sample_rate)))
    t = np.arange(frame_count, dtype=np.float32) / float(sample_rate)
    envelope = 0.45 + 0.55 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 0.22 * t))
    tone = np.sin(2.0 * np.pi * 110.0 * t) * 0.18
    noise = np.sin(2.0 * np.pi * 2.1 * t) * 0.04
    samples = np.clip((tone + noise) * envelope * float(level), -0.03, 0.03)
    pcm = (samples * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def render_synthetic_idle_video(
    image: np.ndarray,
    output_path: Path,
    duration_sec: float,
    fps: float,
    eye_center: tuple[float, float],
    eye_size: tuple[float, float],
) -> None:
    frame_count = max(1, int(round(duration_sec * fps)))
    height, width = image.shape[:2]

    with tempfile.TemporaryDirectory(prefix="her_idle_") as tmp:
        raw_path = Path(tmp) / "idle_raw.mp4"
        writer = cv2.VideoWriter(
            str(raw_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise RuntimeError(f"Unable to create temporary video: {raw_path}")

        try:
            for index in range(frame_count):
                progress = index / frame_count
                frame = _animate_frame(
                    image=image,
                    progress=progress,
                    eye_center=eye_center,
                    eye_size=eye_size,
                )
                writer.write(frame)
        finally:
            writer.release()

        _encode_browser_mp4(raw_path, output_path, fps)


def _animate_frame(
    image: np.ndarray,
    progress: float,
    eye_center: tuple[float, float],
    eye_size: tuple[float, float],
) -> np.ndarray:
    height, width = image.shape[:2]
    breath = math.sin(progress * math.tau * 2.0)
    drift = math.sin(progress * math.tau)
    scale = 1.0 + 0.006 * breath
    tx = 1.7 * drift
    ty = -3.0 * breath

    matrix = cv2.getRotationMatrix2D((width / 2, height * 0.56), 0.22 * drift, scale)
    matrix[0, 2] += tx
    matrix[1, 2] += ty
    frame = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )

    blink = max(
        _blink_amount(progress, 0.18, 0.045),
        _blink_amount(progress, 0.56, 0.038),
        _blink_amount(progress, 0.83, 0.05),
    )
    if blink > 0:
        frame = _apply_blink(frame, image, eye_center, eye_size, blink)

    # A tiny luminance wave keeps the pre-render from looking frozen between blinks.
    frame = cv2.convertScaleAbs(frame, alpha=1.0 + 0.012 * breath, beta=0)
    return frame


def _blink_amount(progress: float, center: float, width: float) -> float:
    distance = abs(progress - center)
    if distance > width:
        return 0.0
    value = 1.0 - distance / width
    return math.sin(value * math.pi / 2.0) ** 2


def _apply_blink(
    frame: np.ndarray,
    source: np.ndarray,
    eye_center: tuple[float, float],
    eye_size: tuple[float, float],
    amount: float,
) -> np.ndarray:
    height, width = frame.shape[:2]
    cx = int(round(eye_center[0] * width))
    cy = int(round(eye_center[1] * height))
    ew = max(4, int(round(eye_size[0] * width)))
    eh = max(2, int(round(eye_size[1] * height)))
    x1 = max(0, cx - ew // 2)
    x2 = min(width, cx + ew // 2)
    y1 = max(0, cy - eh)
    y2 = min(height, cy + eh)
    if x2 <= x1 or y2 <= y1:
        return frame

    roi = frame[y1:y2, x1:x2].copy()
    src_roi = source[y1:y2, x1:x2]
    skin = cv2.GaussianBlur(src_roi, (0, 0), sigmaX=8, sigmaY=5)
    skin = cv2.convertScaleAbs(skin, alpha=0.82, beta=8)

    mask = np.zeros(roi.shape[:2], dtype=np.float32)
    center = ((x2 - x1) // 2, (y2 - y1) // 2)
    axes = (max(2, (x2 - x1) // 2), max(1, int((y2 - y1) * 0.34)))
    cv2.ellipse(mask, center, axes, 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=3, sigmaY=2)
    mask = np.clip(mask[..., None] * amount, 0.0, 1.0)
    blended = (roi.astype(np.float32) * (1.0 - mask) + skin.astype(np.float32) * mask)

    lid_y = int(round(center[1] + axes[1] * 0.2))
    cv2.line(
        blended,
        (max(0, center[0] - axes[0] + 4), lid_y),
        (min(x2 - x1 - 1, center[0] + axes[0] - 4), lid_y),
        (32, 28, 28),
        max(1, int(2 * amount)),
        cv2.LINE_AA,
    )

    out = frame.copy()
    out[y1:y2, x1:x2] = np.clip(blended, 0, 255).astype(np.uint8)
    return out


def _encode_browser_mp4(raw_path: Path, output_path: Path, fps: float) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(raw_path),
            "-r",
            str(fps),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1000:] or "ffmpeg failed")


def _parse_pair(value: str, name: str) -> tuple[float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise SystemExit(f"{name} must be formatted as x,y")
    try:
        x, y = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise SystemExit(f"{name} must contain numbers") from exc
    return x, y


if __name__ == "__main__":
    main()
