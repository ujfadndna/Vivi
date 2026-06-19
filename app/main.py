"""FastAPI 入口。挂载编排端点、各模块端点，并静态托管输出视频。"""
from __future__ import annotations

import asyncio
import os as _os
import signal as _signal

# IndexTTS2 依赖的 HuggingFace/protobuf 在无网络环境下需要这些环境变量
_os.environ.setdefault("HF_HUB_OFFLINE", "1")
_os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
_os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import profile_store
from app.api.routes import chat_page, generate, modules, profile, stream
from app.api.routes.agent import router as agent_router
from app.api.routes.ws_audio import router as ws_audio_router
from app.api.routes.ws_sensor import router as ws_sensor_router
from app.storage import output_dir
from app.warmup import WARMUP_STATUS as _warmup_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    from app.agent.agent_config import agent_settings
    from app.agent import db as agent_db
    from app.agent import memory as agent_mem
    from app.config import settings
    from app import profile_store

    logger = logging.getLogger(__name__)
    worker_manager = None
    profile_store.ensure_profile_store()
    avatar_image = profile_store.resolve_avatar_image()
    _warmup_status["tts"].update(
        {"status": "not_started", "backend": settings.tts_backend, "error": None}
    )
    _warmup_status["flashhead"].update(
        {
            "status": "not_started",
            "worker_ready": False,
            "avatar_image_path": str(avatar_image),
            "error": None,
            "inference_warmup": {
                "status": "not_started",
                "elapsed_sec": 0.0,
                "error": None,
            },
        }
    )
    logger.info("FlashHead avatar image path: %s", avatar_image)

    try:
        from app.agent.tools import init_tools_db

        agent_db.init_db(agent_settings.agent_db_dir / "agent.sqlite")
        init_tools_db(agent_settings.agent_db_dir / "todos.sqlite")
        agent_mem.init_memory(agent_settings.agent_db_dir / "chroma")
    except ModuleNotFoundError:
        # Agent dependencies are optional for render-only and static UI usage.
        pass
    if settings.musetalk_backend != "local":
        _warmup_status["flashhead"].update(
            {
                "status": "ok",
                "worker_ready": True,
                "avatar_image_path": str(avatar_image),
                "error": None,
                "inference_warmup": {
                    "status": "ok",
                    "elapsed_sec": 0.0,
                    "error": None,
                },
            }
        )
    elif settings.musetalk_persistent_worker:
        from app.services.flashhead.persistent import worker_manager as flashhead_worker_manager
        from app.warmup import run_flashhead_warmup

        worker_manager = flashhead_worker_manager
        logger.info("FlashHead worker ready, warmup avatar=%s", avatar_image)
        if avatar_image.exists():
            async def _warmup() -> None:
                await run_flashhead_warmup(str(avatar_image))
                logger.info("FlashHead warmup finished avatar=%s", avatar_image)

            asyncio.create_task(_warmup())
        else:
            _warmup_status["flashhead"]["status"] = "failed"
            _warmup_status["flashhead"]["error"] = f"avatar image not found: {avatar_image}"
            _warmup_status["flashhead"]["inference_warmup"].update(
                {
                    "status": "failed",
                    "elapsed_sec": 0.0,
                    "error": f"avatar image not found: {avatar_image}",
                }
            )
            logger.warning("FlashHead warmup skipped; avatar image not found: %s", avatar_image)
    async def _warmup_tts() -> None:
        if settings.tts_backend == "qwen3":
            return
        if settings.tts_backend not in {"indextts", "indextts_http"}:
            _warmup_status["tts"]["status"] = "ok"
            return
        _warmup_status["tts"]["status"] = "started"
        logger.info("TTS warmup started backend=%s", settings.tts_backend)
        try:
            if settings.tts_backend == "indextts":
                from app.services.tts import indextts

                await asyncio.to_thread(indextts._load_model)
            _warmup_status["tts"]["status"] = "ok"
            logger.info("TTS warmup ok backend=%s", settings.tts_backend)
        except Exception as _e:  # noqa: BLE001 - startup warmup is best-effort.
            _warmup_status["tts"]["status"] = "failed"
            _warmup_status["tts"]["error"] = str(_e)
            logger.warning("TTS warmup failed backend=%s error=%s", settings.tts_backend, _e)

    asyncio.create_task(_warmup_tts())

    async def _warmup_faster_qwen3() -> None:
        if settings.tts_backend != "qwen3":
            return
        try:
            from app.services.tts.qwen3 import _load_model
            _warmup_status["tts"]["status"] = "started"
            logger.info("TTS warmup started backend=qwen3")
            await asyncio.to_thread(_load_model)
            _warmup_status["tts"]["status"] = "ok"
            logger.info("TTS warmup ok backend=qwen3")
        except Exception as _e:  # noqa: BLE001
            _warmup_status["tts"]["status"] = "failed"
            _warmup_status["tts"]["error"] = str(_e)
            logger.warning("TTS warmup failed backend=qwen3 error=%s", _e)

    asyncio.create_task(_warmup_faster_qwen3())
    # 写 PID 文件，供重启脚本精准杀进程用
    _pid_file = _pathlib.Path("/data/Her/server.pid")
    try:
        _pid_file.write_text(str(_os.getpid()))
    except Exception:
        pass
    try:
        yield
    finally:
        if worker_manager is not None:
            worker_manager.stop()
        try:
            _pid_file.unlink(missing_ok=True)
        except Exception:
            pass


app = FastAPI(title="可控 2D 数字人系统", version="0.1.0", lifespan=lifespan)

_cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
try:
    from app.config import settings as _settings

    if _settings.web_origin:
        _cors_origins.append(_settings.web_origin.rstrip("/"))
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(set(_cors_origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router)
app.include_router(modules.router)
app.include_router(profile.router)
app.include_router(chat_page.router)
app.include_router(agent_router)
app.include_router(stream.router)
app.include_router(ws_audio_router)
app.include_router(ws_sensor_router)

# 输出视频下载：GET /outputs/{task_id}.mp4
app.mount("/outputs", StaticFiles(directory=str(output_dir())), name="outputs")

# Demo UI：GET /static/demo.html
import pathlib as _pathlib
_static_dir = _pathlib.Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/health")
async def health():
    import os, pathlib
    base = pathlib.Path(__file__).parent
    def _mtime(rel):
        try:
            return round(os.path.getmtime(base / rel), 2)
        except OSError:
            return None
    return {
        "status": "ok",
        "code_mtime": _mtime("main.py"),
        "tts_mtime": _mtime("services/tts/indextts.py"),
        "warmup": _warmup_status,
        "profile": profile_store.active_profile_summary(),
    }
