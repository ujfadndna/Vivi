from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import profile_store
from app.api.routes import chat_page
from app.main import app
from app.warmup import WARMUP_STATUS


@pytest.fixture(autouse=True)
def restore_warmup_status():
    import copy

    original = copy.deepcopy(WARMUP_STATUS)
    yield
    WARMUP_STATUS.clear()
    WARMUP_STATUS.update(original)


def _set_ready_warmup() -> None:
    WARMUP_STATUS["tts"].update({"status": "ok", "backend": "mock", "error": None})
    WARMUP_STATUS["flashhead"].update(
        {
            "status": "ok",
            "worker_ready": True,
            "avatar_image_path": "avatar.png",
            "error": None,
            "inference_warmup": {
                "status": "ok",
                "elapsed_sec": 1.25,
                "error": None,
            },
        }
    )


def _set_not_ready_warmup() -> None:
    WARMUP_STATUS["tts"].update({"status": "ok", "backend": "mock", "error": None})
    WARMUP_STATUS["flashhead"].update(
        {
            "status": "ok",
            "worker_ready": True,
            "avatar_image_path": "avatar.png",
            "error": None,
            "inference_warmup": {
                "status": "started",
                "elapsed_sec": 0.0,
                "error": None,
            },
        }
    )


def test_chat_page_uses_idle_video_and_current_page_history():
    client = TestClient(app)
    response = client.get("/chat")

    assert response.status_code == 200
    assert 'id="idleVideo"' in response.text
    assert 'id="settingsToggle"' in response.text
    assert 'id="settingsDrawer"' in response.text
    assert 'id="avatarUpload"' in response.text
    assert 'id="voiceUpload"' in response.text
    assert 'id="llmSave"' in response.text
    assert 'id="backendSave"' in response.text
    assert '<option value="mock">mock</option>' in response.text
    assert 'fetch("/api/v1/profile",{cache:"no-store"})' in response.text
    assert 'fetch("/api/v1/profile/avatar",{method:"POST",body:formData})' in response.text
    assert 'fetch("/api/v1/profile/voice",{method:"POST",body:formData})' in response.text
    assert 'fetch("/api/v1/profile/llm"' in response.text
    assert 'fetch("/api/v1/profile/backends"' in response.text
    assert 'const idleVideoUrl="/chat/idle-video"' in response.text
    assert "let conversationHistory=[]" in response.text
    assert 'formData.append("history",JSON.stringify(conversationHistory.slice(-16)))' in response.text
    assert "conversationHistory.push({role:\"user\",content:text})" in response.text
    assert "conversationHistory.push({role:\"assistant\",content:data.reply})" in response.text


def test_chat_page_has_startup_overlay_health_polling_and_disabled_input():
    client = TestClient(app)
    response = client.get("/chat")

    assert response.status_code == 200
    assert 'id="startupOverlay"' in response.text
    assert 'class="spinner"' in response.text
    assert "正在启动数字人..." in response.text
    assert "正在预热语音服务..." in response.text
    assert "正在启动数字人渲染进程..." in response.text
    assert "正在准备数字人头像..." in response.text
    assert "正在预热数字人推理，首次启动约需 1 分钟..." in response.text
    assert "可以开始聊天" in response.text
    assert 'fetch("/health",{cache:"no-store"})' in response.text
    assert 'tts.status==="ok"' in response.text
    assert 'flashhead.worker_ready===true' in response.text
    assert 'flashhead.status==="ok"' in response.text
    assert 'inference.status==="ok"' in response.text
    assert "数字人推理初始化失败，请刷新重试" in response.text
    assert 'showWarmupOverlay(elapsed>180000?"初始化仍在进行，请稍候或刷新":"正在连接后端服务...")' in response.text
    assert "setComposerEnabled(false)" in response.text
    assert "if(!digitalHumanReady)" in response.text
    assert "response.status===503" in response.text
    assert 'id="playButton"' in response.text
    assert 'playButton.addEventListener("click"' in response.text
    assert 'idle.addEventListener("click"' not in response.text
    assert 'mainVideo.addEventListener("click"' not in response.text
    assert 'player.addEventListener("click"' not in response.text


