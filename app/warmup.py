"""Shared startup warmup status for health checks and chat readiness gates."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings


WARMUP_STATUS: dict[str, Any] = {
    "tts": {"status": "not_started", "backend": None, "error": None},
    "flashhead": {
        "status": "not_started",
        "worker_ready": False,
        "avatar_image_path": None,
        "error": None,
        "inference_warmup": {
            "status": "not_started",
            "elapsed_sec": 0.0,
            "error": None,
        },
    },
}


def reset_flashhead_warmup(image_path: str) -> None:
    WARMUP_STATUS["flashhead"].update(
        {
            "status": "started",
            "worker_ready": True,
            "avatar_image_path": image_path,
            "error": None,
            "inference_warmup": {
                "status": "not_started",
                "elapsed_sec": 0.0,
                "error": None,
            },
        }
    )


async def run_flashhead_warmup(image_path: str) -> None:
    """Run avatar and inference warmup, updating shared status in-place."""
    from app.services.flashhead.persistent import worker_manager

    logger = logging.getLogger(__name__)
    reset_flashhead_warmup(image_path)
    try:
        worker_manager.start()
        WARMUP_STATUS["flashhead"]["worker_ready"] = True
    except Exception as exc:  # noqa: BLE001 - warmup status carries the failure.
        WARMUP_STATUS["flashhead"].update(
            {
                "status": "failed",
                "worker_ready": False,
                "error": str(exc),
            }
        )
        WARMUP_STATUS["flashhead"]["inference_warmup"].update(
            {"status": "failed", "elapsed_sec": 0.0, "error": str(exc)}
        )
        logger.warning("FlashHead worker start failed avatar=%s error=%s", image_path, exc)
        return
    try:
        await worker_manager.warmup_background(image_path)
        WARMUP_STATUS["flashhead"]["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - warmup status carries the failure.
        WARMUP_STATUS["flashhead"]["status"] = "failed"
        WARMUP_STATUS["flashhead"]["error"] = str(exc)
        WARMUP_STATUS["flashhead"]["inference_warmup"].update(
            {"status": "failed", "elapsed_sec": 0.0, "error": str(exc)}
        )
        logger.warning("FlashHead avatar warmup failed avatar=%s error=%s", image_path, exc)
        return

    inference = WARMUP_STATUS["flashhead"]["inference_warmup"]
    inference.update({"status": "started", "elapsed_sec": 0.0, "error": None})
    try:
        elapsed_sec = 0.0
        for duration_sec in (2.0, 3.2, 5.0):
            result = await worker_manager.warmup_inference_background(
                image_path,
                duration_sec=duration_sec,
                fps=float(settings.default_fps),
            )
            elapsed_sec += float(result.get("elapsed_sec") or 0.0)
        inference.update(
            {
                "status": "ok",
                "elapsed_sec": round(elapsed_sec, 3),
                "error": None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - warmup status carries the failure.
        inference.update(
            {
                "status": "failed",
                "elapsed_sec": 0.0,
                "error": str(exc),
            }
        )
        logger.warning("FlashHead inference warmup failed avatar=%s error=%s", image_path, exc)


def start_flashhead_warmup_for_avatar(image_path: str) -> None:
    """Schedule FlashHead warmup from an async route or lifespan task."""
    reset_flashhead_warmup(image_path)
    asyncio.create_task(run_flashhead_warmup(image_path))


def is_digital_human_ready() -> bool:
    if settings.musetalk_backend != "local":
        return WARMUP_STATUS.get("tts", {}).get("status") == "ok"

    flashhead = WARMUP_STATUS.get("flashhead") or {}
    inference = flashhead.get("inference_warmup") or {}
    tts = WARMUP_STATUS.get("tts") or {}
    return (
        tts.get("status") == "ok"
        and flashhead.get("worker_ready") is True
        and flashhead.get("status") == "ok"
        and inference.get("status") == "ok"
    )
