from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from app import storage
from app.config import settings
from app.schemas import AudioWithTimestamps, PhonemeInterval, SynthesizeRequest
from app.services.base import register
from app.services.tts.base import SAMPLE_RATE, TTSBackend, _build_phoneme_intervals, _tokenize
from app.services.tts.cosyvoice import _dump_phonemes

_INSTALL_HINT = (
    "请先安装 faster-qwen3-tts：pip install faster-qwen3-tts，"
    "并将模型权重放到 settings.qwen3_tts_model_dir 路径。"
)
_LOGGER = logging.getLogger(__name__)

_MODEL: Any | None = None
_MODEL_KEY: str | None = None
_MODEL_LOCK: threading.Lock = threading.Lock()

_EMOTION_PROMPT = {
    "warm": "用温暖、轻柔、陪伴感强的语气",
    "calm": "用平静、放慢、让人安心的语气",
    "encouraging": "用温暖、轻快、鼓励的语气",
    "neutral": "用自然、平和的语气",
    "sad_soft": "用温柔、低沉、理解的语气",
}

_EMOTION_ALIASES = {
    "happy": "encouraging",
    "sad": "warm",
    "angry": "calm",
    "anxious": "calm",
}

_DEFAULT_SPEAKER = "aiden"
_KNOWN_SPEAKERS = {"aiden", "dylan", "eric", "ono_anna", "ryan"}
_MAX_SEQ_LEN = 2048
_CHUNK_SIZE = 12


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _load_model() -> Any:
    """懒加载并缓存 faster-qwen3-tts，避免非 qwen3 链路触发重依赖。"""
    global _MODEL, _MODEL_KEY

    model_dir = _resolve(settings.qwen3_tts_model_dir)
    model_key = str(model_dir)

    if _MODEL is not None and _MODEL_KEY == model_key:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is not None and _MODEL_KEY == model_key:
            return _MODEL

        if not model_dir.is_dir():
            raise RuntimeError(
                "Qwen3-TTS 模型目录不存在或不可访问。"
                f"当前 qwen3_tts_model_dir={model_key!r}。{_INSTALL_HINT}"
            )

        try:
            import torch
            from faster_qwen3_tts import FasterQwen3TTS
        except Exception as exc:
            raise RuntimeError(
                "Qwen3-TTS 依赖未安装或不可用：无法导入 faster_qwen3_tts.FasterQwen3TTS。"
                f"{_INSTALL_HINT}"
            ) from exc

        try:
            model = FasterQwen3TTS.from_pretrained(
                str(model_dir),
                device="cuda",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
                max_seq_len=_MAX_SEQ_LEN,
            )
        except Exception as exc:
            raise RuntimeError(
                "Qwen3-TTS 模型加载失败：请确认 faster-qwen3-tts、模型目录和 CUDA 环境。"
                f"model_dir={model_key!r}。{_INSTALL_HINT}"
            ) from exc

        _MODEL = model
        _MODEL_KEY = model_key
        return model


def _resolve_speaker(speaker_id: str | None) -> str:
    """将 speaker_id 解析为 Qwen3-TTS CustomVoice 内置 speaker 名称。

    speaker_id 可以是：
    - 内置 speaker 名称（如 "aiden"）→ 直接使用
    - 本地 wav 路径（沿用 IndexTTS 约定）→ 忽略路径，回退默认 speaker
    - None → 使用默认 speaker
    """
    if not speaker_id:
        return _DEFAULT_SPEAKER
    sid = speaker_id.strip()
    if sid in _KNOWN_SPEAKERS:
        return sid
    return _DEFAULT_SPEAKER


def _emotion_to_prompt(emotion: str | None) -> str:
    if not emotion:
        return _EMOTION_PROMPT["neutral"]
    normalized = emotion.strip().lower()
    normalized = _EMOTION_ALIASES.get(normalized, normalized)
    return _EMOTION_PROMPT.get(normalized, _EMOTION_PROMPT["neutral"])


