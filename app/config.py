"""全局配置。后端可逐模块切换 mock / local / cloud。"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 工作区
    workspace_dir: Path = Path("./workspace")
    default_fps: int = 25
    api_port: int = 8100
    web_origin: str = "http://localhost:5173"
    deployment_mode: str = "mock"
    # Agent 层调用时使用的默认数字人视频素材路径
    default_avatar_video: Path = Path("./workspace/avatar/default.mp4")
    # 浏览器 /chat 待机循环视频；不存在时回退到 DEFAULT_AVATAR_IMAGE
    default_idle_video: Path = Path("./workspace/avatar/idle.mp4")
    # Agent 层调用时使用的默认参考音色（IndexTTS2 音色克隆所需）；分句流水线不传 speaker_id 时兜底
    default_speaker_wav: Path = Path("./reference_voice.wav")

    # 各模块后端选择
    ingest_backend: str = "mock"
    tts_backend: str = "mock"
    musetalk_backend: str = "mock"
    segment_backend: str = "mock"
    background_backend: str = "mock"
    composite_backend: str = "local"
    skip_rvm: bool = True

    # MuseTalk 真实后端（可选）
    musetalk_repo: Path = Path("./third_party/MuseTalk")
    musetalk_models_dir: Path = Path("./models")
    musetalk_realtime_blend: bool = True
    musetalk_stream_frames: bool = True
    musetalk_persistent_worker: bool = Field(
        True, env="MUSETALK_PERSISTENT_WORKER"
    )  # True=常驻Worker（~14GB VRAM），False=子进程（无帧流）

    # FlashHead 真实后端
    flashhead_repo: Path = Path("./third_party/SoulX-FlashHead")
    flashhead_ckpt_dir: Path = Path("./models/SoulX-FlashHead-1_3B")
    flashhead_wav2vec_dir: Path = Path("./models/wav2vec2-base-960h")
    flashhead_model_type: str = "lite"
    flashhead_stream_frames: bool = True
    # 头像单张照片（FlashHead 输入）
    default_avatar_image: Path = Path("./workspace/avatar/default.png")

    # RVM 真实分割后端（可选）
    rvm_variant: str = "mobilenetv3"
    rvm_checkpoint: Path = Path("./models/rvm/rvm_mobilenetv3.pth")

    # IndexTTS2 真实 TTS 后端（可选）
    indextts_repo: Path = Path("./third_party/IndexTTS")
    indextts_checkpoints: Path = Path("./models/IndexTTS-2")
    indextts_use_fp16: bool = True
    indextts_use_deepspeed: bool = False
    indextts_api_url: str = ""  # HTTP endpoint for IndexTTS2 service

    # Qwen3-TTS 真实 TTS 后端（可选）
    qwen3_tts_model_dir: Path = Path("/data/Her/models/Qwen3-TTS-1.7B")

    # Celery / Redis
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_always_eager: bool = True


settings = Settings()
