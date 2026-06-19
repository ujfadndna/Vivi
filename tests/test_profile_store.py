from __future__ import annotations

import json

import cv2
import numpy as np

from app import profile_store
from app.agent.agent_config import agent_settings
from app.config import settings


def test_profile_store_creates_default_and_encrypts_api_key(tmp_path, monkeypatch):
    avatar = tmp_path / "default.png"
    speaker = tmp_path / "speaker.wav"
    cv2.imwrite(str(avatar), np.full((8, 8, 3), 90, dtype=np.uint8))
    speaker.write_bytes(b"not-a-real-wav")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "default_avatar_image", avatar)
    monkeypatch.setattr(settings, "default_speaker_wav", speaker)
    monkeypatch.setattr(settings, "tts_backend", "indextts_http")
    monkeypatch.setattr(settings, "indextts_api_url", "http://127.0.0.1:8200")
    monkeypatch.setattr(agent_settings, "agent_llm_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(agent_settings, "agent_llm_model", "test-model")
    monkeypatch.setattr(agent_settings, "agent_llm_api_key", "sk-secret")

    profile_store.ensure_profile_store()
    profile = profile_store.get_profile()

    assert profile["id"] == "default"
    assert profile["deployment_mode"] == "mock"
    assert profile["voice"]["tts_api_url"] == "http://127.0.0.1:8200"
    assert profile["llm"]["api_key_set"] is True
    assert profile["llm"]["api_key_encrypted"] != "sk-secret"
    assert profile_store.decrypt_api_key(profile["llm"]["api_key_encrypted"]) == "sk-secret"
    profile_text = (tmp_path / "workspace" / "profiles" / "default" / "profile.json").read_text(
        encoding="utf-8"
    )
    assert "sk-secret" not in profile_text
    assert (tmp_path / "workspace" / "profiles" / "default" / "avatar.png").is_file()
    assert (tmp_path / "workspace" / "profiles" / "default" / "speaker.wav").is_file()


def test_profile_resolvers_prefer_profile_then_settings(tmp_path, monkeypatch):
    profile_avatar = tmp_path / "workspace" / "profiles" / "default" / "avatar.png"
    profile_speaker = tmp_path / "workspace" / "profiles" / "default" / "speaker.wav"
    fallback_avatar = tmp_path / "fallback.png"
    fallback_speaker = tmp_path / "fallback.wav"
    profile_avatar.parent.mkdir(parents=True)
    profile_avatar.write_bytes(b"avatar")
    profile_speaker.write_bytes(b"speaker")
    fallback_avatar.write_bytes(b"fallback-avatar")
    fallback_speaker.write_bytes(b"fallback-speaker")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "default_avatar_image", fallback_avatar)
    monkeypatch.setattr(settings, "default_speaker_wav", fallback_speaker)
    monkeypatch.setattr(settings, "indextts_api_url", "http://fallback")

    profile = {
        "id": "default",
        "name": "默认数字人",
        "active": True,
        "deployment_mode": "remote",
        "avatar": {"image_path": str(profile_avatar), "render_backend": "flashhead"},
        "voice": {
            "speaker_wav_path": str(profile_speaker),
            "tts_backend": "indextts_http",
            "tts_api_url": "http://profile",
        },
        "llm": {"api_key_encrypted": None},
    }
    (tmp_path / "workspace" / "profiles" / "profiles.json").write_text(
        json.dumps({"version": 1, "active_profile_id": "default", "profiles": ["default"]}),
        encoding="utf-8",
    )
    (tmp_path / "workspace" / "profiles" / "default" / "profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert profile_store.resolve_avatar_image() == profile_avatar.resolve()
    assert profile_store.resolve_speaker_wav() == profile_speaker.resolve()
    assert profile_store.resolve_tts_api_url() == "http://profile"
    assert profile_store.resolve_deployment_mode() == "remote"
    assert profile_store.resolve_render_api_url() == ""

    profile_avatar.unlink()
    profile_speaker.unlink()
    profile["voice"]["tts_api_url"] = ""
    (tmp_path / "workspace" / "profiles" / "default" / "profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert profile_store.resolve_avatar_image() == fallback_avatar.resolve()
    assert profile_store.resolve_speaker_wav() == fallback_speaker.resolve()
    assert profile_store.resolve_tts_api_url() == "http://fallback"


def test_profile_resolvers_return_render_url_and_normalize_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path / "workspace")
    monkeypatch.setattr(settings, "deployment_mode", "local")
    profile = {
        "id": "default",
        "name": "默认数字人",
        "active": True,
        "deployment_mode": "remote",
        "avatar": {"render_api_url": "https://render.example.com/"},
        "voice": {},
        "llm": {},
    }
    (tmp_path / "workspace" / "profiles" / "profiles.json").parent.mkdir(parents=True)
    (tmp_path / "workspace" / "profiles" / "profiles.json").write_text(
        json.dumps({"version": 1, "active_profile_id": "default", "profiles": ["default"]}),
        encoding="utf-8",
    )
    (tmp_path / "workspace" / "profiles" / "default").mkdir()
    (tmp_path / "workspace" / "profiles" / "default" / "profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert profile_store.resolve_deployment_mode() == "remote"
    assert profile_store.resolve_render_api_url() == "https://render.example.com"

    profile["deployment_mode"] = "bad"
    profile["avatar"]["render_api_url"] = ""
    (tmp_path / "workspace" / "profiles" / "default" / "profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert profile_store.resolve_deployment_mode() == "mock"
    assert profile_store.resolve_render_api_url() == ""

    profile.pop("deployment_mode")
    (tmp_path / "workspace" / "profiles" / "default" / "profile.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )

    assert profile_store.resolve_deployment_mode() == "local"
