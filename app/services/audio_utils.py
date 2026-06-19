"""Small audio file helpers."""
from __future__ import annotations

import wave
from pathlib import Path


def trim_audio(src_path: str, end_sec: float, dst_path: str) -> None:
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if end_sec <= 0:
        raise ValueError("end_sec must be positive")

    with wave.open(str(src), "rb") as reader:
        params = reader.getparams()
        sample_rate = reader.getframerate()
        if sample_rate <= 0:
            raise ValueError(f"invalid sample rate: {src}")

        frames_to_copy = min(
            reader.getnframes(),
            max(1, int(round(end_sec * sample_rate))),
        )
        audio = reader.readframes(frames_to_copy)

    with wave.open(str(dst), "wb") as writer:
        writer.setparams(params)
        writer.setnframes(frames_to_copy)
        writer.writeframes(audio)
