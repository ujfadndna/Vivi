"""背景处理（模块 5）。

对应 docs/digital-human-design.md「### 5. 背景处理」。
三种模式：static / dynamic_video / generated（generated 为 v1 Mock）。
所有背景帧落盘到 storage.background_dir(task_id)，按 %08d.png 连续编号。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import cv2
import numpy as np

from app import storage
from app.config import settings
from app.schemas import BackgroundFrames, BackgroundMode, Resolution
from app.services.base import get_backend, register


def _gradient_placeholder(width: int, height: int) -> np.ndarray:
    """生成一张竖直渐变占位图（BGR），从上到下由深变浅。"""
    # 竖直方向 0~255 渐变，广播到三通道
    column = np.linspace(0, 255, height, dtype=np.uint8).reshape(height, 1)
    gray = np.repeat(column, width, axis=1)            # (height, width)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)      # (height, width, 3)


def _resize(img: np.ndarray, resolution: Resolution) -> np.ndarray:
    """按 resolution=(width, height) resize，cv2.resize 接收 (width, height)。"""
    width, height = resolution
    return cv2.resize(img, (width, height))


def _generated_placeholder(
    width: int, height: int, description: Optional[str]
) -> np.ndarray:
    """generated 模式 Mock：纯灰 (BGR 200,200,200)，可叠加 description 文字提示。"""
    img = np.full((height, width, 3), 200, dtype=np.uint8)
    if description:
        cv2.putText(
            img,
            description,
            (20, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (80, 80, 80),
            2,
            cv2.LINE_AA,
        )
    return img


class BackgroundBackend(ABC):
    @abstractmethod
    def run(
        self,
        mode: BackgroundMode,
        num_frames: int,
        resolution: Resolution,
        task_id: str,
        bg_image_path: Optional[str] = None,
        description: Optional[str] = None,
    ) -> BackgroundFrames:
        ...


@register("background", "mock")
class MockBackground(BackgroundBackend):
    def run(
        self,
        mode: BackgroundMode,
        num_frames: int,
        resolution: Resolution,
        task_id: str,
        bg_image_path: Optional[str] = None,
        description: Optional[str] = None,
    ) -> BackgroundFrames:
        width, height = resolution
        out_dir = storage.background_dir(task_id)

        # 计算每一帧背景图，统一为 num_frames 张
        if mode == BackgroundMode.static:
            frames = self._static_frames(num_frames, resolution, bg_image_path)
        elif mode == BackgroundMode.dynamic_video:
            frames = self._dynamic_frames(num_frames, resolution, bg_image_path)
        else:  # BackgroundMode.generated
            base = _generated_placeholder(width, height, description)
            frames = [base] * num_frames

        # 落盘：00000000.png 起连续编号
        for i, frame in enumerate(frames):
            cv2.imwrite(str(out_dir / f"{i:08d}.png"), frame)

        return BackgroundFrames(
            background_frames_dir=str(out_dir),
            num_frames=num_frames,
        )

    def _static_frames(
        self,
        num_frames: int,
        resolution: Resolution,
        bg_image_path: Optional[str],
    ) -> list[np.ndarray]:
        """单张背景图复制成 num_frames 帧；无图则用渐变占位。"""
        width, height = resolution
        img = cv2.imread(bg_image_path) if bg_image_path else None
        if img is None:
            img = _gradient_placeholder(width, height)
        else:
            img = _resize(img, resolution)
        return [img] * num_frames

    def _dynamic_frames(
        self,
        num_frames: int,
        resolution: Resolution,
        bg_image_path: Optional[str],
    ) -> list[np.ndarray]:
        """读视频帧，循环/截断到 num_frames，每帧 resize；读失败则回退渐变占位。"""
        width, height = resolution
        source: list[np.ndarray] = []

        if bg_image_path:
            cap = cv2.VideoCapture(bg_image_path)
            try:
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    source.append(_resize(frame, resolution))
            finally:
                cap.release()

        if not source:
            # 无视频或读取失败：回退到渐变占位单图
            source = [_gradient_placeholder(width, height)]

        # 循环填充 / 截断到 num_frames
        return [source[i % len(source)] for i in range(num_frames)]


def run_background(
    mode: BackgroundMode,
    num_frames: int,
    resolution: Resolution,
    task_id: str,
    bg_image_path: Optional[str] = None,
    description: Optional[str] = None,
) -> BackgroundFrames:
    return get_backend("background", settings.background_backend)().run(
        mode, num_frames, resolution, task_id, bg_image_path, description
    )
