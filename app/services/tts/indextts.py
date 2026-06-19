from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import soundfile as sf

from app import storage
from app.config import settings
from app.schemas import AudioWithTimestamps, PhonemeInterval, SynthesizeRequest
from app.services.base import register
from app.services.tts.base import TTSBackend, _build_phoneme_intervals, _tokenize
from app.services.tts.cosyvoice import _align_with_whisperx, _dump_phonemes

_INSTALL_HINT = (
    "请先查看 requirements-tts-indextts.txt 准备 IndexTTS2："
    "默认仓库路径为 ./third_party/IndexTTS，默认权重路径为 ./models/IndexTTS-2。"
    "本后端已按本机 IndexTTS2 源码适配 API："
    "`from indextts.infer_v2 import IndexTTS2`，"
    "构造参数为 cfg_path/model_dir/use_fp16/use_deepspeed，"
    "推理参数为 spk_audio_prompt/text/output_path。"
)
_LOGGER = logging.getLogger(__name__)

_MODEL: Any | None = None
_MODEL_KEY: tuple[str, str, bool, bool] | None = None
_MODEL_LOCK: threading.Lock = threading.Lock()


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _add_repo_to_path(repo: Path) -> None:
    repo_str = str(repo)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


def _validate_paths(repo: Path, checkpoints: Path) -> Path:
    if not repo.is_dir():
        raise RuntimeError(
            "IndexTTS2 仓库目录不存在或不可访问。"
            f"当前 INDEXTTS_REPO={str(repo)!r}。{_INSTALL_HINT}"
        )
    if not checkpoints.is_dir():
        raise RuntimeError(
            "IndexTTS2 权重目录不存在或不可访问。"
            f"当前 INDEXTTS_CHECKPOINTS={str(checkpoints)!r}。{_INSTALL_HINT}"
        )

    cfg_path = checkpoints / "config.yaml"
    if not cfg_path.is_file():
        raise RuntimeError(
            "IndexTTS2 配置文件缺失：未找到 checkpoints/config.yaml。"
            f"当前 cfg_path={str(cfg_path)!r}。{_INSTALL_HINT}"
        )
    return cfg_path


def _load_model() -> Any:
    """懒加载并缓存 IndexTTS2，避免 Mock 链路和重复请求加载重依赖。"""
    global _MODEL, _MODEL_KEY

    repo = _resolve(settings.indextts_repo)
    checkpoints = _resolve(settings.indextts_checkpoints)
    use_fp16 = bool(settings.indextts_use_fp16)
    use_deepspeed = bool(settings.indextts_use_deepspeed)
    model_key = (str(repo), str(checkpoints), use_fp16, use_deepspeed)

    # Fast path: 已加载，无需加锁
    if _MODEL is not None and _MODEL_KEY == model_key:
        return _MODEL

    # Slow path: 加锁后再次检查，防止并发线程重复加载
    with _MODEL_LOCK:
        if _MODEL is not None and _MODEL_KEY == model_key:
            return _MODEL

        cfg_path = _validate_paths(repo, checkpoints)
        _add_repo_to_path(repo)

        try:
            from indextts.infer_v2 import IndexTTS2
        except Exception as exc:
            raise RuntimeError(
                "IndexTTS2 依赖未安装或不可用：无法导入 indextts.infer_v2。"
                f"{_INSTALL_HINT}"
            ) from exc

        try:
            # 对齐官方 indextts/infer_v2.py 中 IndexTTS2 的基础参数。
            model_kwargs: dict[str, Any] = {
                "cfg_path": str(cfg_path),
                "model_dir": str(checkpoints),
                "use_fp16": use_fp16,
                "use_deepspeed": use_deepspeed,
            }
            model = IndexTTS2(**model_kwargs)
        except Exception as exc:
            raise RuntimeError(
                "IndexTTS2 模型加载失败：请确认仓库依赖、config.yaml 和权重已准备好。"
                f"repo={str(repo)!r}, checkpoints={str(checkpoints)!r}, "
                f"use_fp16={use_fp16!r}, use_deepspeed={use_deepspeed!r}。"
                f"{_INSTALL_HINT}"
            ) from exc

        _MODEL = model
        _MODEL_KEY = model_key
        return model


def _speaker_wav_path(speaker_id: str | None) -> Path:
    if not speaker_id:
        raise RuntimeError(
            "IndexTTS2 音色克隆需要 speaker_id 指向本地 .wav 参考音频。"
            "如果你使用的官方版本支持默认音色，请按 README 调整推理参数；"
            "否则请传入可访问的 .wav 路径。"
        )

    path = Path(speaker_id).expanduser()
    if path.is_file() and path.suffix.lower() == ".wav":
        return path.resolve()
    raise RuntimeError(
        "IndexTTS2 speaker_id 必须是存在的本地 .wav 参考音频路径。"
        f"当前 speaker_id={speaker_id!r}。"
    )


