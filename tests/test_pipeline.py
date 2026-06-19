"""端到端冒烟测试：合成一段视频 → 跑完整链路 → 校验产物。

依赖 opencv / imageio-ffmpeg（见 requirements.txt）。Celery 默认 eager 同步执行。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.schemas import GenerateRequest
from app.storage import new_id
from app.tasks.pipeline import run_generation


@pytest.fixture()
def fake_video(tmp_path: Path) -> str:
    """生成一段 1 秒、320x240、25fps 的占位视频。"""
    path = tmp_path / "input.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    w, h, fps, n = 320, 240, 25, 25
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    assert writer.isOpened(), "无法创建测试视频（缺 opencv 编码器？）"
    for i in range(n):
        frame = np.full((h, w, 3), 60, dtype=np.uint8)
        # 画一个移动的方块代替人物，确保逐帧有差异
        x = 40 + i * 4
        cv2.rectangle(frame, (x, 80), (x + 80, 200), (200, 180, 160), -1)
        writer.write(frame)
    writer.release()
    return str(path)


def test_end_to_end(fake_video: str, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ingest_backend", "mock")
    monkeypatch.setattr(settings, "tts_backend", "mock")
    monkeypatch.setattr(settings, "musetalk_backend", "mock")
    monkeypatch.setattr(settings, "segment_backend", "mock")
    monkeypatch.setattr(settings, "background_backend", "mock")
    monkeypatch.setattr(settings, "composite_backend", "local")
    task_id = new_id("test")
    req = GenerateRequest(text="你好，我是数字人", language="zh")
    out = run_generation(task_id, fake_video, req)

    out_path = Path(out)
    assert out_path.exists(), "未生成输出视频"
    assert out_path.stat().st_size > 0, "输出视频为空"


def test_health():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert "warmup" in payload
    assert "tts" in payload["warmup"]
    assert "flashhead" in payload["warmup"]
    assert "inference_warmup" in payload["warmup"]["flashhead"]
    inference = payload["warmup"]["flashhead"]["inference_warmup"]
    assert {"status", "elapsed_sec", "error"} <= set(inference)


def test_cors_allows_vite_dev_origin():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
