from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import soundfile as sf

from app import storage
from app.schemas import AudioWithTimestamps, PhonemeInterval, SynthesizeRequest
from app.services.base import register
from app.services.tts.base import TTSBackend, _build_phoneme_intervals, _tokenize

_DEFAULT_SFT_MODEL_DIR = "pretrained_models/CosyVoice-300M-SFT"
_DEFAULT_ZERO_SHOT_MODEL_DIR = "pretrained_models/CosyVoice-300M"
_INSTALL_HINT = (
    "请先查看 requirements-tts.txt 安装真实 TTS 可选依赖，"
    "并确认 CosyVoice 源码包和模型权重已准备好。"
)
_LOGGER = logging.getLogger(__name__)

_MODELS: dict[tuple[str, str], Any] = {}

_LANGUAGE_SPEAKERS: dict[str, tuple[str, ...]] = {
    "zh": ("中文女", "中文男"),
    "en": ("英文女", "英文男"),
    "ja": ("日语男", "日语女"),
    "ko": ("韩语女", "韩语男"),
    "yue": ("粤语女", "中文女"),
}

_EMOTION_INSTRUCTIONS: dict[str, str] = {
    "neutral": "自然、中性的语气",
    "happy": "开心、明亮的语气",
    "sad": "低落、悲伤的语气",
    "angry": "生气、有力度的语气",
}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _model_name(model_factory: Any) -> str:
    return (
        f"{getattr(model_factory, '__module__', '')}."
        f"{getattr(model_factory, '__name__', model_factory.__class__.__name__)}"
    )


def _get_model(model_dir: str, model_factory: Any) -> Any:
    """按模型目录缓存 CosyVoice，避免每次请求重复加载权重。"""
    model_key = (model_dir, _model_name(model_factory))
    if model_key in _MODELS:
        return _MODELS[model_key]

    if getattr(model_factory, "__name__", "") == "AutoModel":
        model = model_factory(model_dir=model_dir)
    else:
        try:
            model = model_factory(
                model_dir,
                load_jit=_bool_env("COSYVOICE_LOAD_JIT"),
                load_trt=_bool_env("COSYVOICE_LOAD_TRT"),
                fp16=_bool_env("COSYVOICE_FP16"),
            )
        except TypeError:
            model = model_factory(model_dir)

    _MODELS[model_key] = model
    return model


def _select_cosyvoice_factory(cosyvoice_module: Any, model_dir: str) -> Any:
    """按模型族选择 CosyVoice 类，兼容官方不同版本导出。"""
    auto_model = getattr(cosyvoice_module, "AutoModel", None)
    if auto_model is not None:
        return auto_model

    if "cosyvoice2" in model_dir.lower():
        cosyvoice2 = getattr(cosyvoice_module, "CosyVoice2", None)
        if cosyvoice2 is not None:
            return cosyvoice2

    cosyvoice = getattr(cosyvoice_module, "CosyVoice", None)
    if cosyvoice is not None:
        return cosyvoice

    cosyvoice2 = getattr(cosyvoice_module, "CosyVoice2", None)
    if cosyvoice2 is not None:
        return cosyvoice2

    raise RuntimeError("cosyvoice.cli.cosyvoice 未导出可用的 CosyVoice 类")


def _speaker_wav_path(speaker_id: str | None) -> Path | None:
    """speaker_id 指向本地 wav 时，按零样本音色克隆处理。"""
    if not speaker_id:
        return None
    path = Path(speaker_id).expanduser()
    if path.is_file() and path.suffix.lower() == ".wav":
        return path
    return None


def _select_model_dir(prompt_path: Path | None) -> str:
    """允许显式指定模型；未指定时按默认音色/零样本场景分流。"""
    explicit = os.getenv("COSYVOICE_MODEL_DIR")
    if explicit:
        return explicit.strip()
    if prompt_path is not None:
        return os.getenv("COSYVOICE_ZERO_SHOT_MODEL_DIR", _DEFAULT_ZERO_SHOT_MODEL_DIR)
    return os.getenv("COSYVOICE_SFT_MODEL_DIR", _DEFAULT_SFT_MODEL_DIR)


