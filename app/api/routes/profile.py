"""Profile configuration API for runtime assets and model endpoints."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.agent_config import agent_settings
from app.config import settings
from app import profile_store
from app.warmup import WARMUP_STATUS, start_flashhead_warmup_for_avatar

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac"}


class LlmConfigRequest(BaseModel):
    profile_id: str | None = None
    base_url: str = ""
    model: str = ""
    api_key: str | None = None


class BackendConfigRequest(BaseModel):
    profile_id: str | None = None
    deployment_mode: str = Field(pattern="^(mock|remote|local)$")
    tts_backend: str = Field(min_length=1)
    tts_api_url: str | None = None
    render_backend: str = Field(min_length=1)
    render_api_url: str | None = None


@router.get("")
async def get_active_profile():
    profile = profile_store.get_profile()
    payload = profile_store.sanitize_profile(profile)
    payload["warmup"] = WARMUP_STATUS
    return payload


@router.post("/avatar", status_code=202)
async def upload_avatar(
    file: UploadFile = File(...),
    profile_id: str | None = Form(None),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=422, detail="avatar must be png, jpg, jpeg, or webp")

    profile_store.ensure_profile_store()
    asset_dir = profile_store.profile_asset_dir(profile_id)
    tmp_path = asset_dir / f"avatar_upload{ext}"
    avatar_path = asset_dir / "avatar.png"
    with tmp_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    try:
        import cv2

        image = cv2.imread(str(tmp_path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("image cannot be decoded")
        if not cv2.imwrite(str(avatar_path), image):
            raise ValueError("image cannot be written")
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="avatar image cannot be decoded") from exc
    finally:
        if tmp_path != avatar_path:
            tmp_path.unlink(missing_ok=True)

    profile = profile_store.set_avatar_path(avatar_path, profile_id)
    if _should_warmup_local_flashhead(profile):
        start_flashhead_warmup_for_avatar(str(avatar_path.resolve()))
    return {
        "status": "accepted",
        "profile_id": profile["id"],
        "avatar_url": "/api/v1/profile/avatar",
        "warmup": WARMUP_STATUS,
    }


@router.get("/avatar")
async def get_avatar():
    avatar_path = profile_store.resolve_avatar_image()
    if avatar_path.is_file():
        return FileResponse(avatar_path)
    raise HTTPException(status_code=404, detail=f"avatar image not found: {avatar_path}")


@router.post("/voice")
async def upload_voice(
    file: UploadFile = File(...),
    profile_id: str | None = Form(None),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _AUDIO_EXTENSIONS:
        raise HTTPException(status_code=422, detail="voice must be wav, mp3, m4a, or flac")

    profile_store.ensure_profile_store()
    asset_dir = profile_store.profile_asset_dir(profile_id)
    speaker_path = asset_dir / "speaker.wav"
    tmp_path = asset_dir / f"speaker_upload{ext}"
    with tmp_path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)

    try:
        if ext == ".wav":
            shutil.copyfile(tmp_path, speaker_path)
        else:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(tmp_path),
                    "-ac",
                    "1",
                    "-ar",
                    "22050",
                    str(speaker_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise ValueError(result.stderr[-500:] if result.stderr else "ffmpeg failed")

        info = sf.info(str(speaker_path))
        duration_sec = float(info.frames) / float(info.samplerate)
        if duration_sec <= 0 or int(info.samplerate) <= 0:
            raise ValueError("invalid audio metadata")
    except Exception as exc:
        speaker_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="voice audio cannot be decoded") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    profile = profile_store.set_speaker_path(speaker_path, profile_id)
    return {
        "status": "ok",
        "profile_id": profile["id"],
        "voice_set": True,
        "duration_sec": round(duration_sec, 3),
        "sample_rate": int(info.samplerate),
    }


def _should_warmup_local_flashhead(profile: dict) -> bool:
    """Only local real FlashHead needs avatar warmup after upload.

    Remote mode uses the configured render endpoint, and mock/Docker mode does
    not ship FlashHead dependencies. Starting the local worker there creates a
    false failure even though the upload and preview are valid.
    """
    deployment_mode = (profile.get("deployment_mode") or "").strip().lower()
    return deployment_mode == "local" and settings.musetalk_backend == "local"


@router.post("/llm")
async def update_llm_config(request: LlmConfigRequest):
    api_key = (request.api_key or "").strip() or None
    base_url = (
        request.base_url.strip().rstrip("/")
        or agent_settings.agent_llm_base_url
        or "https://api.deepseek.com/v1"
    )
    model = request.model.strip() or agent_settings.agent_llm_model or "deepseek-chat"
    profile = profile_store.set_llm_config(
        profile_id=request.profile_id,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    llm = profile_store.sanitize_profile(profile)["llm"]
    return {
        "status": "ok",
        "profile_id": profile["id"],
        **llm,
    }


@router.post("/backends")
async def update_backend_config(request: BackendConfigRequest):
    profile = profile_store.set_backend_config(
        profile_id=request.profile_id,
        deployment_mode=request.deployment_mode,
        tts_backend=request.tts_backend.strip(),
        tts_api_url=(request.tts_api_url or "").strip() or None,
        render_backend=request.render_backend.strip(),
        render_api_url=(request.render_api_url or "").strip() or None,
    )
    payload = profile_store.sanitize_profile(profile)
    return {
        "status": "ok",
        "profile_id": profile["id"],
        "deployment_mode": payload["deployment_mode"],
        "voice": payload["voice"],
        "avatar": payload["avatar"],
    }
