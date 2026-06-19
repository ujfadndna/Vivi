from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.main import app, lifespan
from app.warmup import WARMUP_STATUS


@pytest.fixture(autouse=True)
def restore_warmup_status():
    import copy

    original = copy.deepcopy(WARMUP_STATUS)
    yield
    WARMUP_STATUS.clear()
    WARMUP_STATUS.update(original)


@pytest.mark.asyncio
async def test_startup_runs_flashhead_inference_warmup_to_ok(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"image")
    calls: list[str] = []

    class FakeWorkerManager:
        def start(self) -> None:
            calls.append("start")

        async def warmup_background(self, image_path: str):
            calls.append(f"image:{Path(image_path).name}")
            return {"status": "ok"}

        async def warmup_inference_background(
            self,
            image_path: str,
            duration_sec: float = 2.0,
            fps: float = 25.0,
        ):
            calls.append(f"inference:{Path(image_path).name}:{duration_sec}:{fps}")
            return {"status": "ok", "num_frames": 12, "elapsed_sec": 0.75}

        def stop(self) -> None:
            calls.append("stop")

    monkeypatch.setattr(settings, "default_avatar_image", avatar)
    monkeypatch.setattr(settings, "musetalk_backend", "local")
    monkeypatch.setattr(settings, "musetalk_persistent_worker", True)
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(settings, "default_fps", 25)
    monkeypatch.setattr("app.main.worker_manager", FakeWorkerManager(), raising=False)

    import app.services.flashhead.persistent as persistent

    monkeypatch.setattr(persistent, "worker_manager", FakeWorkerManager())

    async with lifespan(app):
        for _ in range(20):
            if WARMUP_STATUS["flashhead"]["inference_warmup"]["status"] == "ok":
                break
            import asyncio

            await asyncio.sleep(0.01)

        assert WARMUP_STATUS["tts"]["status"] == "ok"
        assert WARMUP_STATUS["flashhead"]["worker_ready"] is True
        assert WARMUP_STATUS["flashhead"]["status"] == "ok"
        assert WARMUP_STATUS["flashhead"]["inference_warmup"] == {
            "status": "ok",
            "elapsed_sec": 2.25,
            "error": None,
        }
        assert calls == [
            "start",
            "image:avatar.png",
            "inference:avatar.png:2.0:25.0",
            "inference:avatar.png:3.2:25.0",
            "inference:avatar.png:5.0:25.0",
        ]


@pytest.mark.asyncio
async def test_startup_marks_flashhead_inference_warmup_failed(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"image")

    class FakeWorkerManager:
        def start(self) -> None:
            pass

        async def warmup_background(self, image_path: str):
            return {"status": "ok"}

        async def warmup_inference_background(
            self,
            image_path: str,
            duration_sec: float = 2.0,
            fps: float = 25.0,
        ):
            raise RuntimeError("compile failed")

        def stop(self) -> None:
            pass

    import app.services.flashhead.persistent as persistent

    monkeypatch.setattr(settings, "default_avatar_image", avatar)
    monkeypatch.setattr(settings, "musetalk_backend", "local")
    monkeypatch.setattr(settings, "musetalk_persistent_worker", True)
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(persistent, "worker_manager", FakeWorkerManager())

    async with lifespan(app):
        for _ in range(20):
            if WARMUP_STATUS["flashhead"]["inference_warmup"]["status"] == "failed":
                break
            import asyncio

            await asyncio.sleep(0.01)

        inference = WARMUP_STATUS["flashhead"]["inference_warmup"]
        assert inference["status"] == "failed"
        assert inference["error"] == "compile failed"
