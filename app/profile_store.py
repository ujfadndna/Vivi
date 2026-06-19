"""Runtime profile storage for user-configurable model endpoints and assets."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.agent.agent_config import agent_settings
from app.config import settings

PROFILE_STORE_VERSION = 1
DEFAULT_PROFILE_ID = "default"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profiles_root() -> Path:
    return settings.workspace_dir / "profiles"


def _profile_dir(profile_id: str) -> Path:
    return _profiles_root() / profile_id


def _profile_json(profile_id: str) -> Path:
    return _profile_dir(profile_id) / "profile.json"


def _manifest_path() -> Path:
    return _profiles_root() / "profiles.json"


def _secret_path() -> Path:
    return _profiles_root() / "app_secret.key"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _fernet() -> Fernet:
    _profiles_root().mkdir(parents=True, exist_ok=True)
    path = _secret_path()
    if path.is_file():
        key = path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        path.write_bytes(key)
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(api_key_encrypted: str | None) -> str | None:
    if not api_key_encrypted:
        return None
    try:
        return _fernet().decrypt(api_key_encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def _copy_initial_asset(src: Path, dst: Path) -> str | None:
    src = src.expanduser()
    if not src.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copyfile(src, dst)
    return str(dst)


def _initial_profile() -> dict[str, Any]:
    profile_id = DEFAULT_PROFILE_ID
    now = _utc_now()
    pdir = _profile_dir(profile_id)

    avatar_path = _copy_initial_asset(
        Path(settings.default_avatar_image),
        pdir / "avatar.png",
    )
    speaker_path = _copy_initial_asset(
        Path(settings.default_speaker_wav),
        pdir / "speaker.wav",
    )
    api_key = agent_settings.agent_llm_api_key or ""
    api_key_encrypted = encrypt_api_key(api_key) if api_key else None

    return {
        "id": profile_id,
        "name": "默认数字人",
        "active": True,
        "deployment_mode": _normalize_deployment_mode(settings.deployment_mode),
        "avatar": {
            "image_path": avatar_path,
            "render_backend": "flashhead",
            "render_api_url": None,
        },
        "voice": {
            "speaker_wav_path": speaker_path,
            "tts_backend": settings.tts_backend,
            "tts_api_url": settings.indextts_api_url or None,
        },
        "llm": {
            "provider": "openai_compatible",
            "base_url": agent_settings.agent_llm_base_url or "https://api.deepseek.com/v1",
            "model": agent_settings.agent_llm_model,
            "api_key_encrypted": api_key_encrypted,
            "api_key_set": bool(api_key_encrypted),
        },
        "created_at": now,
        "updated_at": now,
    }


def ensure_profile_store() -> None:
    root = _profiles_root()
    root.mkdir(parents=True, exist_ok=True)
    _fernet()
    manifest = _read_json(_manifest_path())
    profile_ids = manifest.get("profiles") or []
    if profile_ids and manifest.get("active_profile_id"):
        return

    profile = _initial_profile()
    _write_json(_profile_json(profile["id"]), profile)
    _write_json(
        _manifest_path(),
        {
            "version": PROFILE_STORE_VERSION,
            "active_profile_id": profile["id"],
            "profiles": [profile["id"]],
        },
    )


def list_profile_ids() -> list[str]:
    ensure_profile_store()
    manifest = _read_json(_manifest_path())
    return [str(item) for item in manifest.get("profiles", [])]


def get_active_profile_id() -> str:
    ensure_profile_store()
    manifest = _read_json(_manifest_path())
    return str(manifest.get("active_profile_id") or DEFAULT_PROFILE_ID)


def get_profile(profile_id: str | None = None) -> dict[str, Any]:
    ensure_profile_store()
    pid = profile_id or get_active_profile_id()
    profile = _read_json(_profile_json(pid))
    if not profile:
        raise FileNotFoundError(f"profile not found: {pid}")
    return profile


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile = dict(profile)
    profile["updated_at"] = _utc_now()
    _write_json(_profile_json(str(profile["id"])), profile)
    return profile


def sanitize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    llm = dict(profile.get("llm") or {})
    llm.pop("api_key_encrypted", None)
    llm["api_key_set"] = bool(profile.get("llm", {}).get("api_key_encrypted"))
    avatar = dict(profile.get("avatar") or {})
    voice = dict(profile.get("voice") or {})
    return {
        "profile_id": profile.get("id"),
        "name": profile.get("name"),
        "deployment_mode": profile.get("deployment_mode"),
        "avatar": {
            "avatar_url": "/api/v1/profile/avatar",
            "render_backend": avatar.get("render_backend"),
            "render_api_url": avatar.get("render_api_url"),
        },
        "voice": {
            "voice_set": bool(voice.get("speaker_wav_path")),
            "tts_backend": voice.get("tts_backend"),
            "tts_api_url": voice.get("tts_api_url"),
        },
        "llm": llm,
    }


def resolve_avatar_image(profile_id: str | None = None) -> Path:
    try:
        profile = get_profile(profile_id)
    except FileNotFoundError:
        profile = {}
    candidate = (profile.get("avatar") or {}).get("image_path")
    if candidate and Path(candidate).expanduser().is_file():
        return Path(candidate).expanduser().resolve()
    return Path(settings.default_avatar_image).expanduser().resolve()


def resolve_speaker_wav(profile_id: str | None = None) -> Path | None:
    try:
        profile = get_profile(profile_id)
    except FileNotFoundError:
        profile = {}
    candidate = (profile.get("voice") or {}).get("speaker_wav_path")
    if candidate and Path(candidate).expanduser().is_file():
        return Path(candidate).expanduser().resolve()
    fallback = Path(settings.default_speaker_wav).expanduser()
    if fallback.is_file():
        return fallback.resolve()
    return None


def resolve_tts_api_url(profile_id: str | None = None) -> str:
    try:
        profile = get_profile(profile_id)
    except FileNotFoundError:
        profile = {}
    api_url = ((profile.get("voice") or {}).get("tts_api_url") or "").strip()
    return api_url or settings.indextts_api_url


def _normalize_deployment_mode(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"mock", "remote", "local"}:
        return normalized
    return "mock"


def resolve_deployment_mode(profile_id: str | None = None) -> str:
    try:
        profile = get_profile(profile_id)
    except FileNotFoundError:
        profile = {}
    raw_mode = profile.get("deployment_mode")
    if raw_mode is None or not str(raw_mode).strip():
        return _normalize_deployment_mode(settings.deployment_mode)
    return _normalize_deployment_mode(raw_mode)


def resolve_render_api_url(profile_id: str | None = None) -> str:
    try:
        profile = get_profile(profile_id)
    except FileNotFoundError:
        profile = {}
    api_url = ((profile.get("avatar") or {}).get("render_api_url") or "").strip()
    return api_url.rstrip("/")


def resolve_llm_config(profile_id: str | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id)
    llm = dict(profile.get("llm") or {})
    return {
        "provider": llm.get("provider") or "openai_compatible",
        "base_url": llm.get("base_url") or "https://api.deepseek.com/v1",
        "model": llm.get("model") or "deepseek-chat",
        "api_key": decrypt_api_key(llm.get("api_key_encrypted")),
        "api_key_set": bool(llm.get("api_key_encrypted")),
    }


def set_avatar_path(path: Path, profile_id: str | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id)
    avatar = dict(profile.get("avatar") or {})
    avatar["image_path"] = str(path)
    profile["avatar"] = avatar
    return save_profile(profile)


def set_speaker_path(path: Path, profile_id: str | None = None) -> dict[str, Any]:
    profile = get_profile(profile_id)
    voice = dict(profile.get("voice") or {})
    voice["speaker_wav_path"] = str(path)
    profile["voice"] = voice
    return save_profile(profile)


def set_llm_config(
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    profile = get_profile(profile_id)
    llm = dict(profile.get("llm") or {})
    llm["provider"] = "openai_compatible"
    llm["base_url"] = base_url
    llm["model"] = model
    if api_key:
        llm["api_key_encrypted"] = encrypt_api_key(api_key)
    llm["api_key_set"] = bool(llm.get("api_key_encrypted"))
    profile["llm"] = llm
    return save_profile(profile)


def set_backend_config(
    *,
    deployment_mode: str,
    tts_backend: str,
    tts_api_url: str | None,
    render_backend: str,
    render_api_url: str | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    profile = get_profile(profile_id)
    profile["deployment_mode"] = _normalize_deployment_mode(deployment_mode)
    voice = dict(profile.get("voice") or {})
    voice["tts_backend"] = tts_backend
    voice["tts_api_url"] = tts_api_url or None
    avatar = dict(profile.get("avatar") or {})
    avatar["render_backend"] = render_backend
    avatar["render_api_url"] = render_api_url or None
    profile["voice"] = voice
    profile["avatar"] = avatar
    return save_profile(profile)


def active_profile_summary() -> dict[str, Any]:
    profile = get_profile()
    avatar = dict(profile.get("avatar") or {})
    voice = dict(profile.get("voice") or {})
    llm = dict(profile.get("llm") or {})
    return {
        "id": profile.get("id"),
        "name": profile.get("name"),
        "avatar_set": bool(avatar.get("image_path")),
        "voice_set": bool(voice.get("speaker_wav_path")),
        "llm_configured": bool(llm.get("api_key_encrypted")),
        "deployment_mode": _normalize_deployment_mode(
            profile.get("deployment_mode") or settings.deployment_mode
        ),
        "render_api_url": avatar.get("render_api_url"),
    }


def profile_asset_dir(profile_id: str | None = None) -> Path:
    pid = profile_id or get_active_profile_id()
    path = _profile_dir(pid)
    path.mkdir(parents=True, exist_ok=True)
    return path