def test_clean_history_accepts_only_recent_user_and_assistant_messages():
    raw = json.dumps(
        [
            {"role": "system", "content": "ignore"},
            {"role": "user", "content": "我叫小明"},
            {"role": "assistant", "content": "我记住了"},
            {"role": "tool", "content": "ignore"},
            {"role": "user", "content": "x" * 800},
        ],
        ensure_ascii=False,
    )

    cleaned = chat_page._parse_history(raw)

    assert cleaned == [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "我记住了"},
        {"role": "user", "content": "x" * 500},
    ]


@pytest.mark.asyncio
async def test_chat_simple_injects_history_into_llm(monkeypatch):
    _set_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "local")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")
    captured_llm_payloads: list[dict] = []
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": "sk-profile",
    })

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        @property
        def is_success(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, **kwargs):
            if "chat/completions" in url:
                captured_llm_payloads.append(kwargs["json"])
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "你叫小明，我记得。"
                                }
                            }
                        ]
                    }
                )
            if url.endswith("/api/v1/generate-text-batch"):
                return FakeResponse(
                    {
                        "video_urls": ["/outputs/test.mp4"],
                        "subtitle_segments": [
                            {
                                "text": "你叫小明，我记得。",
                                "start_sec": 0,
                                "end_sec": 2,
                            }
                        ],
                        "duration_sec": 2,
                    }
                )
            raise AssertionError(url)

    monkeypatch.setattr(chat_page.httpx, "AsyncClient", FakeAsyncClient)

    response = await chat_page.chat_simple(
        text="我叫什么名字？",
        history=json.dumps(
            [
                {"role": "user", "content": "我叫小明"},
                {"role": "assistant", "content": "我记住了"},
            ],
            ensure_ascii=False,
        ),
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["reply"] == "你叫小明，我记得。"
    messages = captured_llm_payloads[0]["messages"]
    assert captured_llm_payloads[0]["model"] == "profile-model"
    assert messages[0]["role"] == "system"
    assert messages[1:] == [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "我记住了"},
        {"role": "user", "content": "我叫什么名字？"},
    ]


@pytest.mark.asyncio
async def test_chat_simple_returns_503_before_inference_warmup(monkeypatch):
    _set_not_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "local")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")

    with pytest.raises(chat_page.HTTPException) as exc_info:
        await chat_page.chat_simple(text="你好", history=None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Digital human is warming up"


@pytest.mark.asyncio
async def test_chat_simple_allows_request_after_inference_warmup(monkeypatch):
    _set_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "local")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": "sk-profile",
    })
    captured_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        @property
        def is_success(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, **kwargs):
            captured_urls.append(url)
            if "chat/completions" in url:
                return FakeResponse({"choices": [{"message": {"content": "你好。"}}]})
            if url.endswith("/api/v1/generate-text-batch"):
                return FakeResponse({"video_urls": ["/outputs/ready.mp4"]})
            raise AssertionError(url)

    monkeypatch.setattr(chat_page.httpx, "AsyncClient", FakeAsyncClient)

    response = await chat_page.chat_simple(text="你好", history=None)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["reply"] == "你好。"
    assert payload["video_urls"] == ["/outputs/ready.mp4"]
    assert captured_urls[0] == "https://api.profile.test/v1/chat/completions"


@pytest.mark.asyncio
async def test_chat_simple_returns_clear_error_without_llm_key(monkeypatch):
    _set_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "local")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": None,
    })

    with pytest.raises(chat_page.HTTPException) as exc_info:
        await chat_page.chat_simple(text="你好", history=None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "LLM API key is not configured"


@pytest.mark.asyncio
async def test_chat_simple_mock_mode_does_not_require_llm_key_or_warmup(monkeypatch):
    _set_not_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "mock")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": None,
    })
    captured_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        @property
        def is_success(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, **kwargs):
            captured_urls.append(url)
            assert "chat/completions" not in url
            return FakeResponse(
                {
                    "video_urls": ["/outputs/mock.mp4"],
                    "subtitle_segments": [
                        {"text": "mock", "start_sec": 0, "end_sec": 1}
                    ],
                    "duration_sec": 1,
                }
            )

    monkeypatch.setattr(chat_page.httpx, "AsyncClient", FakeAsyncClient)

    response = await chat_page.chat_simple(text="你好", history=None)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["reply"] == "你刚才说：你好。我在这里听你说。"
    assert payload["video_urls"] == ["/outputs/mock.mp4"]
    assert captured_urls == ["http://127.0.0.1:8100/api/v1/generate-text-batch"]