def _language_name(language: str) -> str:
    language = language.lower()
    if language.startswith("zh"):
        return "中文"
    if language.startswith("en"):
        return "英文"
    if language.startswith("ja"):
        return "日语"
    if language.startswith("ko"):
        return "韩语"
    return language or "目标语言"


def _instruction_text(req: SynthesizeRequest) -> str:
    """把情绪和语言转成 CosyVoice instruct 文本。"""
    emotion = _EMOTION_INSTRUCTIONS.get(
        req.emotion.lower(), _EMOTION_INSTRUCTIONS["neutral"]
    )
    return f"请用{_language_name(req.language)}，以{emotion}朗读。"


def _available_speakers(model: Any) -> list[str]:
    for name in ("list_available_spks", "list_avaliable_spks"):
        method = getattr(model, name, None)
        if method is None:
            continue
        try:
            speakers = method()
        except Exception:
            continue
        if speakers:
            return [str(spk) for spk in speakers]

    frontend = getattr(model, "frontend", None)
    spk2info = getattr(frontend, "spk2info", None)
    if isinstance(spk2info, dict):
        return list(spk2info.keys())
    return []


def _default_speaker(model: Any, language: str) -> str:
    """优先使用环境变量，其次按语言挑选模型自带音色。"""
    env_spk = os.getenv("COSYVOICE_SPK") or os.getenv("COSYVOICE_SPK_ID")
    if env_spk:
        return env_spk

    speakers = _available_speakers(model)
    lang = language.lower()
    preferred = _LANGUAGE_SPEAKERS.get(lang[:2], _LANGUAGE_SPEAKERS["zh"])
    for spk_id in preferred:
        if not speakers or spk_id in speakers:
            return spk_id
    return speakers[0] if speakers else "中文女"


def _call_zero_shot(
    model: Any,
    req: SynthesizeRequest,
    prompt_wav: Any,
    speed: float,
) -> Iterable[Any]:
    if not hasattr(model, "inference_zero_shot"):
        raise RuntimeError("当前 CosyVoice 模型不支持 inference_zero_shot")

    prompt_text = os.getenv("COSYVOICE_PROMPT_TEXT", "")
    zero_shot_spk_id = os.getenv("COSYVOICE_ZERO_SHOT_SPK_ID", "")
    try:
        return model.inference_zero_shot(
            req.text,
            prompt_text,
            prompt_wav,
            zero_shot_spk_id=zero_shot_spk_id,
            stream=False,
            speed=speed,
        )
    except TypeError:
        return model.inference_zero_shot(
            req.text,
            prompt_text,
            prompt_wav,
            stream=False,
            speed=speed,
        )


def _call_default_voice(
    model: Any,
    req: SynthesizeRequest,
    speed: float,
) -> Iterable[Any]:
    spk_id = _default_speaker(model, req.language)
    instruct = _instruction_text(req)

    if req.emotion.lower() != "neutral" and hasattr(model, "inference_instruct"):
        try:
            return model.inference_instruct(
                req.text,
                spk_id,
                instruct,
                stream=False,
                speed=speed,
            )
        except AssertionError:
            # CosyVoice2/3 的 instruct 接口需要 prompt wav，这里退回默认音色。
            pass

    if hasattr(model, "inference_sft"):
        return model.inference_sft(req.text, spk_id, stream=False, speed=speed)

    if hasattr(model, "inference_instruct"):
        return model.inference_instruct(
            req.text,
            spk_id,
            instruct,
            stream=False,
            speed=speed,
        )

    raise RuntimeError("当前 CosyVoice 模型不支持 inference_sft/inference_instruct")


def _tensor_to_numpy(audio: Any) -> np.ndarray:
    """把 CosyVoice 输出的 torch Tensor 或数组转成 mono float32。"""
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().float().numpy()
    arr = np.asarray(audio, dtype=np.float32)
    arr = np.squeeze(arr)
    if arr.ndim > 1:
        if arr.shape[0] <= 8:
            arr = arr.mean(axis=0)
        else:
            arr = arr.mean(axis=-1)
    return np.ravel(arr).astype(np.float32)


