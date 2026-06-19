from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app import profile_store
from app import storage
from app.api.routes import generate as generate_route
from app.config import settings
from app.main import app
from app.schemas import AudioWithTimestamps, FrameSequence, VideoMetadata
from app.services.composite import run_composite


def _write_test_mp4(path: Path, frames: int = 8, fps: float = 25.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (96, 64))
    assert writer.isOpened(), "failed to create test mp4"
    for i in range(frames):
        frame = np.full((64, 96, 3), 40 + i * 8, dtype=np.uint8)
        cv2.rectangle(frame, (10 + i, 20), (40 + i, 45), (180, 120, 80), -1)
        writer.write(frame)
    writer.release()


def _read_frame_count(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened(), f"failed to open {path}"
        ok, _ = cap.read()
        assert ok, f"failed to decode first frame from {path}"
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def test_concat_videos_reencodes_to_single_decodable_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "default_fps", 25)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    first = outputs / "first.mp4"
    second = outputs / "second.mp4"
    _write_test_mp4(first, frames=7)
    _write_test_mp4(second, frames=9)

    merged_url = generate_route._concat_videos(
        ["/outputs/first.mp4", "/outputs/second.mp4"]
    )

    assert merged_url is not None
    assert merged_url.startswith("/outputs/")
    merged_path = tmp_path / merged_url.lstrip("/")
    assert merged_path.exists()
    assert merged_path.stat().st_size > 0
    assert _read_frame_count(merged_path) >= 14


