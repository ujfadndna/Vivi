"""视频合成（模块 6）。

对应 docs/digital-human-design.md「### 6. 视频合成（FFmpeg）」。
用 imageio-ffmpeg 自带的 ffmpeg 二进制（系统未装 ffmpeg），
把前景 RGBA 序列叠到背景序列上，并合入音频，输出 MP4。

纯工程实现，无模型；同时注册 local / mock 两个名字指向同一实现。
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

import imageio_ffmpeg

from app import storage
from app.config import settings
from app.schemas import (
    AudioWithTimestamps,
    BackgroundFrames,
    CompositeResult,
    FrameSequence,
    SegmentedFrames,
)
from app.services.base import get_backend, register


class CompositeBackend(ABC):
    @abstractmethod
    def run(
        self,
        fg: SegmentedFrames | FrameSequence,
        bg: BackgroundFrames | None,
        audio: AudioWithTimestamps,
        fps: float,
        task_id: str,
    ) -> CompositeResult:
        ...


@register("composite", "local")
@register("composite", "mock")
class FFmpegComposite(CompositeBackend):
    def run(
        self,
        fg: SegmentedFrames | FrameSequence,
        bg: BackgroundFrames | None,
        audio: AudioWithTimestamps,
        fps: float,
        task_id: str,
    ) -> CompositeResult:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        audio_path = Path(audio.audio_path).as_posix()
        out = storage.output_dir() / f"{task_id}.mp4"
        out_path = out.as_posix()

        if isinstance(fg, FrameSequence) or getattr(fg, "full_frame", False):
            frame_pattern = (Path(fg.output_frames_dir) / "%08d.png").as_posix()
            cmd = [
                ffmpeg,
                "-y",
                "-framerate", str(fps),
                "-i", frame_pattern,
                "-i", audio_path,
                "-map", "0:v",
                "-map", "1:a",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "23",
                "-preset", "fast",
                "-c:a", "aac",
                "-shortest",
                out_path,
            ]
            self._run_ffmpeg(cmd)
            return _result_from_file(out, fg.num_frames, fps)

        if bg is None:
            raise ValueError("BackgroundFrames is required for alpha compositing")

        # 帧序列路径统一用正斜杠，避免 Windows 下 %08d 反斜杠转义问题
        bg_pattern = (Path(bg.background_frames_dir) / "%08d.png").as_posix()
        fg_pattern = (Path(fg.foreground_frames_dir) / "%08d.png").as_posix()

        cmd = [
            ffmpeg,
            "-y",
            "-framerate", str(fps),
            "-i", bg_pattern,                              # input 0：背景
            "-framerate", str(fps),
            "-i", fg_pattern,                              # input 1：前景（带 alpha）
            "-i", audio_path,                              # input 2：音频
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
            "-map", "[v]",
            "-map", "2:a",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "fast",
            "-c:a", "aac",
            "-shortest",
            out_path,
        ]

        self._run_ffmpeg(cmd)
        return _result_from_file(out, fg.num_frames, fps)

    @staticmethod
    def _run_ffmpeg(cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            # 把 ffmpeg stderr 解码后并入异常信息，便于排查
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise RuntimeError(f"ffmpeg 合成失败：{stderr}") from e


def run_composite(
    fg: SegmentedFrames | FrameSequence,
    bg: BackgroundFrames | None,
    audio: AudioWithTimestamps,
    fps: float,
    task_id: str,
) -> CompositeResult:
    return get_backend("composite", settings.composite_backend)().run(
        fg, bg, audio, fps, task_id
    )


def _result_from_file(out: Path, num_frames: int, fps: float) -> CompositeResult:
    return CompositeResult(
        video_path=str(out),
        size_mb=round(out.stat().st_size / 1e6, 1),
        duration_sec=num_frames / fps,
    )
