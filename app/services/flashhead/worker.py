"""Line-oriented persistent SoulX-FlashHead inference worker."""
from __future__ import annotations

import base64
import json
import os
import sys
import sysconfig
import time
import traceback
from pathlib import Path
from typing import Any


_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
_REPO_DIR = os.environ.get("FLASHHEAD_REPO") or ""

_site_packages = [p for p in sys.path if "site-packages" in p or "dist-packages" in p]
_stdlib_roots = {
    str(Path(path).resolve()).lower()
    for path in (sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib"))
    if path
}
_stdlib = [
    p
    for p in sys.path
    if p
    and "site-packages" not in p
    and "dist-packages" not in p
    and (
        "lib/python3" in p.lower().replace("\\", "/")
        or str(Path(p).resolve()).lower() in _stdlib_roots
        or str(Path(p).resolve()).lower().startswith(
            tuple(root + os.sep.lower() for root in _stdlib_roots)
        )
        or Path(p).name.lower() == "dlls"
        or Path(p).suffix.lower() == ".zip"
    )
]

sys.path.clear()
if _PROJECT_ROOT:
    sys.path.append(_PROJECT_ROOT)
if _REPO_DIR:
    sys.path.append(_REPO_DIR)
for _path in [*_site_packages, *_stdlib]:
    if _path not in sys.path:
        sys.path.append(_path)


import cv2
import librosa
import numpy as np


class PersistentFlashHeadWorker:
    def __init__(self) -> None:
        self.repo_dir = Path(_REPO_DIR).expanduser().resolve() if _REPO_DIR else Path.cwd()
        self.ckpt_dir = str(
            Path(os.environ.get("FLASHHEAD_CKPT_DIR", "./models/SoulX-FlashHead-1_3B"))
            .expanduser()
            .resolve()
        )
        self.wav2vec_dir = str(
            Path(os.environ.get("FLASHHEAD_WAV2VEC_DIR", "./models/wav2vec2-base-960h"))
            .expanduser()
            .resolve()
        )
        self.model_type = os.environ.get("FLASHHEAD_MODEL_TYPE", "lite")
        self.stream_frames = _env_bool("FLASHHEAD_STREAM_FRAMES", True)
        self._pipeline: Any = None
        self._infer_params: Any = None
        self._base_image_path: str | None = None

        if _REPO_DIR:
            os.chdir(self.repo_dir)
        self._add_ffmpeg_to_path()
        self._load_models()

    def _load_models(self) -> None:
        from flash_head.inference import get_infer_params, get_pipeline

        _log(
            "[FlashHead] loading pipeline "
            f"model_type={self.model_type} ckpt_dir={self.ckpt_dir}"
        )
        t0 = time.perf_counter()
        self._pipeline = get_pipeline(
            world_size=1,
            ckpt_dir=self.ckpt_dir,
            model_type=self.model_type,
            wav2vec_dir=self.wav2vec_dir,
        )
        self._infer_params = get_infer_params()
        _log(f"[FlashHead] pipeline ready in {time.perf_counter() - t0:.1f}s")

    def run_warmup(self, image_path: str | Path) -> bool:
        from flash_head.inference import get_base_data

        resolved = Path(image_path).expanduser().resolve()
        if not resolved.is_file():
            _log(f"[WARMUP] image_path is not a file: {resolved}")
            return False

        t0 = time.perf_counter()
        get_base_data(
            self._pipeline,
            cond_image_path_or_dir=str(resolved),
            base_seed=42,
            use_face_crop=False,
        )
        self._base_image_path = str(resolved)
        _log(f"[WARMUP] image prepared in {time.perf_counter() - t0:.1f}s: {resolved}")
        return True

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        task_id = str(job["task_id"])
        output_dir = Path(job["output_dir"]).expanduser().resolve()
        try:
            image_path = Path(job["image_path"]).expanduser().resolve()
            audio_path = Path(job["audio_path"]).expanduser().resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"FlashHead input image does not exist: {image_path}")
            if not audio_path.is_file():
                raise FileNotFoundError(f"FlashHead input audio does not exist: {audio_path}")

            if self._base_image_path != str(image_path):
                ok = self.run_warmup(image_path)
                if not ok:
                    raise RuntimeError(f"FlashHead failed to prepare image: {image_path}")

            output_dir.mkdir(parents=True, exist_ok=True)
            _clear_png_frames(output_dir)
            num_frames = self._run_inference(
                task_id=task_id,
                audio_path=audio_path,
                output_dir=output_dir,
            )
            return {
                "task_id": task_id,
                "status": "ok",
                "output_dir": str(output_dir),
                "num_frames": num_frames,
                "error_msg": "",
            }
        except Exception:
            return {
                "task_id": task_id,
                "status": "error",
                "output_dir": str(output_dir),
                "num_frames": 0,
                "error_msg": traceback.format_exc(),
            }

    def run_streaming_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """
        Accept a type="streaming_job" payload with base64 int16 PCM chunks.

        The current line-oriented worker protocol sends one complete job per JSON
        line, so chunks are decoded and concatenated before reusing the same
        sliding-window embedding and chunk rendering path as file-based jobs.
        """
        task_id = str(job["task_id"])
        output_dir = Path(job["output_dir"]).expanduser().resolve()
        try:
            image_path = Path(job["image_path"]).expanduser().resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"FlashHead input image does not exist: {image_path}")

            if self._base_image_path != str(image_path):
                ok = self.run_warmup(image_path)
                if not ok:
                    raise RuntimeError(f"FlashHead failed to prepare image: {image_path}")

            audio_array = _pcm_chunks_to_float32(job.get("chunks"))

            output_dir.mkdir(parents=True, exist_ok=True)
            _clear_png_frames(output_dir)
            num_frames = self._run_inference_from_array(
                task_id=task_id,
                audio_array=audio_array,
                output_dir=output_dir,
            )
            return {
                "task_id": task_id,
                "status": "ok",
                "output_dir": str(output_dir),
                "num_frames": num_frames,
                "error_msg": "",
            }
        except Exception:
            return {
                "task_id": task_id,
                "status": "error",
                "output_dir": str(output_dir),
                "num_frames": 0,
                "error_msg": traceback.format_exc(),
            }

    def _run_inference(self, task_id: str, audio_path: Path, output_dir: Path) -> int:
        sample_rate = int(_param(self._infer_params, "sample_rate", 16000))
        t0 = time.perf_counter()
        audio_array, _ = librosa.load(str(audio_path), sr=sample_rate, mono=True)
        audio_array = np.asarray(audio_array, dtype=np.float32)
        _log(
            f"[FTIMING] audio_load({len(audio_array) / sample_rate:.2f}s): "
            f"{time.perf_counter() - t0:.2f}s"
        )
        return self._run_inference_from_array(
            task_id=task_id,
            audio_array=audio_array,
            output_dir=output_dir,
        )

    def _run_inference_from_array(
        self,
        task_id: str,
        audio_array: np.ndarray,
        output_dir: Path,
    ) -> int:
        import torch
        from contextlib import redirect_stdout
        from flash_head.inference import get_audio_embedding, run_pipeline

        sample_rate = int(_param(self._infer_params, "sample_rate", 16000))
        tgt_fps = int(_param(self._infer_params, "tgt_fps", 25))
        frame_num = int(_param(self._infer_params, "frame_num", 33))
        motion_frames_num = int(_param(self._infer_params, "motion_frames_num", 9))
        slice_len = frame_num - motion_frames_num
        if slice_len <= 0:
            raise RuntimeError(
                "Invalid FlashHead infer params: "
                f"frame_num={frame_num}, motion_frames_num={motion_frames_num}"
            )

        samples_frame = frame_num * sample_rate // tgt_fps
        samples_slice = slice_len * sample_rate // tgt_fps
        if samples_frame <= 0 or samples_slice <= 0:
            raise RuntimeError(
                "Invalid FlashHead audio slicing params: "
                f"sample_rate={sample_rate}, tgt_fps={tgt_fps}, frame_num={frame_num}, "
                f"slice_len={slice_len}"
            )

        audio_array = np.asarray(audio_array, dtype=np.float32)

        if len(audio_array) < samples_frame:
            audio_array = np.pad(audio_array, (0, samples_frame - len(audio_array)))
        rem = (len(audio_array) - samples_frame) % samples_slice
        if rem > 0:
            audio_array = np.pad(audio_array, (0, samples_slice - rem))

        t0 = time.perf_counter()
        audio_emb = get_audio_embedding(self._pipeline, audio_array)
        total_audio_frames = int(audio_emb.shape[1])
        _log(
            f"[FTIMING] audio_embed({total_audio_frames}f): "
            f"{time.perf_counter() - t0:.2f}s"
        )

        n_chunks = max(1, (total_audio_frames - frame_num) // slice_len + 1)
        frame_index = 0
        for chunk_index in range(n_chunks):
            start = chunk_index * slice_len
            emb_chunk = audio_emb[:, start : start + frame_num].contiguous()
            t0 = time.perf_counter()
            with torch.no_grad(), redirect_stdout(sys.stderr):
                video = run_pipeline(self._pipeline, emb_chunk)
            if chunk_index > 0:
                video = video[motion_frames_num:]
            video_np = _to_numpy_uint8(video)
            _log(
                f"[FTIMING] chunk_{chunk_index}({len(video_np)}f): "
                f"{time.perf_counter() - t0:.2f}s"
            )

            written = self._write_frames_and_events(
                task_id=task_id,
                frames_rgb=video_np,
                start_index=frame_index,
                output_dir=output_dir,
            )
            frame_index += written

        self._write_event(
            {
                "type": "completed",
                "task_id": task_id,
                "output_dir": str(output_dir),
                "num_frames": frame_index,
            }
        )
        return frame_index

    def _write_frames_and_events(
        self,
        task_id: str,
        frames_rgb: np.ndarray,
        start_index: int,
        output_dir: Path,
    ) -> int:
        event_frames: list[str] = []
        for offset, frame_rgb in enumerate(frames_rgb):
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            frame_path = output_dir / f"{start_index + offset:08d}.png"
            if not cv2.imwrite(str(frame_path), frame_bgr):
                raise RuntimeError(f"Failed to write FlashHead frame: {frame_path}")
            if self.stream_frames:
                ok, jpg = cv2.imencode(
                    ".jpg",
                    frame_bgr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 80],
                )
                if ok:
                    event_frames.append(base64.b64encode(jpg.tobytes()).decode("ascii"))

        if event_frames:
            self._write_event(
                {
                    "type": "frame_batch",
                    "task_id": task_id,
                    "start_index": start_index,
                    "frames": event_frames,
                    "mime": "image/jpeg",
                }
            )
        return int(len(frames_rgb))

    def _write_event(self, event: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps({"event": event}, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _add_ffmpeg_to_path(self) -> None:
        try:
            import imageio_ffmpeg

            ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


def _param(params: Any, name: str, default: Any) -> Any:
    if isinstance(params, dict):
        return params.get(name, default)
    return getattr(params, name, default)


def _to_numpy_uint8(video: Any) -> np.ndarray:
    if hasattr(video, "detach"):
        video = video.detach()
    if hasattr(video, "cpu"):
        video = video.cpu()
    video_np = np.asarray(video)
    if video_np.dtype != np.uint8:
        video_np = np.clip(video_np, 0, 255).astype(np.uint8)
    if video_np.ndim != 4 or video_np.shape[-1] != 3:
        raise RuntimeError(f"Unexpected FlashHead video shape: {video_np.shape}")
    return np.ascontiguousarray(video_np)


def _pcm_chunks_to_float32(chunks: Any) -> np.ndarray:
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("streaming_job requires non-empty chunks")

    arrays: list[np.ndarray] = []
    saw_eof = False
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"streaming_job chunk #{index} must be an object")
        pcm_b64 = chunk.get("pcm_b64")
        if pcm_b64:
            try:
                pcm_bytes = base64.b64decode(str(pcm_b64), validate=True)
            except Exception as exc:
                raise ValueError(f"Invalid base64 PCM in chunk #{index}") from exc
            if len(pcm_bytes) % 2 != 0:
                raise ValueError(f"PCM chunk #{index} has odd byte length")
            if pcm_bytes:
                arrays.append(
                    np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768.0
                )
        if bool(chunk.get("eof")):
            saw_eof = True

    if not saw_eof:
        raise ValueError("streaming_job missing eof chunk")
    if not arrays:
        raise ValueError("streaming_job contains no PCM audio")
    return np.concatenate(arrays).astype(np.float32, copy=False)


def _clear_png_frames(output_dir: Path) -> None:
    for frame_path in output_dir.glob("*.png"):
        frame_path.unlink()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _write_result(result: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        worker = PersistentFlashHeadWorker()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1

    warmup_image = os.environ.get("FLASHHEAD_WARMUP_IMAGE")
    if warmup_image:
        t0 = time.perf_counter()
        try:
            ok = worker.run_warmup(warmup_image)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            ok = False
        _log(
            f"[WARMUP] env warmup status={'ok' if ok else 'failed'} "
            f"elapsed={time.perf_counter() - t0:.1f}s"
        )

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        job: dict[str, Any] | None = None
        try:
            job = json.loads(line)
            if job.get("type") == "warmup":
                t0 = time.perf_counter()
                ok = worker.run_warmup(job["image_path"])
                result = {
                    "task_id": job.get("task_id", "warmup"),
                    "status": "ok" if ok else "error",
                    "elapsed_sec": round(time.perf_counter() - t0, 3),
                    "error_msg": "" if ok else "warmup failed",
                }
            elif job.get("type") == "streaming_job":
                result = worker.run_streaming_job(job)
            else:
                result = worker.run_job(job)
        except Exception:
            result = {
                "task_id": job.get("task_id") if job is not None else None,
                "status": "error",
                "output_dir": "",
                "num_frames": 0,
                "error_msg": traceback.format_exc(),
            }
        _write_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
