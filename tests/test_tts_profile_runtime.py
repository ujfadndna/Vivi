from __future__ import annotations

import base64
import json
from io import BytesIO

import numpy as np
import soundfile as sf

from app import profile_store
from app.config import settings
from app.schemas import SynthesizeRequest
from app.services.tts.indextts import IndexTTSHttpBackend


def test_indextts_http_uses_profile_api_url(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "indextts_api_url", "http://settings")
    monkeypatch.setattr(profile_store, "resolve_tts_api_url", lambda: "http://profile")
    captured_urls: list[str] = []

    audio_buf = BytesIO()
    sf.write(audio_buf, np.zeros(800, dtype=np.float32), 16000, format="WAV")
    audio_b64 = base64.b64encode(audio_buf.getvalue()).decode("ascii")

    class FakeUrlOpenResponse:
        def read(self) -> bytes:
            return json.dumps({"audio_b64": audio_b64}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return FakeUrlOpenResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    audio = IndexTTSHttpBackend().run(SynthesizeRequest(text="你好"), fps=25)

    assert captured_urls == ["http://profile/synthesize"]
    assert audio.duration_sec == 0.05
    assert audio.sample_rate == 16000


def test_indextts_http_request_url_overrides_profile_api_url(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "indextts_api_url", "http://settings")
    monkeypatch.setattr(profile_store, "resolve_tts_api_url", lambda: "http://profile")
    captured_urls: list[str] = []

    audio_buf = BytesIO()
    sf.write(audio_buf, np.zeros(800, dtype=np.float32), 16000, format="WAV")
    audio_b64 = base64.b64encode(audio_buf.getvalue()).decode("ascii")

    class FakeUrlOpenResponse:
        def read(self) -> bytes:
            return json.dumps({"audio_b64": audio_b64}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return FakeUrlOpenResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    audio = IndexTTSHttpBackend().run(
        SynthesizeRequest(text="你好", tts_api_url="http://request-tts"),
        fps=25,
    )

    assert captured_urls == ["http://request-tts/synthesize"]
    assert audio.duration_sec == 0.05
    assert audio.sample_rate == 16000
