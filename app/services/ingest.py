"""素材接入：视频校验 + 元信息提取 + 抽帧 + 人脸检测。

对应 docs/digital-human-design.md「### 1. 素材接入」。纯 OpenCV 工程，
mock 即真实实现。后端通过注册表可插拔（见 services/base.py）。
"""
from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import cv2

from app import storage
from app.config import settings
from app.schemas import VideoMetadata
from app.services.base import get_backend, register

logger = logging.getLogger(__name__)

_VALID_EXTS = {".mp4", ".mov", ".avi"}


class IngestBackend(ABC):
    @abstractmethod
    def run(self, video_path: str) -> VideoMetadata: ...


@register("ingest", "mock")
class MockIngest(IngestBackend):
    def run(self, video_path: str) -> VideoMetadata:
        # 格式校验
        if Path(video_path).suffix.lower() not in _VALID_EXTS:
            raise ValueError("Format not supported")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError("Cannot read video")

        fps = cap.get(cv2.CAP_PROP_FPS) or float(settings.default_fps)
        reported_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        video_id = storage.new_id("vid")
        frames_dir = storage.video_frames_dir(video_id)

        # 抽帧：边读边写边计数，以实际写出帧数为准（CAP_PROP_FRAME_COUNT 有时不准）
        frames: list = []
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.imwrite(str(frames_dir / f"{idx:08d}.png"), frame)
            frames.append(frame)
            idx += 1
        cap.release()

        num_frames = idx
        if num_frames == 0:
            raise ValueError("Cannot read video")
        if reported_frames and reported_frames != num_frames:
            logger.warning("帧数不一致：报告 %d，实际 %d", reported_frames, num_frames)

        duration_sec = num_frames / fps

        # 时长软提示（不硬失败）
        if not (10.0 <= duration_sec <= 60.0):
            logger.warning("视频时长 %.2fs 不在建议区间 10~60s", duration_sec)

        # 人脸检测：在中间帧取最大人脸，失败则用居中默认框
        mid = frames[num_frames // 2]
        face_bbox = _detect_main_face(mid, width, height)

        return VideoMetadata(
            video_id=video_id,
            fps=fps,
            num_frames=num_frames,
            duration_sec=duration_sec,
            resolution=(width, height),
            face_bbox=face_bbox,
            frames_dir=str(frames_dir),
            status="ready",
        )


def _detect_main_face(frame, width: int, height: int) -> tuple[int, int, int, int]:
    """中间帧检测最大人脸 bbox=(x,y,x+w,y+h)；检测不到则居中默认框。"""
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) > 0:
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return (int(x), int(y), int(x + w), int(y + h))
    # 鲁棒兜底：居中默认框
    return (width // 4, height // 4, width * 3 // 4, height * 3 // 4)


def _ingest_cache_key(video_path: str) -> str | None:
    """以 文件绝对路径+大小+mtime 作为缓存键；文件不存在返回 None。"""
    p = Path(video_path)
    try:
        st = p.stat()
    except OSError:
        return None
    raw = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _ingest_cache_dir() -> Path:
    d = settings.workspace_dir / "ingest_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_ingest_cache(key: str) -> VideoMetadata | None:
    cache_file = _ingest_cache_dir() / f"{key}.json"
    if not cache_file.is_file():
        return None
    try:
        meta = VideoMetadata(**json.loads(cache_file.read_text(encoding="utf-8")))
    except Exception:
        return None
    # 校验抽帧目录仍然有效，否则视为未命中重新抽帧
    first_frame = Path(meta.frames_dir) / "00000000.png"
    if not first_frame.is_file():
        return None
    return meta


def _save_ingest_cache(key: str, meta: VideoMetadata) -> None:
    cache_file = _ingest_cache_dir() / f"{key}.json"
    try:
        cache_file.write_text(
            json.dumps(meta.model_dump(), ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.warning("写入 ingest 缓存失败：%s", cache_file, exc_info=True)


def run_ingest(video_path: str) -> VideoMetadata:
    """抽帧结果按 文件指纹 缓存。同一头像视频（如默认数字人）重复请求时直接复用，
    避免每次重新抽取整段视频帧（实测省去约 20s/请求）。"""
    key = _ingest_cache_key(video_path)
    if key is not None:
        cached = _load_ingest_cache(key)
        if cached is not None:
            return cached

    meta = get_backend("ingest", settings.ingest_backend)().run(video_path)

    if key is not None:
        _save_ingest_cache(key, meta)
    return meta