def _emotion_to_vector(emotion: str | None) -> list[float] | None:
    if emotion is None:
        return None

    normalized = emotion.strip().lower()
    if normalized in {"warm", "happy"}:
        return [0.6, 0, 0, 0, 0, 0, 0, 0.2]
    if normalized in {"calm", "neutral"}:
        return [0, 0, 0, 0, 0, 0, 0, 0.7]
    if normalized == "sad":
        return [0, 0, 0.5, 0, 0, 0.3, 0, 0]
    if normalized == "excited":
        return [0.5, 0, 0, 0, 0, 0, 0.3, 0]
    return None


def _infer(model: Any, req: SynthesizeRequest, prompt_path: Path, wav_path: Path) -> None:
    import torch
    torch.manual_seed(42)
    infer_kwargs: dict[str, Any] = {
        "spk_audio_prompt": str(prompt_path),
        "text": req.text,
        "output_path": str(wav_path),
        "temperature": 0.3,
        "top_p": 0.7,
    }
    emo_vector = _emotion_to_vector(req.emotion)
    if emo_vector is not None:
        infer_kwargs["emo_vector"] = emo_vector

    try:
        model.infer(**infer_kwargs)
    except TypeError as exc:
        raise RuntimeError(
            "IndexTTS2 infer 调用失败：当前实现假设 "
            "infer(spk_audio_prompt=..., text=..., output_path=...)，"
            "该签名来自官方 indextts/infer_v2.py。"
        ) from exc


def _read_audio_info(wav_path: Path) -> tuple[float, int]:
    try:
        info = sf.info(str(wav_path))
    except Exception as exc:
        raise RuntimeError(f"无法读取 IndexTTS2 输出 wav：{wav_path}") from exc

    sample_rate = int(info.samplerate)
    frames = int(info.frames)
    if sample_rate <= 0 or frames <= 0:
        raise RuntimeError(
            "IndexTTS2 输出音频无效："
            f"sample_rate={sample_rate!r}, frames={frames!r}, path={str(wav_path)!r}"
        )
    return frames / float(sample_rate), sample_rate


def _normalize_loudness(wav_path: Path, target_rms: float = 0.15) -> None:
    """将输出 wav 归一化到固定 RMS，消除句间音量漂移。"""
    import numpy as np
    data, sr = sf.read(str(wav_path))
    rms = float(np.sqrt(np.mean(data ** 2)))
    if rms < 1e-6:
        return
    data = data * (target_rms / rms)
    data = np.clip(data, -1.0, 1.0)
    sf.write(str(wav_path), data, sr)


@register("tts", "indextts_http")
class IndexTTSHttpBackend(TTSBackend):
    """Calls IndexTTS2 via HTTP service (port 8200)."""

    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        import base64, io, json, urllib.request

        from app import profile_store

        api_url = (req.tts_api_url or "").strip() or profile_store.resolve_tts_api_url()
        if not api_url:
            raise RuntimeError("INDEXTTS_API_URL not set")

        data = json.dumps({"text": req.text}).encode()
        http_req = urllib.request.Request(
            f"{api_url}/synthesize", data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(http_req, timeout=300)
        result = json.loads(resp.read().decode())

        audio_bytes = base64.b64decode(result["audio_b64"])
        audio_buf = io.BytesIO(audio_bytes)
        audio_data, sr = sf.read(audio_buf)

        audio_id = storage.new_id("aud")
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"
        sf.write(str(wav_path), audio_data, sr)

        duration_sec = len(audio_data) / sr
        duration_frames = max(1, round(duration_sec * fps))

        return AudioWithTimestamps(
            audio_id=audio_id, audio_path=str(wav_path),
            duration_sec=duration_sec, duration_frames=duration_frames,
            sample_rate=int(sr),
            phoneme_intervals=_build_phoneme_intervals(
                _tokenize(req.text, req.language), duration_frames,
            ),
        )


@register("tts", "indextts")
class IndexTTSBackend(TTSBackend):
    def run(self, req: SynthesizeRequest, fps: float) -> AudioWithTimestamps:
        audio_id = storage.new_id("aud")
        out_dir = storage.audio_dir(audio_id)
        wav_path = out_dir / "tts.wav"

        if not req.text.strip():
            raise ValueError("IndexTTS2 TTS 合成失败：输入文本不能为空")

        prompt_path = _speaker_wav_path(req.speaker_id)
        model = _load_model()

        try:
            _infer(model, req, prompt_path, wav_path)
        except Exception as exc:
            raise RuntimeError(f"IndexTTS2 TTS 合成失败：{exc}") from exc

        if not wav_path.is_file() or wav_path.stat().st_size <= 0:
            raise RuntimeError(
                "IndexTTS2 TTS 合成失败：未生成有效 tts.wav。"
                f"输出路径={str(wav_path)!r}。"
            )

        _normalize_loudness(wav_path)
        duration_sec, sample_rate = _read_audio_info(wav_path)
        duration_frames = round(duration_sec * fps)

        phoneme_intervals: list[PhonemeInterval] = []
        try:
            import torch
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
