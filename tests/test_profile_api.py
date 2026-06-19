from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _write_png(path: Path) -> None:
    cv2.imwrite(str(path), np.full((24, 18, 3), 120, dtype=np.uint8))


def _write_wav(path: Path) -> None:
    samples = np.zeros(2205, dtype=np.float32)
    sf.write(str(path), samples, 22050)


def test_profile_api_returns_sanitized_active_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    avatar = tmp_path / "avatar.png"
    _write_png(avatar)
    monkeypatch.setattr(settings, "default_avatar_image", avatar)

    client = TestClient(app)
    response = client.get("/api/v1/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_id"] == "default"
    assert payload["avatar"]["avatar_url"] == "/api/v1/profile/avatar"
    assert "api_key_encrypted" not in payload["llm"]
    assert "warmup" in payload


def test_profile_avatar_upload_saves_image_and_triggers_warmup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "deployment_mode", "local")
    monkeypatch.setattr(settings, "musetalk_backend", "local")
    upload = tmp_path / "upload.jpg"
    _write_png(upload)
    warmup_calls: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.profile.start_flashhead_warmup_for_avatar",
        lambda image_path: warmup_calls.append(image_path),
    )

    client = TestClient(app)
    with upload.open("rb") as handle:
        response = client.post(
            "/api/v1/profile/avatar",
            files={"file": ("avatar.jpg", handle, "image/jpeg")},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    saved = tmp_path / "workspace" / "profiles" / "default" / "avatar.png"
    assert saved.is_file()
    assert cv2.imread(str(saved)) is not None
    assert warmup_calls == [str(saved.resolve())]
    image_response = client.get("/api/v1/profile/avatar")
    assert image_response.status_code == 200


def test_profile_avatar_upload_remote_mode_does_not_trigger_local_warmup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "deployment_mode", "remote")
    monkeypatch.setattr(settings, "musetalk_backend", "mock")
    upload = tmp_path / "upload.jpg"
    _write_png(upload)
    warmup_calls: list[str] = []
    monkeypatch.setattr(
        "app.api.routes.profile.start_flashhead_warmup_for_avatar",
        lambda image_path: warmup_calls.append(image_path),
    )

    client = TestClient(app)
    client.post(
        "/api/v1/profile/backends",
        json={
            "deployment_mode": "remote",
            "tts_backend": "indextts_http",
            "tts_api_url": "http://tts.example.com",
            "render_backend": "flashhead",
            "render_api_url": "http://render.example.com",
        },
    )

    with upload.open("rb") as handle:
        response = client.post(
            "/api/v1/profile/avatar",
            files={"file": ("avatar.jpg", handle, "image/jpeg")},
        )

    assert response.status_code == 202
    saved = tmp_path / "workspace" / "profiles" / "default" / "avatar.png"
    assert saved.is_file()
    assert warmup_calls == []


def test_profile_avatar_upload_rejects_bad_image(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-image")

    client = TestClient(app)
    with bad.open("rb") as handle:
        response = client.post(
            "/api/v1/profile/avatar",
            files={"file": ("bad.png", handle, "image/png")},
        )

    assert response.status_code == 422


def test_profile_voice_upload_saves_wav_and_returns_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    wav = tmp_path / "voice.wav"
    _write_wav(wav)

    client = TestClient(app)
    with wav.open("rb") as handle:
        response = client.post(
            "/api/v1/profile/voice",
            files={"file": ("voice.wav", handle, "audio/wav")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["voice_set"] is True
    assert payload["sample_rate"] == 22050
    assert payload["duration_sec"] == 0.1
    saved = tmp_path / "workspace" / "profiles" / "default" / "speaker.wav"
    assert saved.is_file()


def test_profile_voice_upload_rejects_bad_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not-audio")

    client = TestClient(app)
    with bad.open("rb") as handle:
        response = client.post(
            "/api/v1/profile/voice",
            files={"file": ("bad.wav", handle, "audio/wav")},
        )

    assert response.status_code == 422


def test_profile_llm_encrypts_key_and_allows_key_preserve(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    client = TestClient(app)

    response = client.post(
        "/api/v1/profile/llm",
        json={
            "base_url": "https://api.example.com/v1",
            "model": "demo-model",
            "api_key": "sk-demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key_set"] is True
    assert "sk-demo" not in response.text
    profile_path = tmp_path / "workspace" / "profiles" / "default" / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    encrypted = profile["llm"]["api_key_encrypted"]
    assert encrypted and encrypted != "sk-demo"

    response = client.post(
        "/api/v1/profile/llm",
        json={"base_url": "https://api2.example.com/v1", "model": "demo-2", "api_key": ""},
    )
    assert response.status_code == 200
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["llm"]["api_key_encrypted"] == encrypted
    assert profile["llm"]["model"] == "demo-2"


def test_profile_llm_allows_empty_fields_for_mock_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    client = TestClient(app)

    response = client.post(
        "/api/v1/profile/llm",
        json={"base_url": "", "model": "", "api_key": ""},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"]
    assert payload["model"]
    assert payload["api_key_set"] is False


def test_profile_backends_updates_endpoint_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    client = TestClient(app)

    response = client.post(
        "/api/v1/profile/backends",
        json={
            "deployment_mode": "mock",
            "tts_backend": "indextts_http",
            "tts_api_url": "http://127.0.0.1:8200",
            "render_backend": "flashhead",
            "render_api_url": "https://render.example.com",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deployment_mode"] == "mock"
    assert payload["voice"]["tts_api_url"] == "http://127.0.0.1:8200"
    assert payload["avatar"]["render_backend"] == "flashhead"
    assert payload["avatar"]["render_api_url"] == "https://render.example.com"
