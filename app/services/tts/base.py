"""文本转语音（TTS）。Mock 实现：生成占位音频 + 伪音素时间戳。

对应 docs/digital-human-design.md「2. 文本与语音」。
真实实现可注册为 @register("tts", "local"/"indextts"/"qwen3"/"cloud")，按 settings.tts_backend 切换。
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

import numpy as np
import soundfile as sf

from app import storage
from app.config import settings
from app.schemas import AudioWithTimestamps, PhonemeInterval, SynthesizeRequest
from app.services.base import get_backend, register

SAMPLE_RATE = 16000

# 时长估算系数
_SEC_PER_CHAR = 0.18   # 中文：每字约 0.18s
_SEC_PER_WORD = 0.30   # 其它语言：每词约 0.30s
_MIN_DURATION = 0.5    # 最小时长兜底（秒）

# 占位音频参数（低幅正弦，避免纯静音）
_TONE_HZ = 220.0
_TONE_AMP = 0.02


class TTSBackend(ABC):
    @abstractmethod
    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        ...


def _is_chinese(language: str) -> bool:
    return language.lower().startswith("zh")


def _tokenize(text: str, language: str) -> list[str]:
    """把文本切成伪音素 token：中文按字符，其它语言按词。忽略空白。"""
    if _is_chinese(language):
        return [c for c in text if not c.isspace()]
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _estimate_duration(tokens: list[str], language: str, speed: float) -> float:
    """根据 token 数量估算时长，再按语速缩放，并做最小时长兜底。"""
    per = _SEC_PER_CHAR if _is_chinese(language) else _SEC_PER_WORD
    speed = speed if speed > 0 else 1.0
    duration = len(tokens) * per / speed
    return max(duration, _MIN_DURATION)


def _build_phoneme_intervals(
    tokens: list[str], duration_frames: int
) -> list[PhonemeInterval]:
    """在 [0, duration_frames] 上均匀分配 token，首尾相接覆盖整段。"""
    if not tokens or duration_frames <= 0:
        return []

    n = len(tokens)
    intervals: list[PhonemeInterval] = []
    for i, tok in enumerate(tokens):
        start = round(i * duration_frames / n)
        end = round((i + 1) * duration_frames / n)
        if end <= start:  # 保证至少 1 帧，避免零长度区间
            end = start + 1
        intervals.append(
            PhonemeInterval(phoneme=tok, start_frame=start, end_frame=end)
        )
    # 末尾对齐到总帧数
    intervals[-1].end_frame = duration_frames
    return intervals


def _make_waveform(num_samples: int) -> np.ndarray:
    """生成低幅正弦占位波形（mono, float32）。"""
    if num_samples <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(num_samples, dtype=np.float32) / SAMPLE_RATE
    wave = _TONE_AMP * np.sin(2.0 * np.pi * _TONE_HZ * t)
    return wave.astype(np.float32)


@register("tts", "mock")
class MockTTS(TTSBackend):
    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        audio_id = storage.new_id("aud")

        tokens = _tokenize(req.text, req.language)
        duration_sec = _estimate_duration(tokens, req.language, req.speed)
        duration_frames = round(duration_sec * fps)

        # 生成并写入占位 wav
        num_samples = int(round(duration_sec * SAMPLE_RATE))
        waveform = _make_waveform(num_samples)
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"
        sf.write(str(wav_path), waveform, SAMPLE_RATE)

        # 伪音素时间戳
        phoneme_intervals = _build_phoneme_intervals(tokens, duration_frames)

        # 可选：dump 音素到 json，便于排查
        phonemes_path = out_dir / "phonemes.json"
        phonemes_path.write_text(
            json.dumps(
                [pi.model_dump() for pi in phoneme_intervals],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return AudioWithTimestamps(
            audio_id=audio_id,
            audio_path=str(wav_path),
            duration_sec=duration_sec,
            duration_frames=duration_frames,
            sample_rate=SAMPLE_RATE,
            phoneme_intervals=phoneme_intervals,
        )


def _ensure_backend_registered(backend: str) -> None:
    """按需导入真实 TTS 后端，避免 Mock 链路加载重依赖。"""
    if backend not in {"local", "indextts", "qwen3"}:
        return
    try:
        get_backend("tts", backend)
        return
    except ValueError:
        pass

    if backend == "local":
        try:
            import app.services.tts.cosyvoice  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                "local TTS 后端不可用：无法加载 app.services.tts.cosyvoice。"
                "请安装 requirements-tts.txt 中的可选依赖，并确认 CosyVoice 模型已准备好。"
            ) from exc
        return

    if backend == "indextts":
        try:
            import app.services.tts.indextts  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                "indextts TTS 后端不可用：无法加载 app.services.tts.indextts。"
                "请按 requirements-tts-indextts.txt 准备 IndexTTS2 仓库、依赖和权重。"
            ) from exc
        return

    try:
        import app.services.tts.qwen3  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "qwen3 TTS 后端不可用：无法加载 app.services.tts.qwen3。"
            "请确认 qwen-tts 可选依赖和 Qwen3-TTS 模型目录已准备好。"
        ) from exc


def run_tts(req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
    backend = settings.tts_backend
    _ensure_backend_registered(backend)
    return get_backend("tts", backend)().run(req, fps)
