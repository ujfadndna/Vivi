"""MVP-1 Tier 1 计时基准测试 - MuseTalk Worker 冷启动 vs 热启动"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import soundfile as sf


def find_audio() -> Path | None:
    workspace = Path("workspace/audio")
    if not workspace.exists():
        return None
    for wav in sorted(workspace.rglob("tts.wav")):
        phonemes = wav.parent / "phonemes.json"
        if phonemes.exists():
            return wav.parent
    return None


def main() -> None:
    print("=" * 60)
    print("MVP-1 Tier 1 基准测试：MuseTalk Worker 热启动计时")
    print("=" * 60)

    from app.services.ingest import run_ingest
    from app.services.musetalk import run_musetalk
    from app.services.musetalk.persistent import worker_manager
    from app.schemas import AudioWithTimestamps, PhonemeInterval
    from app.storage import new_id

    avatar = Path("workspace/avatar/default.mp4")
    if not avatar.exists():
        print(f"ERROR: Avatar 视频不存在: {avatar}")
        sys.exit(1)

    audio_dir = find_audio()
    if audio_dir is None:
        print("ERROR: 找不到已有 tts.wav，请先跑一次 TTS 生成音频")
        sys.exit(1)

    print(f"\n[素材] avatar={avatar}  audio={audio_dir}")

    # ── 素材接入 ──────────────────────────────────────────────────
    print("\n[1] 素材接入...")
    t0 = time.time()
    video = run_ingest(str(avatar))
    print(f"    {time.time()-t0:.1f}s  frames={video.num_frames}  fps={video.fps}")

    # ── 重建 AudioWithTimestamps ──────────────────────────────────
    wav_path = audio_dir / "tts.wav"
    info = sf.info(str(wav_path))
    phonemes_raw = json.loads((audio_dir / "phonemes.json").read_bytes())
    audio = AudioWithTimestamps(
        audio_id=audio_dir.name,
        audio_path=str(wav_path),
        duration_sec=info.duration,
        duration_frames=round(info.duration * video.fps),
        sample_rate=info.samplerate,
        phoneme_intervals=[PhonemeInterval(**p) for p in phonemes_raw],
    )
    print(f"[2] 音频: duration={info.duration:.1f}s  frames={audio.duration_frames}")

    # ── Worker 启动 ───────────────────────────────────────────────
    print("\n[3] 启动 MuseTalk Worker...")
    t0 = time.time()
    worker_manager.start()
    print(f"    进程已启动 PID={worker_manager._proc.pid}  {time.time()-t0:.2f}s")

    # ── 第一次推理（含模型加载）──────────────────────────────────
    print("\n[4] 第一次推理（含 Worker 内模型加载）...")
    t0 = time.time()
    frames1 = run_musetalk(video, audio, new_id("bench"))
    t1 = time.time() - t0
    print(f"    耗时: {t1:.0f}s  frames={frames1.num_frames}")

    # ── 第二次推理（热启动）──────────────────────────────────────
    print("\n[5] 第二次推理（Worker 热启动）...")
    t0 = time.time()
    frames2 = run_musetalk(video, audio, new_id("bench"))
    t2 = time.time() - t0
    print(f"    耗时: {t2:.0f}s  frames={frames2.num_frames}")

    # ── 结果 ─────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("MVP-1 Tier 1 实测结果")
    print(f"  第一次（冷启动含模型加载）: {t1:.0f}s")
    print(f"  第二次（Worker 热启动）:    {t2:.0f}s  目标 ≤ 60s → {'✅ 达标' if t2 <= 60 else '❌ 超标'}")
    if t2 > 0:
        print(f"  提升倍数: {t1 / t2:.1f}x")
    print("=" * 60)

    worker_manager.stop()


if __name__ == "__main__":
    main()