@pytest.mark.asyncio
async def test_chat_simple_remote_render_uses_profile_url_and_expands_relative_video(tmp_path, monkeypatch):
    _set_not_ready_warmup()
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"not-a-real-image-but-opened")
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "remote")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "https://render.example.com")
    monkeypatch.setattr(profile_store, "resolve_tts_api_url", lambda: "https://tts.example.com")
    monkeypatch.setattr(profile_store, "resolve_avatar_image", lambda: avatar)
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": "sk-profile",
    })
    captured_urls: list[str] = []
    captured_render_payloads: list[dict] = []
    captured_render_files: list[dict] = []

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        @property
        def is_success(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, **kwargs):
            captured_urls.append(url)
            if "chat/completions" in url:
                return FakeResponse({"choices": [{"message": {"content": "你好，我在。"}}]})
            if url == "https://render.example.com/api/v1/generate-text-batch":
                captured_render_payloads.append(kwargs["data"])
                captured_render_files.append(kwargs["files"])
                return FakeResponse(
                    {
                        "video_urls": ["/outputs/demo.mp4"],
                        "subtitle_segments": [],
                        "duration_sec": 2,
                    }
                )
            raise AssertionError(url)

    monkeypatch.setattr(chat_page.httpx, "AsyncClient", FakeAsyncClient)

    response = await chat_page.chat_simple(text="你好", history=None)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["reply"] == "你好，我在。"
    assert payload["video_urls"] == ["https://render.example.com/outputs/demo.mp4"]
    assert captured_urls == [
        "https://api.profile.test/v1/chat/completions",
        "https://render.example.com/api/v1/generate-text-batch",
    ]
    assert captured_render_payloads == [
        {
            "sentences": "你好，我在。",
            "language": "zh",
            "emotion": "calm",
            "speed": "1.0",
            "tts_api_url": "https://tts.example.com",
        }
    ]
    assert captured_render_files[0]["avatar_file"][0] == "avatar.png"
    captured_render_files[0]["avatar_file"][1].close()


@pytest.mark.asyncio
async def test_chat_simple_remote_render_keeps_absolute_video_url(monkeypatch):
    _set_not_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "remote")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "https://render.example.com")
    monkeypatch.setattr(profile_store, "resolve_llm_config", lambda: {
        "base_url": "https://api.profile.test/v1",
        "model": "profile-model",
        "api_key": "sk-profile",
    })

    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        @property
        def is_success(self) -> bool:
            return 200 <= self.status_code < 300

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, **kwargs):
            if "chat/completions" in url:
                return FakeResponse({"choices": [{"message": {"content": "你好，我在。"}}]})
            return FakeResponse({"video_urls": ["https://cdn.example.com/demo.mp4"]})

    monkeypatch.setattr(chat_page.httpx, "AsyncClient", FakeAsyncClient)

    response = await chat_page.chat_simple(text="你好", history=None)
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["video_urls"] == ["https://cdn.example.com/demo.mp4"]


@pytest.mark.asyncio
async def test_chat_simple_remote_without_render_url_falls_back_to_local_warmup_gate(monkeypatch):
    _set_not_ready_warmup()
    monkeypatch.setattr(profile_store, "resolve_deployment_mode", lambda: "remote")
    monkeypatch.setattr(profile_store, "resolve_render_api_url", lambda: "")

    with pytest.raises(chat_page.HTTPException) as exc_info:
        await chat_page.chat_simple(text="你好", history=None)

    assert exc_info.value.status_code == 503
