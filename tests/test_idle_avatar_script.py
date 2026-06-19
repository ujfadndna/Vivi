from __future__ import annotations

import wave

from scripts.render_idle_avatar import _write_idle_audio


def test_write_idle_audio_creates_expected_duration(tmp_path):
    path = tmp_path / "idle.wav"

    _write_idle_audio(path, duration_sec=2.0, sample_rate=16000, level=0.0015)

    assert path.exists()
    assert path.stat().st_size > 0
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 32000
