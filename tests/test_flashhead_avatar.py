from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.schemas import VideoMetadata
from app.services.flashhead.real import _resolve_avatar_image


def test_resolve_avatar_image_requires_configured_default_image(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    missing_avatar = tmp_path / "avatar" / "default.png"
    monkeypatch.setattr(settings, "default_avatar_image", missing_avatar)

    video = VideoMetadata(
        video_id="vid",
        fps=25,
        num_frames=1,
        duration_sec=0.04,
        resolution=(96, 64),
        face_bbox=(0, 0, 96, 64),
        frames_dir=str(frames_dir),
    )

    with pytest.raises(FileNotFoundError, match="DEFAULT_AVATAR_IMAGE"):
        _resolve_avatar_image(video)


def test_resolve_avatar_image_prefers_image_driven_frame(tmp_path, monkeypatch):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    uploaded_frame = frames_dir / "00000000.png"
    uploaded_frame.write_bytes(b"uploaded")
    default_avatar = tmp_path / "avatar" / "default.png"
    default_avatar.parent.mkdir()
    default_avatar.write_bytes(b"default")
    monkeypatch.setattr(settings, "default_avatar_image", default_avatar)

    video = VideoMetadata(
        video_id="default_avatar_image",
        fps=25,
        num_frames=1,
        duration_sec=0.04,
        resolution=(96, 64),
        face_bbox=(0, 0, 96, 64),
        frames_dir=str(frames_dir),
    )

    assert _resolve_avatar_image(video) == uploaded_frame.resolve()


def test_resolve_avatar_image_uses_configured_default_image(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"not a real image")
    monkeypatch.setattr(settings, "default_avatar_image", avatar)

    video = VideoMetadata(
        video_id="vid",
        fps=25,
        num_frames=1,
        duration_sec=0.04,
        resolution=(96, 64),
        face_bbox=(0, 0, 96, 64),
        frames_dir=str(tmp_path / "missing_frames"),
    )

    assert _resolve_avatar_image(video) == avatar.resolve()