def test_concat_videos_missing_input_returns_none(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    (tmp_path / "outputs").mkdir()

    merged_url = generate_route._concat_videos(["/outputs/missing.mp4"])

    assert merged_url is None
    assert "input missing" in caplog.text


def test_composite_scales_odd_frame_dimensions_for_h264(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    monkeypatch.setattr(settings, "composite_backend", "local")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for index in range(3):
        frame = np.full((51, 53, 3), 80 + index, dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"{index:08d}.png"), frame)

    wav_path = tmp_path / "tts.wav"
    import soundfile as sf

    sf.write(str(wav_path), np.zeros(1600, dtype=np.float32), 16000)
    audio = AudioWithTimestamps(
        audio_id="aud",
        audio_path=str(wav_path),
        duration_sec=0.1,
        duration_frames=3,
        sample_rate=16000,
    )
    frames = FrameSequence(
        output_frames_dir=str(frames_dir),
        num_frames=3,
        fps=25,
        full_frame=True,
    )

    result = run_composite(frames, None, audio, fps=25, task_id="odd_dims")

    output_path = tmp_path / "outputs" / "odd_dims.mp4"
    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert result.video_path == str(output_path)
    assert _read_frame_count(output_path) >= 1


def test_parse_sentence_list_accepts_json_and_newlines():
    assert generate_route._parse_sentence_list('[" 一 ", "", "二"]') == ["一", "二"]
    assert generate_route._parse_sentence_list("一\n\n 二 ") == ["一", "二"]


def test_join_sentences_for_tts_adds_missing_sentence_endings():
    assert (
        generate_route._join_sentences_for_tts(["第一句", "第二句！", "third?"], "zh")
        == "第一句。第二句！third?"
    )
    assert (
        generate_route._join_sentences_for_tts(["First", "Second!"], "en")
        == "First. Second!"
    )


def test_build_subtitle_segments_cover_full_audio_duration():
    audio = AudioWithTimestamps(
        audio_id="aud",
        audio_path="aud.wav",
        duration_sec=4.0,
        duration_frames=100,
        sample_rate=16000,
    )

    segments = generate_route._build_subtitle_segments(
        ["短句", "这是明显更长的一句", "收尾"],
        audio,
        fps=25,
    )

    assert [segment.text for segment in segments] == ["短句", "这是明显更长的一句", "收尾"]
    assert segments[0].start_sec == 0
    assert segments[-1].end_sec == 4.0
    assert all(
        left.end_sec <= right.start_sec
        for left, right in zip(segments, segments[1:])
    )
    assert all(segment.start_sec <= segment.end_sec for segment in segments)


def test_generate_text_batch_renders_full_text_once_without_concat(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.mp4"
    _write_test_mp4(avatar, frames=5)
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "default_avatar_video", avatar)
    monkeypatch.setattr(settings, "default_speaker_wav", tmp_path / "missing.wav")
    tts_calls: list[dict] = []
    generation_calls: list[dict] = []
    ingest_calls: list[str] = []

    def fake_run_ingest(path: str) -> VideoMetadata:
        ingest_calls.append(path)
        assert path == str(avatar)
        return VideoMetadata(
            video_id="avatar",
            fps=25,
            num_frames=5,
            duration_sec=0.2,
            resolution=(96, 64),
            face_bbox=(0, 0, 96, 64),
            frames_dir=str(tmp_path / "frames"),
        )

    def fake_run_tts_only(
        task_id: str,
        text: str,
        fps: float = 25.0,
        speaker_id: str | None = None,
        tts_api_url: str | None = None,
        language: str = "zh",
        emotion: str = "neutral",
        speed: float = 1.0,
    ) -> AudioWithTimestamps:
        tts_calls.append(
            {
                "task_id": task_id,
                "text": text,
                "fps": fps,
                "speaker_id": speaker_id,
                "tts_api_url": tts_api_url,
                "language": language,
                "emotion": emotion,
                "speed": speed,
            }
        )
        return AudioWithTimestamps(
            audio_id=task_id,
            audio_path=str(tmp_path / f"{task_id}.wav"),
            duration_sec=0.1,
            duration_frames=3,
            sample_rate=16000,
        )

    class FakeOutput(str):
        video_url: str

        def __new__(cls, video_url: str):
            obj = str.__new__(cls, str(tmp_path / video_url.rsplit("/", 1)[-1]))
            obj.video_url = video_url
            return obj

    def fake_run_generation_from_audio(**kwargs) -> FakeOutput:
        generation_calls.append(kwargs)
        url = f"/outputs/{kwargs['task_id']}.mp4"
        return FakeOutput(url)

    def fail_concat(video_urls: list[str]) -> str | None:
        raise AssertionError(f"_concat_videos should not be called: {video_urls}")

    monkeypatch.setattr("app.services.ingest.run_ingest", fake_run_ingest)
    monkeypatch.setattr("app.tasks.pipeline.run_tts_only", fake_run_tts_only)
    monkeypatch.setattr(
        "app.tasks.pipeline.run_generation_from_audio",
        fake_run_generation_from_audio,
    )
    monkeypatch.setattr(generate_route, "_concat_videos", fail_concat)

    client = TestClient(app)
    response = client.post(
        "/api/v1/generate-text-batch",
        data={
            "sentences": '["第一句", "第二句。", "第三句"]',
            "language": "zh",
            "emotion": "calm",
            "tts_api_url": "http://tts.example.com",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "completed"
    assert len(payload["video_urls"]) == 1
    assert payload["video_urls"][0].startswith("/outputs/")
    assert payload["duration_sec"] == 0.1
    assert [segment["text"] for segment in payload["subtitle_segments"]] == [
        "第一句",
        "第二句。",
        "第三句",
    ]
    assert payload["subtitle_segments"][0]["start_sec"] == 0
    assert payload["subtitle_segments"][-1]["end_sec"] == 0.1
    assert ingest_calls == [str(avatar)]
    assert len(tts_calls) == 1
    assert tts_calls[0]["task_id"] == "batch_tts_full"
    assert tts_calls[0]["text"] == "第一句。第二句。第三句。"
    assert tts_calls[0]["language"] == "zh"
    assert tts_calls[0]["emotion"] == "calm"
    assert tts_calls[0]["tts_api_url"] == "http://tts.example.com"
    assert len(generation_calls) == 1
    assert generation_calls[0]["audio"].audio_id == "batch_tts_full"


def test_generate_text_batch_prefers_profile_speaker_wav(tmp_path, monkeypatch):
    avatar = tmp_path / "avatar.mp4"
    speaker = tmp_path / "profile.wav"
    _write_test_mp4(avatar, frames=5)
    speaker.write_bytes(b"fake")
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "default_avatar_video", avatar)
    monkeypatch.setattr(settings, "default_speaker_wav", tmp_path / "fallback.wav")
    monkeypatch.setattr(profile_store, "resolve_speaker_wav", lambda: speaker)
    tts_speakers: list[str | None] = []

    def fake_run_ingest(path: str) -> VideoMetadata:
        return VideoMetadata(
            video_id="avatar",
            fps=25,
            num_frames=5,
            duration_sec=0.2,
            resolution=(96, 64),
            face_bbox=(0, 0, 96, 64),
            frames_dir=str(tmp_path / "frames"),
        )

    def fake_run_tts_only(*args, **kwargs) -> AudioWithTimestamps:
        tts_speakers.append(args[3])
        return AudioWithTimestamps(
            audio_id="batch_tts_full",
            audio_path=str(tmp_path / "tts.wav"),
            duration_sec=0.1,
            duration_frames=3,
            sample_rate=16000,
        )

    class FakeOutput(str):
        video_url: str

        def __new__(cls, video_url: str):
            obj = str.__new__(cls, str(tmp_path / video_url.rsplit("/", 1)[-1]))
            obj.video_url = video_url
            return obj

    def fake_run_generation_from_audio(**kwargs) -> FakeOutput:
        return FakeOutput("/outputs/full.mp4")

    monkeypatch.setattr("app.services.ingest.run_ingest", fake_run_ingest)
    monkeypatch.setattr("app.tasks.pipeline.run_tts_only", fake_run_tts_only)
    monkeypatch.setattr(
        "app.tasks.pipeline.run_generation_from_audio",
        fake_run_generation_from_audio,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/generate-text-batch",
        data={"sentences": '["第一句"]'},
    )

    assert response.status_code == 202
    assert tts_speakers == [str(speaker)]


def test_generate_text_batch_uses_default_avatar_image_without_video(tmp_path, monkeypatch):
    avatar_image = tmp_path / "avatar.png"
    cv2.imwrite(str(avatar_image), np.full((80, 64, 3), 30, dtype=np.uint8))
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "default_avatar_video", tmp_path / "missing.mp4")
    monkeypatch.setattr(settings, "default_avatar_image", avatar_image)
    monkeypatch.setattr(settings, "default_speaker_wav", tmp_path / "missing.wav")
    ingest_calls: list[str] = []
    generation_videos: list[VideoMetadata] = []

    def fake_run_ingest(path: str) -> VideoMetadata:
        ingest_calls.append(path)
        raise AssertionError("run_ingest should not be called when default video is absent")

    def fake_run_tts_only(*args, **kwargs) -> AudioWithTimestamps:
        return AudioWithTimestamps(
            audio_id="batch_tts_full",
            audio_path=str(tmp_path / "tts.wav"),
            duration_sec=0.1,
            duration_frames=3,
            sample_rate=16000,
        )

    class FakeOutput(str):
        video_url: str

        def __new__(cls, video_url: str):
            obj = str.__new__(cls, str(tmp_path / video_url.rsplit("/", 1)[-1]))
            obj.video_url = video_url
            return obj

    def fake_run_generation_from_audio(**kwargs) -> FakeOutput:
        generation_videos.append(kwargs["video"])
        return FakeOutput("/outputs/full.mp4")

    monkeypatch.setattr("app.services.ingest.run_ingest", fake_run_ingest)
    monkeypatch.setattr("app.tasks.pipeline.run_tts_only", fake_run_tts_only)
    monkeypatch.setattr(
        "app.tasks.pipeline.run_generation_from_audio",
        fake_run_generation_from_audio,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/generate-text-batch",
        data={"sentences": '["第一句", "第二句"]'},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["video_urls"] == ["/outputs/full.mp4"]
    assert payload["duration_sec"] == 0.1
    assert [segment["text"] for segment in payload["subtitle_segments"]] == ["第一句", "第二句"]
    assert ingest_calls == []
    assert len(generation_videos) == 1
    assert generation_videos[0].video_id == "default_avatar_image"
    assert generation_videos[0].resolution == (64, 80)
    assert generation_videos[0].frames_dir == str(tmp_path / "profiles" / "default")
    assert (tmp_path / "profiles" / "default" / "00000000.png").is_file()


def test_generate_text_batch_uses_uploaded_avatar_file(tmp_path, monkeypatch):
    avatar_image = tmp_path / "upload.png"
    cv2.imwrite(str(avatar_image), np.full((48, 32, 3), 120, dtype=np.uint8))
    monkeypatch.setattr(settings, "workspace_dir", tmp_path)
    monkeypatch.setattr(settings, "default_avatar_video", tmp_path / "missing.mp4")
    monkeypatch.setattr(settings, "default_avatar_image", tmp_path / "missing.png")
    monkeypatch.setattr(settings, "default_speaker_wav", tmp_path / "missing.wav")
    generation_videos: list[VideoMetadata] = []

    def fake_run_tts_only(*args, **kwargs) -> AudioWithTimestamps:
        return AudioWithTimestamps(
            audio_id="batch_tts_full",
            audio_path=str(tmp_path / "tts.wav"),
            duration_sec=0.1,
            duration_frames=3,
            sample_rate=16000,
        )

    class FakeOutput(str):
        video_url: str

        def __new__(cls, video_url: str):
            obj = str.__new__(cls, str(tmp_path / video_url.rsplit("/", 1)[-1]))
            obj.video_url = video_url
            return obj

    def fake_run_generation_from_audio(**kwargs) -> FakeOutput:
        generation_videos.append(kwargs["video"])
        return FakeOutput("/outputs/uploaded.mp4")

    monkeypatch.setattr("app.tasks.pipeline.run_tts_only", fake_run_tts_only)
    monkeypatch.setattr(
        "app.tasks.pipeline.run_generation_from_audio",
        fake_run_generation_from_audio,
    )

    client = TestClient(app)
    with avatar_image.open("rb") as handle:
        response = client.post(
            "/api/v1/generate-text-batch",
            data={"sentences": '["第一句"]'},
            files={"avatar_file": ("upload.png", handle, "image/png")},
        )

    assert response.status_code == 202
    assert response.json()["video_urls"] == ["/outputs/uploaded.mp4"]
    assert len(generation_videos) == 1
    assert generation_videos[0].video_id == "default_avatar_image"
    assert generation_videos[0].resolution == (32, 48)
    assert (Path(generation_videos[0].frames_dir) / "00000000.png").is_file()


def test_chat_page_is_mounted_and_uses_initial_loading_only():
    client = TestClient(app)
    response = client.get("/chat")

    assert response.status_code == 200
    assert 'id="idle" class="idle"' in response.text
    assert 'id="subtitle" class="subtitle"' in response.text
    assert 'player.addEventListener("timeupdate",updateSubtitle)' in response.text
    assert "subtitleSegments=Array.isArray(data.subtitle_segments)" in response.text
    assert "const videoUrl=data.video_urls[0]" in response.text
    assert "subtitle.textContent=data.reply" not in response.text
