"""HTTP-only render scheduler for agent responses."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from app.agent.agent_config import agent_settings


_DEFAULT_RENDER_BASE_URL = "http://localhost:8000"
_RENDER_BASE_URL = str(
    getattr(agent_settings, "render_base_url", _DEFAULT_RENDER_BASE_URL)
    or _DEFAULT_RENDER_BASE_URL
).rstrip("/")
_POLL_INTERVAL_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 300.0
_SENTENCE_PATTERN = re.compile("[^\u3002\uff01\uff1f]+(?:[\u3002\uff01\uff1f]+|$)")


@dataclass
class RenderSegment:
    sentence: str
    task_id: str | None
    video_url: str | None
    status: str


@dataclass
class RenderResult:
    segments: list[RenderSegment]
    fallback_text: str


def split_sentences(text: str) -> list[str]:
    """Split text by Chinese sentence punctuation, keeping punctuation."""
    return [
        match.group(0).strip()
        for match in _SENTENCE_PATTERN.finditer(text.strip())
        if match.group(0).strip()
    ]


async def submit_render(
    sentence: str,
    tts_emotion: str,
    language: str = "zh",
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Submit one sentence to the render layer and return its task id."""
    if client is None:
        async with httpx.AsyncClient() as owned_client:
            return await _submit_render_with_client(
                sentence=sentence,
                tts_emotion=tts_emotion,
                language=language,
                client=owned_client,
            )

    return await _submit_render_with_client(
        sentence=sentence,
        tts_emotion=tts_emotion,
        language=language,
        client=client,
    )


async def poll_render(
    task_id: str,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Poll the render layer until a video URL is ready or the request fails."""
    if client is None:
        async with httpx.AsyncClient() as owned_client:
            return await _poll_render_with_client(task_id=task_id, client=owned_client)

    return await _poll_render_with_client(task_id=task_id, client=client)


async def render_response(
    response_text: str,
    tts_emotion: str = "neutral",
) -> RenderResult:
    """Render a text response sentence by sentence over the HTTP API."""
    segments: list[RenderSegment] = []

    async with httpx.AsyncClient() as client:
        for sentence in split_sentences(response_text):
            task_id = await submit_render(
                sentence=sentence,
                tts_emotion=tts_emotion,
                client=client,
            )
            if task_id is None:
                segments.append(
                    RenderSegment(
                        sentence=sentence,
                        task_id=None,
                        video_url=None,
                        status="failed",
                    )
                )
                continue

            video_url = await poll_render(task_id=task_id, client=client)
            segments.append(
                RenderSegment(
                    sentence=sentence,
                    task_id=task_id,
                    video_url=video_url,
                    status="completed" if video_url is not None else "failed",
                )
            )

    return RenderResult(segments=segments, fallback_text=response_text)


async def render_response_stream(
    response_text: str,
    tts_emotion: str = "neutral",
) -> AsyncIterator[RenderSegment]:
    """Render a text response concurrently and yield segments in sentence order."""
    sentences = split_sentences(response_text)

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(
                _render_sentence_segment(
                    sentence=sentence,
                    tts_emotion=tts_emotion,
                    client=client,
                )
            )
            for sentence in sentences
        ]

        try:
            for task in tasks:
                yield await task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


async def _render_sentence_segment(
    sentence: str,
    tts_emotion: str,
    client: httpx.AsyncClient,
) -> RenderSegment:
    task_id = await submit_render(
        sentence=sentence,
        tts_emotion=tts_emotion,
        client=client,
    )
    if task_id is None:
        return RenderSegment(
            sentence=sentence,
            task_id=None,
            video_url=None,
            status="failed",
        )

    video_url = await poll_render(task_id=task_id, client=client)
    return RenderSegment(
        sentence=sentence,
        task_id=task_id,
        video_url=video_url,
        status="completed" if video_url is not None else "failed",
    )


async def render_response_batch(
    response_text: str,
    tts_emotion: str = "neutral",
) -> RenderResult:
    """MVP-3.1: TTS all sentences in parallel, then FlashHead sequentially.

    Uses /generate-text-batch endpoint to eliminate inter-sentence gaps.
    """
    sentences = split_sentences(response_text)
    if not sentences:
        return RenderResult(segments=[], fallback_text=response_text)

    import json

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{_RENDER_BASE_URL}/api/v1/generate-text-batch",
                data={
                    "sentences": json.dumps(sentences),
                    "emotion": tts_emotion,
                },
                timeout=_POLL_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return RenderResult(
                segments=[
                    RenderSegment(sentence=s, task_id=None, video_url=None, status="failed")
                    for s in sentences
                ],
                fallback_text=response_text,
            )

    video_urls = payload.get("video_urls") or []
    merged_url = video_urls[0] if len(video_urls) == 1 else None
    segments = []
    for i, sentence in enumerate(sentences):
        video_url = merged_url or (video_urls[i] if i < len(video_urls) else None)
        segments.append(
            RenderSegment(
                sentence=sentence,
                task_id=None,
                video_url=video_url,
                status="completed" if video_url else "failed",
            )
        )

    return RenderResult(segments=segments, fallback_text=response_text)


async def _submit_render_with_client(
    sentence: str,
    tts_emotion: str,
    language: str,
    client: httpx.AsyncClient,
) -> str | None:
    try:
        response = await client.post(
            f"{_RENDER_BASE_URL}/api/v1/generate-text-only",
            data={
                "text": sentence,
                "language": language,
                "emotion": tts_emotion,
                "tts_emotion": tts_emotion,
            },
            # eager（同步）渲染模式下，提交即阻塞至整段渲染完成，需放宽到与轮询同量级超时；
            # 真实异步（Redis+Celery）模式下提交会快速返回 task_id，该超时不会触发。
            timeout=_POLL_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    task_id = _as_str(payload.get("task_id"))
    return task_id or None


async def _poll_render_with_client(
    task_id: str,
    client: httpx.AsyncClient,
) -> str | None:
    deadline = asyncio.get_running_loop().time() + _POLL_TIMEOUT_SECONDS

    while True:
        try:
            response = await client.get(
                f"{_RENDER_BASE_URL}/api/v1/generate/{task_id}",
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        status = _as_str(payload.get("status"))
        if status == "completed":
            return _as_str(payload.get("video_url"))
        if status == "failed":
            return None

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None

        await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