def _collect_waveform(
    outputs: Iterable[Any] | dict[str, Any] | Any,
    model: Any,
) -> tuple[np.ndarray, int]:
    """收集 CosyVoice 输出片段，并读取模型或输出中的原生采样率。"""
    sample_rate = int(getattr(model, "sample_rate", 0) or 0)
    chunks: list[np.ndarray] = []

    if isinstance(outputs, dict) or isinstance(outputs, np.ndarray) or hasattr(
        outputs, "detach"
    ):
        iterable_outputs = (outputs,)
    else:
        iterable_outputs = outputs

    for item in iterable_outputs:
        speech = item
        if isinstance(item, dict):
            for key in ("tts_speech", "speech", "audio", "wav"):
                if key in item:
                    speech = item[key]
                    break
            if sample_rate <= 0:
                for key in ("sample_rate", "sampling_rate", "sr"):
                    value = item.get(key)
                    if value:
                        sample_rate = int(value)
                        break

        chunk = _tensor_to_numpy(speech)
        if chunk.size:
            chunks.append(chunk)

    if sample_rate <= 0:
        raise RuntimeError("无法从 CosyVoice 输出读取原生采样率")
    if not chunks:
        raise RuntimeError("CosyVoice 未返回有效音频")
    return np.concatenate(chunks).astype(np.float32), sample_rate


def _synthesize_and_collect(
    model: Any,
    req: SynthesizeRequest,
    speed: float,
    prompt_path: Path | None,
    load_wav: Any | None,
) -> tuple[np.ndarray, int]:
    if prompt_path is None:
        outputs = _call_default_voice(model, req, speed)
        return _collect_waveform(outputs, model)

    errors: list[str] = []
    prompt_candidates: list[Any] = [str(prompt_path)]
    for prompt_wav in prompt_candidates:
        try:
            outputs = _call_zero_shot(model, req, prompt_wav, speed)
            return _collect_waveform(outputs, model)
        except Exception as exc:
            errors.append(str(exc))

    if load_wav is not None:
        try:
            prompt_wav = load_wav(str(prompt_path), 16000)
            outputs = _call_zero_shot(model, req, prompt_wav, speed)
            return _collect_waveform(outputs, model)
        except Exception as exc:
            errors.append(str(exc))

    hint = ""
    if not os.getenv("COSYVOICE_PROMPT_TEXT"):
        hint = "；零样本克隆通常需要设置 COSYVOICE_PROMPT_TEXT，且内容应与 prompt wav 一致"
    raise RuntimeError(f"零样本音色克隆失败{hint}；尝试结果：{errors}")


def _language_code(language: str) -> str:
    language = language.lower()
    if language.startswith("zh"):
        return "zh"
    if language.startswith("en"):
        return "en"
    if language.startswith("ja"):
        return "ja"
    if language.startswith("ko"):
        return "ko"
    return language[:2] or "zh"


def _word_intervals_from_alignment(
    aligned: dict[str, Any],
    fps: float,
    duration_frames: int,
) -> list[PhonemeInterval]:
    words = aligned.get("word_segments") or []
    if not words:
        for segment in aligned.get("segments", []):
            words.extend(segment.get("words") or [])

    intervals: list[PhonemeInterval] = []
    for word in words:
        text = str(word.get("word") or word.get("text") or "").strip()
        start = word.get("start")
        end = word.get("end")
        if not text or start is None or end is None:
            continue
        start_frame = max(0, min(duration_frames, round(float(start) * fps)))
        end_frame = max(0, min(duration_frames, round(float(end) * fps)))
        if end_frame <= start_frame:
            end_frame = min(duration_frames, start_frame + 1)
        if end_frame > start_frame:
            intervals.append(
                PhonemeInterval(
                    phoneme=text,
                    start_frame=start_frame,
                    end_frame=end_frame,
                )
            )
    return intervals


