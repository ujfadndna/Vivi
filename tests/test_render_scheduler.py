from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import httpx

from app.agent import render_scheduler as rs


def test_split_sentences_by_chinese_punctuation():
    text = (
        "\u4f60\u597d\u3002"
        "\u6211\u8fd8\u5728\u8fd9\u91cc\uff01"
        "\u53ef\u4ee5\u5417\uff1f"
        "\u6ca1\u6709\u6807\u70b9"
    )

    assert rs.split_sentences(text) == [
        "\u4f60\u597d\u3002",
        "\u6211\u8fd8\u5728\u8fd9\u91cc\uff01",
        "\u53ef\u4ee5\u5417\uff1f",
        "\u6ca1\u6709\u6807\u70b9",
    ]


def test_submit_render_posts_form_data_and_returns_task_id():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == (
            f"{rs._RENDER_BASE_URL}/api/v1/generate-text-only"
        )
        assert request.headers["content-type"].startswith(
            "application/x-www-form-urlencoded"
        )
        body = request.content.decode()
        assert "language=zh" in body
        assert "emotion=calm" in body
        assert "tts_emotion=calm" in body
        return httpx.Response(202, json={"task_id": "task-123"})

    async def run_test() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            task_id = await rs.submit_render(
                "\u4f60\u597d\u3002",
                "calm",
                client=client,
            )
        assert task_id == "task-123"

    asyncio.run(run_test())


def test_poll_render_returns_video_url_after_processing(monkeypatch):
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(
            200,
            json={"status": "completed", "video_url": "/videos/task-123.mp4"},
        )

    async def run_test() -> None:
        async def no_sleep(delay: float) -> None:
            return None

        monkeypatch.setattr(rs.asyncio, "sleep", no_sleep)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            video_url = await rs.poll_render("task-123", client=client)
        assert video_url == "/videos/task-123.mp4"
        assert requests == [
            f"{rs._RENDER_BASE_URL}/api/v1/generate/task-123",
            f"{rs._RENDER_BASE_URL}/api/v1/generate/task-123",
        ]

    asyncio.run(run_test())


def test_render_response_renders_serially_and_keeps_fallback(monkeypatch):
    post_count = 0
    request_order: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count

        request_order.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            post_count += 1
            return httpx.Response(202, json={"task_id": f"task-{post_count}"})

        task_id = request.url.path.rsplit("/", 1)[-1]
        if task_id == "task-2":
            return httpx.Response(200, json={"status": "failed"})
        return httpx.Response(
            200,
            json={"status": "completed", "video_url": f"/videos/{task_id}.mp4"},
        )

    async def run_test() -> None:
        original_client = rs.httpx.AsyncClient

        def make_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)

        monkeypatch.setattr(rs.httpx, "AsyncClient", make_client)
        result = await rs.render_response(
            "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\uff01",
            tts_emotion="calm",
        )

        assert result.fallback_text == (
            "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\uff01"
        )
        assert [segment.sentence for segment in result.segments] == [
            "\u7b2c\u4e00\u53e5\u3002",
            "\u7b2c\u4e8c\u53e5\uff01",
        ]
        assert [segment.status for segment in result.segments] == [
            "completed",
            "failed",
        ]
        assert result.segments[0].video_url == "/videos/task-1.mp4"
        assert result.segments[1].task_id == "task-2"
        assert result.segments[1].video_url is None
        assert request_order == [
            "POST /api/v1/generate-text-only",
            "GET /api/v1/generate/task-1",
            "POST /api/v1/generate-text-only",
            "GET /api/v1/generate/task-2",
        ]

    asyncio.run(run_test())