def _language_name(language: str) -> str:
    normalized = language.strip().lower()
    if normalized.startswith("zh"):
        return "Chinese"
    if normalized.startswith("en"):
        return "English"
    if normalized.startswith("ja"):
        return "Japanese"
    if normalized.startswith("ko"):
        return "Korean"
    if normalized.startswith("de"):
        return "German"
    if normalized.startswith("fr"):
        return "French"
    if normalized.startswith("ru"):
        return "Russian"
    if normalized.startswith("pt"):
        return "Portuguese"
    if normalized.startswith("es"):
        return "Spanish"
    if normalized.startswith("it"):
        return "Italian"
    return "Auto"


def _resample_to_16k(waveform: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate == SAMPLE_RATE:
        return waveform.astype(np.float32, copy=False)
    if sample_rate <= 0:
        raise RuntimeError(f"Qwen3-TTS 返回了无效采样率：{sample_rate!r}")

    waveform = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if waveform.size == 0:
        return waveform

    new_size = max(1, int(round(waveform.size * SAMPLE_RATE / sample_rate)))
    old_x = np.linspace(0.0, 1.0, num=waveform.size, endpoint=False)
    new_x = np.linspace(0.0, 1.0, num=new_size, endpoint=False)
    return np.interp(new_x, old_x, waveform).astype(np.float32)


def _float_to_pcm16_bytes(waveform: np.ndarray) -> bytes:
    if waveform.size == 0:
        return b""
    clipped = np.clip(waveform, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    return pcm.tobytes()


@register("tts", "qwen3")
class Qwen3TTSBackend(TTSBackend):
    def run_streaming(self, req: SynthesizeRequest) -> Iterator[bytes]:
        if not req.text.strip():
            raise ValueError("Qwen3-TTS 合成失败：输入文本不能为空")

        model = _load_model()
        speaker = _resolve_speaker(req.speaker_id)
        instruct = _emotion_to_prompt(req.emotion)
        language = _language_name(req.language)

        try:
            gen = model.generate_custom_voice_streaming(
                text=req.text,
                speaker=speaker,
                language=language,
                instruct=instruct,
                chunk_size=_CHUNK_SIZE,
            )
        except Exception as exc:
            raise RuntimeError(f"Qwen3-TTS 流式合成启动失败：{exc}") from exc

        yielded = False
        try:
            for audio_chunk, sample_rate, _meta in gen:
                chunk_16k = _resample_to_16k(np.asarray(audio_chunk), int(sample_rate))
                chunk = _float_to_pcm16_bytes(chunk_16k)
                if chunk:
                    yielded = True
                    yield chunk
        except Exception as exc:
            raise RuntimeError(f"Qwen3-TTS 流式合成失败：{exc}") from exc

        if not yielded:
            raise RuntimeError("Qwen3-TTS 未返回有效音频 chunk")

    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        audio_id = storage.new_id("aud")
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"

        chunks = list(self.run_streaming(req))
        pcm = b"".join(chunks)
        if not pcm:
            raise RuntimeError("Qwen3-TTS 合成失败：流式输出为空")

        waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        try:
            sf.write(str(wav_path), waveform, SAMPLE_RATE, subtype="PCM_16")
        except Exception as exc:
            raise RuntimeError(f"Qwen3-TTS 输出 wav 写入失败：{wav_path}") from exc

        duration_sec = float(waveform.shape[0]) / float(SAMPLE_RATE)
        duration_frames = round(duration_sec * fps)

        tokens = _tokenize(req.text, req.language)
        phoneme_intervals: list[PhonemeInterval] = _build_phoneme_intervals(
            tokens,
            duration_frames,
        )
        try:
            _dump_phonemes(out_dir, phoneme_intervals)
        except Exception as exc:
            _LOGGER.warning("Qwen3-TTS phonemes.json 写入失败：%s", exc)

        return AudioWithTimestamps(
            audio_id=audio_id,
            audio_path=str(wav_path),
            duration_sec=duration_sec,
            duration_frames=duration_frames,
            sample_rate=SAMPLE_RATE,
            phoneme_intervals=phoneme_intervals,
        )
