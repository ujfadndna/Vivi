"""Persistent SoulX-FlashHead worker process manager."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

logger = logging.getLogger(__name__)


class FlashHeadWorkerManager:
    def __init__(self, timeout: float = 600.0) -> None:
        self.timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._start_lock = threading.Lock()
        self._submit_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._proc is not None and self._proc.poll() is None:
                return

            self._responses = queue.Queue()
            script_path = Path(__file__).with_name("worker.py").resolve()
            project_root = Path(__file__).resolve().parents[2]
            repo_dir = Path(settings.flashhead_repo).expanduser().resolve()

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["FLASHHEAD_REPO"] = str(repo_dir)
            env["FLASHHEAD_CKPT_DIR"] = str(
                Path(settings.flashhead_ckpt_dir).expanduser().resolve()
            )
            env["FLASHHEAD_WAV2VEC_DIR"] = str(
                Path(settings.flashhead_wav2vec_dir).expanduser().resolve()
            )
            env["FLASHHEAD_MODEL_TYPE"] = settings.flashhead_model_type
            env["FLASHHEAD_STREAM_FRAMES"] = (
                "1" if settings.flashhead_stream_frames else "0"
            )
            warmup_image = Path(settings.default_avatar_image).expanduser().resolve()
            if warmup_image.exists():
                env["FLASHHEAD_WARMUP_IMAGE"] = str(warmup_image)

            pythonpath_parts = [str(project_root), str(repo_dir)]
            if env.get("PYTHONPATH"):
                pythonpath_parts.append(env["PYTHONPATH"])
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

            try:
                import imageio_ffmpeg

                ffmpeg_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
                env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
            except Exception:
                pass

            self._proc = subprocess.Popen(
                [sys.executable, "-u", str(script_path)],
                cwd=repo_dir if repo_dir.exists() else project_root,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                args=(self._proc,),
                daemon=True,
            )
            self._reader_thread.start()

    def stop(self) -> None:
        with self._start_lock:
            proc = self._proc
            self._proc = None
            if proc is None:
                return

            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass

            if proc.poll() is None:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)

    async def warmup_background(self, image_path: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(
                self._submit_job,
                {"type": "warmup", "image_path": image_path, "task_id": "warmup"},
                180.0,
                False,
            )
        except Exception as exc:  # noqa: BLE001 - warmup must not block startup.
            logger.warning("[WARMUP] FlashHead avatar pre-heat failed: %s", exc)
            raise

        if result.get("status") == "ok":
            print("[WARMUP] FlashHead avatar pre-heated", file=sys.stderr, flush=True)
            return result
        else:
            logger.warning(
                "[WARMUP] FlashHead avatar pre-heat failed: %s",
                result.get("error_msg") or result,
            )
            raise RuntimeError(result.get("error_msg") or f"warmup failed: {result}")

    async def warmup_inference_background(
        self,
        image_path: str,
        duration_sec: float = 2.0,
        fps: float = 25.0,
    ) -> dict[str, Any]:
        """Run one tiny real FlashHead streaming inference to trigger CUDA compile."""
        output_dir = (
            Path(settings.workspace_dir)
            / "processing"
            / "musetalk"
            / "warmup_inference"
        )
        task_id = "warmup_inference"
        pcm = _low_energy_pcm(duration_sec=duration_sec, sample_rate=16000)
        logger.info(
            "[WARMUP] FlashHead inference warmup started duration=%.2fs",
            duration_sec,
        )
        started = time.perf_counter()
        result = await asyncio.to_thread(
            self.stream_tts_to_flashhead,
            task_id,
            image_path,
            str(output_dir),
            fps,
            iter([pcm]),
        )
        elapsed = time.perf_counter() - started
        result["elapsed_sec"] = round(elapsed, 3)
        if result.get("status") != "ok" or int(result.get("num_frames") or 0) <= 0:
            raise RuntimeError(result.get("error_msg") or f"warmup failed: {result}")
        logger.info(
            "[WARMUP] FlashHead inference warmup ok duration=%.2fs frames=%s elapsed=%.2fs",
            duration_sec,
            result.get("num_frames"),
            elapsed,
        )
        return result

    def submit_job(self, job_dict: dict[str, Any]) -> dict[str, Any]:
        return self._submit_job(job_dict, self.timeout)

    def submit_streaming_job(self, job_dict: dict[str, Any]) -> dict[str, Any]:
        return self._submit_job(job_dict, self.timeout)

    def stream_tts_to_flashhead(
        self,
        task_id: str,
        image_path: str,
        output_dir: str,
        fps: float,
        pcm_chunks_iter: Iterator[bytes],
    ) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = []
        for pcm in pcm_chunks_iter:
            if not pcm:
                continue
            chunks.append(
                {
                    "pcm_b64": base64.b64encode(bytes(pcm)).decode("ascii"),
                    "eof": False,
                }
            )
        chunks.append({"pcm_b64": "", "eof": True})

        return self.submit_streaming_job(
            {
                "type": "streaming_job",
                "task_id": task_id,
                "image_path": image_path,
                "output_dir": output_dir,
                "fps": fps,
                "chunks": chunks,
            }
        )

    def _submit_job(
        self,
        job_dict: dict[str, Any],
        timeout: float,
        stop_on_timeout: bool = True,
    ) -> dict[str, Any]:
        with self._submit_lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                raise RuntimeError("FlashHead worker process is not running")
            if proc.stdin is None:
                raise RuntimeError("FlashHead worker stdin is unavailable")

            try:
                proc.stdin.write(json.dumps(job_dict, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(
                    "FlashHead worker process died while accepting a job"
                ) from exc

            deadline = time.monotonic() + timeout
            expected_task_id = job_dict.get("task_id")
            while True:
                if proc.poll() is not None and self._responses.empty():
                    raise RuntimeError(
                        f"FlashHead worker process exited with code {proc.returncode}"
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if stop_on_timeout:
                        self.stop()
                    raise TimeoutError(f"FlashHead worker timed out after {timeout:.0f}s")

                try:
                    result = self._responses.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    continue

                if expected_task_id is not None and result.get("task_id") != expected_task_id:
                    logger.warning(
                        "Ignoring FlashHead worker response for unexpected task_id=%s",
                        result.get("task_id"),
                    )
                    continue
                return result

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Ignoring non-JSON FlashHead worker output: %s", line[:1000])
                continue
            event = payload.get("event")
            if isinstance(event, dict):
                try:
                    from app.services.stream_bus import stream_hub

                    stream_hub.publish(event)
                except Exception:
                    logger.exception("Failed to publish FlashHead stream event")
                continue
            self._responses.put(payload)


worker_manager = FlashHeadWorkerManager()


def _low_energy_pcm(duration_sec: float, sample_rate: int) -> bytes:
    sample_count = max(1, int(duration_sec * sample_rate))
    # Use low-amplitude deterministic audio instead of silence so audio embedding
    # takes the same path as a real request while staying visually unobtrusive.
    amplitude = 384
    period = max(1, sample_rate // 220)
    samples = bytearray(sample_count * 2)
    for index in range(sample_count):
        value = amplitude if (index // (period // 2 or 1)) % 2 == 0 else -amplitude
        offset = index * 2
        samples[offset : offset + 2] = int(value).to_bytes(
            2,
            byteorder="little",
            signed=True,
        )
    return bytes(samples)
