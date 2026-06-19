"""人像分割（RVM）—— Mock 实现。

不接真实 RVM 模型，用居中竖直椭圆生成人像 mask（近似剪影），
使背景替换在合成阶段可见生效。后端可插拔：settings.segment_backend。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import cv2
import numpy as np

from app import storage
from app.config import settings
from app.schemas import FrameSequence, SegmentedFrames
from app.services.base import get_backend, register

_INSTALL_HINT = (
    "请先查看 requirements-segment.txt 安装真实分割可选依赖，"
    "下载 RVM 权重并在 .env 设置 SEGMENT_BACKEND=local / "
    "RVM_CHECKPOINT / RVM_VARIANT。"
)


class SegmentBackend(ABC):
    @abstractmethod
    def run(self, frames: FrameSequence, task_id: str) -> SegmentedFrames: ...


@register("segment", "mock")
class MockSegment(SegmentBackend):
    """用居中椭圆 mask 抠出"人像"，露出四周以便背景替换可见。"""

    def run(self, frames: FrameSequence, task_id: str) -> SegmentedFrames:
        src_dir = storage.Path(frames.output_frames_dir)
        seg_root = storage.segment_dir(task_id)
        fg_dir = seg_root / "fg"
        mask_dir = seg_root / "mask"
        fg_dir.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)

        for i in range(frames.num_frames):
            name = f"{i:08d}.png"
            frame = cv2.imread(str(src_dir / name), cv2.IMREAD_COLOR)
            if frame is None:
                raise FileNotFoundError(f"缺少输入帧：{src_dir / name}")

            mask = self._ellipse_mask(frame.shape[0], frame.shape[1])

            # 前景 RGBA：RGB=原帧，A=mask；cv2 通道顺序为 BGRA
            b, g, r = cv2.split(frame)
            bgra = cv2.merge([b, g, r, mask])

            cv2.imwrite(str(fg_dir / name), bgra)
            cv2.imwrite(str(mask_dir / name), mask)

        return SegmentedFrames(
            foreground_frames_dir=str(fg_dir),
            mask_dir=str(mask_dir),
            num_frames=frames.num_frames,
        )

    @staticmethod
    def _ellipse_mask(height: int, width: int) -> np.ndarray:
        """居中竖直椭圆：约画面中部 60% 宽、90% 高，内 255 外 0，边缘羽化。"""
        mask = np.zeros((height, width), dtype=np.uint8)
        center = (width // 2, height // 2)
        axes = (int(width * 0.30), int(height * 0.45))  # 半轴：直径 ≈ 60%宽 / 90%高
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, thickness=-1)

        # 羽化边缘（核大小取奇数，随画面尺寸缩放）
        k = max(3, (min(height, width) // 50) | 1)
        mask = cv2.GaussianBlur(mask, (k, k), 0)
        return mask


def run_segment(frames: FrameSequence, task_id: str) -> SegmentedFrames:
    if settings.segment_backend == "local":
        try:
            import app.services.segment_rvm  # noqa: F401
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"RVM 分割后端不可用。{_INSTALL_HINT}") from exc

    return get_backend("segment", settings.segment_backend)().run(frames, task_id)