def _align_with_whisperx(
    whisperx: Any,
    torch: Any,
    wav_path: Path,
    req: SynthesizeRequest,
    fps: float,
    duration_frames: int,
) -> list[PhonemeInterval]:
    """使用 WhisperX 做词级强制对齐，失败时由调用方降级。"""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    language = _language_code(req.language)
    batch_size = int(os.getenv("WHISPERX_BATCH_SIZE", "16"))
    model_name = os.getenv("WHISPERX_MODEL", "large-v3")

    model = whisperx.load_model(model_name, device, compute_type=compute_type)
    audio = whisperx.load_audio(str(wav_path))
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    align_language = result.get("language") or language
    align_model, metadata = whisperx.load_align_model(
        language_code=align_language,
        device=device,
    )
    aligned = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        device,
        return_char_alignments=False,
    )
    return _word_intervals_from_alignment(aligned, fps, duration_frames)


def _dump_phonemes(out_dir: Path, intervals: list[PhonemeInterval]) -> None:
    """写出真实后端时间戳，便于排查 WhisperX 或退化策略结果。"""
    phonemes_path = out_dir / "phonemes.json"
    phonemes_path.write_text(
        json.dumps(
            [pi.model_dump() for pi in intervals],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


@register("tts", "local")
class CosyVoiceTTS(TTSBackend):
    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        audio_id = storage.new_id("aud")
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"

        if not req.text.strip():
            raise ValueError("CosyVoice TTS 合成失败：输入文本不能为空")

        try:
            import torch
        except Exception as exc:
            raise RuntimeError(
                "本地 CosyVoice TTS 依赖未安装：缺少 torch。"
                f"{_INSTALL_HINT}"
            ) from exc

        try:
            from cosyvoice.cli import cosyvoice as cosyvoice_module
        except Exception as exc:
            raise RuntimeError(
                "本地 CosyVoice TTS 依赖未安装或不可用：缺少 cosyvoice。"
                f"{_INSTALL_HINT}"
            ) from exc

        try:
            from cosyvoice.utils.file_utils import load_wav
        except Exception:
            load_wav = None

        speed = req.speed if req.speed > 0 else 1.0
        prompt_path = _speaker_wav_path(req.speaker_id)
        model_dir = _select_model_dir(prompt_path).strip()
        if not model_dir:
            raise RuntimeError("CosyVoice 模型目录不能为空")
        cosyvoice_factory = _select_cosyvoice_factory(cosyvoice_module, model_dir)

        try:
            model = _get_model(model_dir, cosyvoice_factory)
        except Exception as exc:
            raise RuntimeError(
                "CosyVoice 模型加载失败：请确认模型目录已下载并可访问。"
                f"当前值：{model_dir!r}"
            ) from exc

        try:
            waveform, sample_rate = _synthesize_and_collect(
                model,
                req,
                speed,
                prompt_path,
                load_wav,
            )
        except Exception as exc:
            raise RuntimeError(f"CosyVoice TTS 合成失败：{exc}") from exc

        sf.write(str(wav_path), waveform, sample_rate, subtype="FLOAT")
        duration_sec = float(waveform.shape[0]) / float(sample_rate)
        duration_frames = round(duration_sec * fps)

        phoneme_intervals: list[PhonemeInterval] = []
        try:
            import whisperx
        except Exception as exc:
            _LOGGER.info("WhisperX 不可用，退化为均匀时间戳：%s", exc)
        else:
            try:
                phoneme_intervals = _align_with_whisperx(
                    whisperx,
                    torch,
                    wav_path,
                    req,
                    fps,
                    duration_frames,
                )
            except Exception as exc:
                _LOGGER.warning("WhisperX 对齐失败，退化为均匀时间戳：%s", exc)

        if not phoneme_intervals:
            tokens = _tokenize(req.text, req.language)
            phoneme_intervals = _build_phoneme_intervals(tokens, duration_frames)

        _dump_phonemes(out_dir, phoneme_intervals)

        return AudioWithTimestamps(
            audio_id=audio_id,
            audio_path=str(wav_path),
            duration_sec=duration_sec,
            duration_frames=duration_frames,
            sample_rate=sample_rate,
            phoneme_intervals=phoneme_intervals,
        )