def test_render_response_stream_submits_all_before_polls_complete(monkeypatch):
    events: list[str] = []
    started_sentences: list[str] = []

    async def fake_submit_render(
        sentence: str,
        tts_emotion: str,
        language: str = "zh",
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        task_id = f"task-{len(started_sentences) + 1}"
        events.append(f"submit_start:{sentence}")
        started_sentences.append(sentence)
        if len(started_sentences) == 3:
            all_submits_started.set()
        await all_submits_started.wait()
        events.append(f"submit_done:{sentence}")
        return task_id

    async def fake_poll_render(
        task_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        assert all_submits_started.is_set()
        events.append(f"poll_start:{task_id}")
        await asyncio.sleep(0)
        events.append(f"poll_done:{task_id}")
        return f"/videos/{task_id}.mp4"

    async def run_test() -> None:
        nonlocal all_submits_started
        all_submits_started = asyncio.Event()
        monkeypatch.setattr(rs, "submit_render", fake_submit_render)
        monkeypatch.setattr(rs, "poll_render", fake_poll_render)

        segments = await asyncio.wait_for(
            _collect_render_stream(
                "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002\u7b2c\u4e09\u53e5\u3002"
            ),
            timeout=1.0,
        )

        assert [segment.status for segment in segments] == [
            "completed",
            "completed",
            "completed",
        ]
        assert started_sentences == [
            "\u7b2c\u4e00\u53e5\u3002",
            "\u7b2c\u4e8c\u53e5\u3002",
            "\u7b2c\u4e09\u53e5\u3002",
        ]

    all_submits_started: asyncio.Event
    asyncio.run(run_test())
    first_poll_done = min(
        index for index, event in enumerate(events) if event.startswith("poll_done:")
    )
    submit_starts = [
        index for index, event in enumerate(events) if event.startswith("submit_start:")
    ]
    assert max(submit_starts) < first_poll_done


def test_render_response_batch_maps_single_merged_url_to_all_segments(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/generate-text-batch"
        return httpx.Response(202, json={"status": "completed", "video_urls": ["/outputs/merged.mp4"]})

    async def run_test() -> None:
        original_client = rs.httpx.AsyncClient

        def make_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return original_client(*args, **kwargs)

        monkeypatch.setattr(rs.httpx, "AsyncClient", make_client)
        result = await rs.render_response_batch(
            "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002",
            tts_emotion="calm",
        )

        assert result.fallback_text == "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002"
        assert [segment.status for segment in result.segments] == ["completed", "completed"]
        assert [segment.video_url for segment in result.segments] == [
            "/outputs/merged.mp4",
            "/outputs/merged.mp4",
        ]

    asyncio.run(run_test())


def test_render_response_stream_yields_sentence_order_when_second_finishes_first(
    monkeypatch,
):
    second_poll_done = asyncio.Event()
    events: list[str] = []

    async def fake_submit_render(
        sentence: str,
        tts_emotion: str,
        language: str = "zh",
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        return {
            "\u7b2c\u4e00\u53e5\u3002": "task-1",
            "\u7b2c\u4e8c\u53e5\u3002": "task-2",
        }[sentence]

    async def fake_poll_render(
        task_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        events.append(f"poll_start:{task_id}")
        if task_id == "task-1":
            await second_poll_done.wait()
            events.append("poll_done:task-1")
            return "/videos/task-1.mp4"

        events.append("poll_done:task-2")
        second_poll_done.set()
        return "/videos/task-2.mp4"

    async def run_test() -> None:
        monkeypatch.setattr(rs, "submit_render", fake_submit_render)
        monkeypatch.setattr(rs, "poll_render", fake_poll_render)

        segments = await asyncio.wait_for(
            _collect_render_stream("\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002"),
            timeout=1.0,
        )

        assert [segment.sentence for segment in segments] == [
            "\u7b2c\u4e00\u53e5\u3002",
            "\u7b2c\u4e8c\u53e5\u3002",
        ]
        assert [segment.video_url for segment in segments] == [
            "/videos/task-1.mp4",
            "/videos/task-2.mp4",
        ]

    asyncio.run(run_test())
    assert events.index("poll_done:task-2") < events.index("poll_done:task-1")


def test_render_response_stream_failed_sentence_does_not_block_later_sentence(
    monkeypatch,
):
    third_poll_done = asyncio.Event()
    poll_calls: list[str] = []

    async def fake_submit_render(
        sentence: str,
        tts_emotion: str,
        language: str = "zh",
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        return {
            "\u7b2c\u4e00\u53e5\u3002": "task-1",
            "\u7b2c\u4e8c\u53e5\u3002": None,
            "\u7b2c\u4e09\u53e5\u3002": "task-3",
        }[sentence]

    async def fake_poll_render(
        task_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        poll_calls.append(task_id)
        if task_id == "task-1":
            await third_poll_done.wait()
            return "/videos/task-1.mp4"

        third_poll_done.set()
        return "/videos/task-3.mp4"

    async def run_test() -> None:
        monkeypatch.setattr(rs, "submit_render", fake_submit_render)
        monkeypatch.setattr(rs, "poll_render", fake_poll_render)

        segments = await asyncio.wait_for(
            _collect_render_stream(
                "\u7b2c\u4e00\u53e5\u3002\u7b2c\u4e8c\u53e5\u3002\u7b2c\u4e09\u53e5\u3002"
            ),
            timeout=1.0,
        )

        assert [segment.status for segment in segments] == [
            "completed",
            "failed",
            "completed",
        ]
        assert [segment.task_id for segment in segments] == [
            "task-1",
            None,
            "task-3",
        ]
        assert [segment.video_url for segment in segments] == [
            "/videos/task-1.mp4",
            None,
            "/videos/task-3.mp4",
        ]

    asyncio.run(run_test())
    assert poll_calls == ["task-1", "task-3"]


async def _collect_render_stream(response_text: str) -> list[rs.RenderSegment]:
    return [segment async for segment in rs.render_response_stream(response_text)]


def test_render_scheduler_does_not_import_render_layer_modules():
    source = Path("app/agent/render_scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert "app.services" not in imported_modules
    assert "app.tasks" not in imported_modules
    assert not any(module.startswith("app.services.") for module in imported_modules)
    assert not any(module.startswith("app.tasks.") for module in imported_modules)
