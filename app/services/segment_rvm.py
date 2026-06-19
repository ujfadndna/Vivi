"""RVM 真实人像分割后端。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import storage
from app.config import settings
from app.schemas import FrameSequence, SegmentedFrames
from app.services.base import register
from app.services.segment import SegmentBackend

_INSTALL_HINT = (
    "请先查看 requirements-segment.txt 安装真实分割可选依赖，"
    "并确认 RVM 权重已放到 RVM_CHECKPOINT，或当前环境可访问 "
    "torch.hub 的 PeterL1n/RobustVideoMatting。"
)

_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


@register("segment", "local")
class RVMSegment(SegmentBackend):
    def run(self, frames: FrameSequence, task_id: str) -> SegmentedFrames:
        if frames.num_frames < 0:
            raise ValueError("RVM 分割输入无效：frames.num_frames 不能为负数")

        src_dir = Path(frames.output_frames_dir)
        if not src_dir.is_dir():
            raise FileNotFoundError(f"RVM 输入帧目录不存在：{src_dir}")

        seg_root = storage.segment_dir(task_id)
        fg_dir = seg_root / "fg"
        mask_dir = seg_root / "mask"
        fg_dir.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)

        if frames.num_frames == 0:
            return SegmentedFrames(
                foreground_frames_dir=str(fg_dir),
                mask_dir=str(mask_dir),
                num_frames=0,
            )

        model, torch, device, use_half = _load_model()
        rec: list[Any] = [None] * 4

        with torch.inference_mode():
            for i in range(frames.num_frames):
                name = f"{i:08d}.png"
                frame_path = src_dir / name
                frame_bgr = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                if frame_bgr is None:
                    raise FileNotFoundError(f"缺少输入帧：{frame_path}")

                height, width = frame_bgr.shape[:2]
                src = _frame_to_tensor(torch, frame_bgr, device, use_half)
                downsample_ratio = _downsample_ratio(height, width)
                fgr, pha, rec = _infer_frame(model, src, rec, downsample_ratio)

                fgr_rgb = _tensor_to_rgb(fgr, height, width)
                mask = _tensor_to_mask(pha, height, width)
                rgba = np.dstack((fgr_rgb, mask))
                bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)

                if not cv2.imwrite(str(fg_dir / name), bgra):
                    raise RuntimeError(f"RVM 前景帧写入失败：{fg_dir / name}")
                if not cv2.imwrite(str(mask_dir / name), mask):
                    raise RuntimeError(f"RVM mask 写入失败：{mask_dir / name}")

        return SegmentedFrames(
            foreground_frames_dir=str(fg_dir),
            mask_dir=str(mask_dir),
            num_frames=frames.num_frames,
        )


def _load_model() -> tuple[Any, Any, Any, bool]:
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(f"本地 RVM 分割依赖未安装：缺少 torch。{_INSTALL_HINT}") from exc

    variant = settings.rvm_variant.strip().lower()
    if variant not in {"mobilenetv3", "resnet50"}:
        raise ValueError("RVM_VARIANT 仅支持 mobilenetv3 或 resnet50")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_half = device.type == "cuda"
    checkpoint = Path(settings.rvm_checkpoint).expanduser()
    precision = "fp16" if use_half else "fp32"

    if checkpoint.exists() and not checkpoint.is_file():
        raise RuntimeError(f"RVM_CHECKPOINT 不是文件：{checkpoint}")

    source_key = str(checkpoint.resolve()) if checkpoint.is_file() else "torch.hub"
    cache_key = (variant, source_key, f"{device.type}:{precision}")
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key], torch, device, use_half

    try:
        if checkpoint.is_file():
            model = _load_from_checkpoint(torch, checkpoint, variant, device)
        else:
            model = _load_from_hub(torch, variant)
    except Exception as exc:
        raise RuntimeError(
            "RVM 模型加载失败：请确认 checkpoint、RVM 源码或网络访问可用。"
            f"当前 RVM_VARIANT={variant!r}，RVM_CHECKPOINT={str(checkpoint)!r}。"
            f"{_INSTALL_HINT}"
        ) from exc

    model = model.to(device)
    if use_half:
        model = model.half()
    model.eval()

    _MODEL_CACHE[cache_key] = model
    return model, torch, device, use_half


def _load_from_checkpoint(
    torch: Any,
    checkpoint: Path,
    variant: str,
    device: Any,
) -> Any:
    jit_error: Exception | None = None
    try:
        return torch.jit.load(str(checkpoint), map_location=device)
    except Exception as exc:
        jit_error = exc

    try:
        from app.services.rvm.model import MattingNetwork
    except Exception as exc:
        raise RuntimeError(
            "RVM checkpoint 不是 TorchScript，加载 state_dict 需要 RVM 模型定义。"
            f"TorchScript 加载错误：{jit_error}"
        ) from exc

    checkpoint_obj = _torch_load(torch, checkpoint, device)
    state_dict = _extract_state_dict(checkpoint_obj)
    model = MattingNetwork(variant=variant)
    model.load_state_dict(state_dict)
    return model


def _load_from_hub(torch: Any, variant: str) -> Any:
    try:
        return torch.hub.load("PeterL1n/RobustVideoMatting", variant, trust_repo=True)
    except TypeError:
        return torch.hub.load("PeterL1n/RobustVideoMatting", variant)


def _torch_load(torch: Any, checkpoint: Path, device: Any) -> Any:
    try:
        return torch.load(str(checkpoint), map_location=device, weights_only=True)
    except TypeError:
        return torch.load(str(checkpoint), map_location=device)


def _extract_state_dict(checkpoint_obj: Any) -> dict[str, Any]:
    if hasattr(checkpoint_obj, "state_dict"):
        checkpoint_obj = checkpoint_obj.state_dict()

    if not isinstance(checkpoint_obj, dict):
        raise RuntimeError("RVM checkpoint 不是可识别的 state_dict")

    for key in ("state_dict", "model_state_dict", "model", "net"):
        value = checkpoint_obj.get(key)
        if hasattr(value, "state_dict"):
            value = value.state_dict()
        if isinstance(value, dict):
            checkpoint_obj = value
            break

    if not all(isinstance(key, str) for key in checkpoint_obj):
        raise RuntimeError("RVM state_dict key 格式无效")

    if all(key.startswith("module.") for key in checkpoint_obj):
        return {key.removeprefix("module."): value for key, value in checkpoint_obj.items()}
    return checkpoint_obj


def _frame_to_tensor(
    torch: Any,
    frame_bgr: np.ndarray,
    device: Any,
    use_half: bool,
) -> Any:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    frame_rgb = np.ascontiguousarray(frame_rgb)
    dtype = torch.float16 if use_half else torch.float32
    tensor = torch.from_numpy(frame_rgb).permute(2, 0, 1).unsqueeze(0)
    return tensor.to(device=device, dtype=dtype).div_(255.0)


def _infer_frame(
    model: Any,
    src: Any,
    rec: list[Any],
    downsample_ratio: float,
) -> tuple[Any, Any, list[Any]]:
    output = model(src, *rec, downsample_ratio)
    if not isinstance(output, (tuple, list)) or len(output) < 6:
        raise RuntimeError("RVM 推理输出格式无效，预期 fgr、pha 和 4 个 recurrent state")
    return output[0], output[1], list(output[2:6])


def _tensor_to_rgb(tensor: Any, height: int, width: int) -> np.ndarray:
    arr = tensor.detach().float().clamp(0, 1).cpu().numpy()
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 3 and arr.shape[0] == 3:
        arr = np.transpose(arr, (1, 2, 0))
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise RuntimeError(f"RVM fgr 输出维度无效：{arr.shape}")

    rgb = np.rint(arr * 255.0).astype(np.uint8)
    if rgb.shape[:2] != (height, width):
        rgb = cv2.resize(rgb, (width, height), interpolation=cv2.INTER_LINEAR)
    return rgb


def _tensor_to_mask(tensor: Any, height: int, width: int) -> np.ndarray:
    arr = tensor.detach().float().clamp(0, 1).cpu().numpy()
    arr = np.squeeze(arr)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        raise RuntimeError(f"RVM alpha 输出维度无效：{arr.shape}")

    mask = np.rint(arr * 255.0).astype(np.uint8)
    if mask.shape != (height, width):
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_LINEAR)
    return mask


def _downsample_ratio(height: int, width: int) -> float:
    short_side = min(height, width)
    if short_side >= 720:
        return 0.25
    if short_side >= 512:
        return 0.375
    return 0.5
