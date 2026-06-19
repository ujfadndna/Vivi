"""REST API routes for the therapist agent layer."""
from __future__ import annotations

import hashlib
import asyncio
import json
import logging
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import db as agent_db
from app.agent.agent_config import agent_settings

try:
    from app.agent.graph import (
        _build_system_prompt,
        _message_content_to_text,
        build_graph,
        get_llm,
    )
    from langchain_core.messages import HumanMessage
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional agent deps.
    build_graph = None  # type: ignore[assignment]
    _build_system_prompt = None  # type: ignore[assignment]
    _message_content_to_text = None  # type: ignore[assignment]
    get_llm = None  # type: ignore[assignment]
    HumanMessage = None  # type: ignore[assignment]
    _BUILD_GRAPH_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _BUILD_GRAPH_IMPORT_ERROR = None

from app.agent.prompts import IDENTITY_DISCLOSURE
from app.agent.render_scheduler import render_response_batch, render_response_stream
from app.agent.safety import check_safety, get_crisis_response

router = APIRouter(prefix="/agent", tags=["agent"])
_logger = logging.getLogger(__name__)
_STREAM_END = object()
MEMORY_EXTRACT_PROMPT = """从以下对话片段中提炼1-3条重要记忆（用户情绪、重要事件、偏好）。
每条记忆用一句话表达。只输出记忆列表，每行一条，不加序号。

用户: {user_text}
助手: {ai_text}

重要记忆:"""
_SENTENCE_PUNCTUATION_BOUNDARIES = {"\u3002", "\uff01", "\uff1f", "!", "?"}
# 逗号类标点也作为分句边界，把长句拆短，降低单句 MuseTalk 耗时（26s→6s）
_SENTENCE_SOFT_BOUNDARIES = {"\uff0c", "\u3001", ",", "\uff1b", ";"}
_SENTENCE_BOUNDARIES = (
    _SENTENCE_PUNCTUATION_BOUNDARIES | _SENTENCE_SOFT_BOUNDARIES | {"\n", "\r"}
)
_TTS_EMOTION_TAGS = {
    "W": "warm",
    "C": "calm",
    "S": "sad",
    "E": "warm",
}
_RENDER_POLL_INTERVAL_SECONDS = 0.5
_RENDER_TIMEOUT_SECONDS = 300.0
_TTS_SEM: asyncio.Semaphore | None = None

_init_lock = RLock()
_checkpointer_context: AbstractContextManager[Any] | None = None
_checkpointer: Any | None = None
_graph: Any | None = None
_memory_initialized = False


def _get_tts_sem() -> asyncio.Semaphore:
    global _TTS_SEM
    if _TTS_SEM is None:
        _TTS_SEM = asyncio.Semaphore(1)
    return _TTS_SEM


class ChatRequest(BaseModel):
    user_id: str
    session_id: str | None = None
    text: str
    render_video: bool = True


class InjectMemoryRequest(BaseModel):
    user_id: str
    content: str
    memory_type: str = "injected"


class RenderSegmentOut(BaseModel):
    sentence: str
    video_url: str | None
    status: str


class ChatResponse(BaseModel):
    session_id: str
    response_text: str
    tts_emotion: str
    risk_level: str
    pause_required: bool
    identity_disclosure: str | None
    render_segments: list[RenderSegmentOut]


class SessionInfo(BaseModel):
    session_id: str
    user_id: str
    started_at: str
    last_active_at: str
    duration_minutes: int
    turn_count: int
    summary: str | None


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    safety_result = check_safety(req.text)
    session_id = req.session_id or f"session_{uuid4().hex}"
    config = _thread_config(session_id)

    _ensure_agent_db()
    agent_db.upsert_session(session_id=session_id, user_id=req.user_id)
    session_row = _get_session_row(session_id)
    duration_minutes = _duration_minutes(session_row)

    checkpointer = await _get_checkpointer()
    is_first_turn = (await checkpointer.aget(config)) is None
    identity_disclosure = _identity_disclosure(is_first_turn)

    if safety_result.risk_level != "safe":
        response_text = get_crisis_response(safety_result.risk_level)
        agent_db.log_crisis_event(
            event_id=f"crisis_{uuid4().hex}",
            user_id=req.user_id,
            session_id=session_id,
            risk_level=safety_result.risk_level,
            matched_pattern=safety_result.matched_pattern,
            user_input_hash=_hash_text(req.text),
        )
        agent_db.update_session_turn(
            session_id=session_id,
            duration_minutes=duration_minutes,
        )
        return ChatResponse(
            session_id=session_id,
            response_text=response_text,
            tts_emotion="calm",
            risk_level=safety_result.risk_level,
            pause_required=False,
            identity_disclosure=identity_disclosure,
            render_segments=[],
        )

    # 直接用 openai AsyncClient（绕过 langchain 的 sync httpcore 问题）
    _ensure_memory()
    from app.agent import memory as mem_store_mod
    from openai import AsyncOpenAI

    memories = mem_store_mod.recall_memories(
        user_id=req.user_id,
        query=req.text,
        top_k=agent_settings.long_memory_top_k,
    )
    system_prompt = _build_system_prompt(memories)

    history = await _load_persisted_messages(config)
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend(_messages_to_openai(history[-40:]))
    chat_messages.append({"role": "user", "content": req.text})

    aclient = AsyncOpenAI(
        api_key=agent_settings.agent_llm_api_key,
        base_url=agent_settings.agent_llm_base_url or "https://api.deepseek.com/v1",
    )
    completion = await aclient.chat.completions.create(
        model=agent_settings.agent_llm_model,
        messages=chat_messages,
        temperature=agent_settings.agent_llm_temperature,
    )
    response_text = (completion.choices[0].message.content or "").strip()
    tts_emotion = "warm"
    risk_level = safety_result.risk_level
    pause_required = False
    render_segments: list[RenderSegmentOut] = []

    if req.render_video and not pause_required:
        render_result = await render_response_batch(
            response_text=response_text,
            tts_emotion=tts_emotion,
        )
        for segment in render_result.segments:
            render_segments.append(
                RenderSegmentOut(
                    sentence=segment.sentence,
                    video_url=segment.video_url,
                    status=segment.status,
                )
            )

    agent_db.update_session_turn(
        session_id=session_id,
        duration_minutes=duration_minutes,
    )

    return ChatResponse(
        session_id=session_id,
        response_text=response_text,
        tts_emotion=tts_emotion,
        risk_level=risk_level,
        pause_required=pause_required,
        identity_disclosure=identity_disclosure,
        render_segments=render_segments,
    )


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    async def event_stream():
        try:
            async for event in _chat_stream_events(req):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - stream responses need in-band errors.
            payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/memory")
async def inject_memory(req: InjectMemoryRequest) -> dict:
    _ensure_memory()
    from app.agent import memory as mem_store

    entry_id = mem_store.store_memory(
        user_id=req.user_id,
        session_id="injected",
        content=req.content,
        memory_type=req.memory_type,
    )
    return {"entry_id": entry_id}


@router.get("/session/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str) -> SessionInfo:
    _ensure_agent_db()
    row = _get_session_row(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return _session_info(row)


@router.get("/history/{user_id}", response_model=list[SessionInfo])
async def get_history(
    user_id: str,
    limit: int = 10,
) -> list[SessionInfo]:
    _ensure_agent_db()
    limit = min(max(limit, 1), 100)
    with agent_db._connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                user_id,
                started_at,
                last_active_at,
                duration_minutes,
                turn_count,
                summary
            FROM sessions
            WHERE user_id = ?
            ORDER BY last_active_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    return [_session_info(row) for row in rows]


async def _get_graph() -> Any:
    global _graph

    if _graph is None:
        if build_graph is None:
            raise RuntimeError(
                "agent graph dependencies are not installed",
            ) from _BUILD_GRAPH_IMPORT_ERROR
        _ensure_agent_db()
        _ensure_memory()
        _graph = build_graph(await _get_checkpointer())

    return _graph


async def _chat_stream_events(req: ChatRequest):
    if (
        build_graph is None
        or HumanMessage is None
    ):
        raise RuntimeError("agent graph dependencies are not installed") from _BUILD_GRAPH_IMPORT_ERROR

    safety_result = check_safety(req.text)
    session_id = req.session_id or f"session_{uuid4().hex}"
    config = _thread_config(session_id)

    _ensure_agent_db()
    agent_db.upsert_session(session_id=session_id, user_id=req.user_id)
    session_row = _get_session_row(session_id)
    duration_minutes = _duration_minutes(session_row)

    checkpointer = await _get_checkpointer()
    is_first_turn = (await checkpointer.aget(config)) is None
    identity_disclosure = _identity_disclosure(is_first_turn)

    yield {
        "type": "session",
        "session_id": session_id,
        "identity_disclosure": identity_disclosure,
    }

    graph = await _get_graph()
    input_state = {
        "messages": [HumanMessage(content=req.text)],
        "user_id": req.user_id,
        "session_id": session_id,
        "session_duration_minutes": duration_minutes,
    }

    event_queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue()

    async def produce_events() -> None:
        render_tasks: list[asyncio.Task[None]] = []
        avatar_task = (
            asyncio.create_task(_load_default_avatar_video())
            if req.render_video
            else None
        )

        try:
            response_text = ""
            risk_level = "safe"
            detected_emotion = "warm"
            pause_required = False

            async for update in graph.astream(
                input_state,
                config=config,
                stream_mode="updates",
            ):
                for node_name, state_update in _iter_graph_updates(update):
                    _logger.info("LangGraph node executed: %s", node_name)
                    if not isinstance(state_update, dict):
                        continue
                    if "risk_level" in state_update:
                        risk_level = str(state_update["risk_level"])
                    if node_name in {"think", "crisis_response"}:
                        candidate = state_update.get("response_text")
                        if candidate is not None:
                            response_text = str(candidate).strip()
                    if "tts_emotion" in state_update:
                        detected_emotion = str(state_update["tts_emotion"] or "warm")
                    if "pause_required" in state_update:
                        pause_required = bool(state_update["pause_required"])

            if risk_level != "safe":
                agent_db.log_crisis_event(
                    event_id=f"crisis_{uuid4().hex}",
                    user_id=req.user_id,
                    session_id=session_id,
                    risk_level=risk_level,
                    matched_pattern=safety_result.matched_pattern,
                    user_input_hash=_hash_text(req.text),
                )

            response_text = _strip_emotion_tags(response_text).strip()
            display_text, _ = _pop_display_text(response_text, final=True)
            if display_text:
                await event_queue.put({"type": "token", "text": display_text})

            sentence_index = 0
            sentences_with_emotion, sentence_buffer = _pop_complete_sentences(
                response_text
            )
            if sentence_buffer.strip():
                sentence, emotion = _parse_sentence_emotion(sentence_buffer.strip())
                if sentence:
                    sentences_with_emotion.append((sentence, emotion))

            for sentence, sentence_emotion in sentences_with_emotion:
                await event_queue.put(_sentence_event(sentence_index, sentence))
                tts_emotion = (
                    sentence_emotion
                    if sentence_emotion != "warm"
                    else detected_emotion
                )
                if req.render_video and avatar_task is not None:
                    render_tasks.append(
                        asyncio.create_task(
                            _render_sentence_pipeline(
                                index=sentence_index,
                                sentence=sentence,
                                tts_emotion=tts_emotion,
                                avatar_task=avatar_task,
                                event_queue=event_queue,
                            )
                        )
                    )
                sentence_index += 1

            if render_tasks:
                await asyncio.gather(*render_tasks)

            agent_db.update_session_turn(
                session_id=session_id,
                duration_minutes=duration_minutes,
            )

            if response_text and risk_level == "safe":
                asyncio.create_task(
                    _extract_and_store_conversation_memories(
                        user_id=req.user_id,
                        session_id=session_id,
                        user_text=req.text,
                        ai_text=response_text,
                    )
                )

            await event_queue.put(
                {
                    "type": "done",
                    "session_id": session_id,
                    "response_text": response_text,
                    "risk_level": risk_level,
                    "pause_required": pause_required,
                    "tts_emotion": detected_emotion,
                }
            )
        except Exception as exc:  # noqa: BLE001 - stream responses need in-band errors.
            for task in render_tasks:
                if not task.done():
                    task.cancel()
            if render_tasks:
                await asyncio.gather(*render_tasks, return_exceptions=True)
            if avatar_task is not None and not avatar_task.done():
                avatar_task.cancel()
            if avatar_task is not None:
                await asyncio.gather(avatar_task, return_exceptions=True)
            await event_queue.put({"type": "error", "message": str(exc)})
        finally:
            for task in render_tasks:
                if not task.done():
                    task.cancel()
            if render_tasks:
                await asyncio.gather(*render_tasks, return_exceptions=True)
            if avatar_task is not None and not avatar_task.done():
                avatar_task.cancel()
            if avatar_task is not None:
                await asyncio.gather(avatar_task, return_exceptions=True)
            await event_queue.put(_STREAM_END)

    producer_task = asyncio.create_task(produce_events())
    try:
        while True:
            event = await event_queue.get()
            if event is _STREAM_END:
                break
            yield event
    finally:
        if not producer_task.done():
            producer_task.cancel()
            await asyncio.gather(producer_task, return_exceptions=True)


def _iter_graph_updates(update: Any):
    if isinstance(update, tuple) and len(update) == 2:
        yield update[0], update[1]
        return

    if isinstance(update, dict):
        for node_name, state_update in update.items():
            yield node_name, state_update
        return

    yield "unknown", update


async def _load_persisted_messages(config: dict[str, dict[str, str]]) -> list[Any]:
    checkpointer = await _get_checkpointer()
    checkpoint = await checkpointer.aget(config)
    if not checkpoint:
        return []

    channel_values = checkpoint.get("channel_values", {})
    messages = channel_values.get("messages", [])
    return list(messages)


def _messages_to_openai(messages: list[Any]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for message in messages:
        role = _openai_role(message)
        if role is None:
            continue
        content = _message_to_text(message)
        if content:
            converted.append({"role": role, "content": content})
    return converted


def _openai_role(message: Any) -> str | None:
    message_type = getattr(message, "type", None)
    if isinstance(message, dict):
        role = message.get("role")
        if role in {"user", "assistant", "system"}:
            return str(role)
        message_type = message.get("type")

    if message_type == "human":
        return "user"
    if message_type == "ai":
        return "assistant"
    if message_type == "system":
        return "system"
    return None


def _message_to_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if _message_content_to_text is not None:
        return _message_content_to_text(content)
    return str(content or "")


async def _render_sentence_pipeline(
    index: int,
    sentence: str,
    tts_emotion: str,
    avatar_task: asyncio.Task[Any],
    event_queue: asyncio.Queue[dict[str, Any] | object],
) -> None:
    task_id = _create_render_task_id()
    try:
        video = await avatar_task
        async with _get_tts_sem():
            audio = await asyncio.to_thread(
                _synthesize_sentence_audio,
                sentence,
                tts_emotion,
                video.fps,
            )
        await event_queue.put(
            {
                "type": "render_start",
                "index": index,
                "text": sentence,
                "sentence": sentence,
                "task_id": task_id,
            }
        )
        _submit_render_task_from_audio(task_id=task_id, video=video, audio=audio)
        result = await _wait_for_render_done(
            index=index,
            sentence=sentence,
            task_id=task_id,
        )
        await event_queue.put(result)
    except Exception as exc:  # noqa: BLE001 - per-sentence failures are reported in-band.
        await event_queue.put(
            {
                "type": "render_done",
                "index": index,
                "text": sentence,
                "sentence": sentence,
                "status": "failed",
                "task_id": task_id,
                "video_url": _render_video_url(task_id),
                "error": str(exc),
            }
        )


async def _extract_and_store_conversation_memories(
    user_id: str,
    session_id: str,
    user_text: str,
    ai_text: str,
) -> None:
    try:
        if get_llm is None or _message_content_to_text is None or HumanMessage is None:
            return

        prompt = MEMORY_EXTRACT_PROMPT.format(user_text=user_text, ai_text=ai_text)
        response = await get_llm().ainvoke([HumanMessage(content=prompt)])
        extracted_text = _message_content_to_text(getattr(response, "content", ""))
        facts = _parse_extracted_memories(extracted_text)
        if not facts:
            return

        _ensure_memory()
        from app.agent import memory as mem_store

        for fact in facts:
            mem_store.store_memory(
                user_id=user_id,
                session_id=session_id,
                content=fact,
                memory_type="conversation",
            )
    except Exception as exc:  # noqa: BLE001 - background memory extraction is best-effort.
        _logger.warning("conversation memory extraction failed: %s", exc)


def _parse_extracted_memories(text: str) -> list[str]:
    memories: list[str] = []
    for line in text.splitlines():
        fact = line.strip()
        if not fact:
            continue
        fact = fact.lstrip("-*• \t")
        digit_count = 0
        while digit_count < len(fact) and fact[digit_count].isdigit():
            digit_count += 1
        if digit_count < len(fact) and fact[digit_count] in ".、)）":
            fact = fact[digit_count + 1 :].lstrip()
        if fact:
            memories.append(fact)
        if len(memories) >= 3:
            break
    return memories


async def _render_sentence_with_preview(
    index: int,
    sentence: str,
    task_id: str,
    video: Any,
    audio: Any,
    event_queue: asyncio.Queue[dict[str, Any] | object],
) -> bool:
    from app.schemas import AudioWithTimestamps
    from app.services.audio_utils import trim_audio
    from app.storage import preview_dir

    preview_task_id = _create_render_task_id()
    preview_audio_path = preview_dir() / f"preview_{preview_task_id}.wav"
    try:
        try:
            await asyncio.to_thread(trim_audio, audio.audio_path, 1.0, str(preview_audio_path))
        except Exception as exc:  # noqa: BLE001 - preview is best-effort.
            from app.tasks import store

            store.fail(preview_task_id, str(exc))
            return False
        preview_audio = AudioWithTimestamps(
            audio_id=f"preview_{preview_task_id}",
            audio_path=str(preview_audio_path),
            duration_sec=1.0,
            duration_frames=round(video.fps),
            sample_rate=audio.sample_rate,
            phoneme_intervals=[],
        )
        preview_sentence = f"{sentence}(预览)"
        await event_queue.put(
            {
                "type": "render_start",
                "index": index,
                "text": preview_sentence,
                "sentence": preview_sentence,
                "task_id": preview_task_id,
            }
        )
        _submit_render_task_from_audio(task_id=preview_task_id, video=video, audio=preview_audio)
        await event_queue.put(
            {
                "type": "render_start",
                "index": index,
                "text": sentence,
                "sentence": sentence,
                "task_id": task_id,
            }
        )
        _submit_render_task_from_audio(task_id=task_id, video=video, audio=audio)
        await event_queue.put(
            await _wait_for_render_done(
                index=index,
                sentence=preview_sentence,
                task_id=preview_task_id,
            )
        )
        await event_queue.put(
            await _wait_for_render_done(index=index, sentence=sentence, task_id=task_id)
        )
        return True
    finally:
        try:
            preview_audio_path.unlink(missing_ok=True)
        except OSError:
            pass


async def _load_default_avatar_video() -> Any:
    from app.config import settings
    from app.services.ingest import run_ingest

    avatar_path = settings.default_avatar_video
    if not avatar_path.exists():
        raise FileNotFoundError(
            f"Default avatar video not found: {avatar_path}. "
            "Please set DEFAULT_AVATAR_VIDEO in .env and place the file."
        )

    return await asyncio.to_thread(run_ingest, str(avatar_path))


def _synthesize_sentence_audio(sentence: str, tts_emotion: str, fps: float) -> Any:
    from app.config import settings
    from app.schemas import SynthesizeRequest
    from app.services.tts import run_tts

    speaker_id = (
        str(settings.default_speaker_wav)
        if settings.default_speaker_wav.exists()
        else None
    )
    req = SynthesizeRequest(
        text=sentence,
        language="zh",
        emotion=tts_emotion,
        speaker_id=speaker_id,
    )
    return run_tts(req, fps=fps)


def _submit_render_from_audio(video: Any, audio: Any) -> str:
    task_id = _create_render_task_id()
    _submit_render_task_from_audio(task_id=task_id, video=video, audio=audio)
    return task_id


def _create_render_task_id() -> str:
    from app.storage import new_id
    from app.tasks import store

    task_id = new_id("gen")
    store.create(task_id)
    return task_id


def _submit_render_task_from_audio(task_id: str, video: Any, audio: Any) -> None:
    from app.tasks.runner import submit_generation_from_audio

    submit_generation_from_audio(task_id=task_id, video=video, audio=audio)


def _render_video_url(task_id: str) -> str:
    return f"/outputs/{task_id}.mp4"


async def _wait_for_render_started(task_id: str) -> None:
    from app.schemas import TaskState
    from app.tasks import store

    deadline = asyncio.get_running_loop().time() + _RENDER_TIMEOUT_SECONDS

    while True:
        status = store.get(task_id)
        if status is None or status.status != TaskState.queued:
            return

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return

        await asyncio.sleep(min(_RENDER_POLL_INTERVAL_SECONDS, remaining))


async def _wait_for_render_done(
    index: int,
    sentence: str,
    task_id: str,
) -> dict[str, Any]:
    from app.schemas import TaskState
    from app.tasks import store

    deadline = asyncio.get_running_loop().time() + _RENDER_TIMEOUT_SECONDS
    video_url = _render_video_url(task_id)

    while True:
        status = store.get(task_id)
        if status is None:
            return _render_done_event(
                index=index,
                sentence=sentence,
                task_id=task_id,
                status="failed",
                video_url=video_url,
            )

        if status.status == TaskState.completed:
            if status.video_url != video_url:
                store.finish(task_id, video_url)
            return _render_done_event(
                index=index,
                sentence=sentence,
                task_id=task_id,
                status="completed",
                video_url=video_url,
            )

        if status.status == TaskState.failed:
            return _render_done_event(
                index=index,
                sentence=sentence,
                task_id=task_id,
                status="failed",
                video_url=video_url,
                error=status.error,
            )

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return _render_done_event(
                index=index,
                sentence=sentence,
                task_id=task_id,
                status="failed",
                video_url=video_url,
                error="render timeout",
            )

        await asyncio.sleep(min(_RENDER_POLL_INTERVAL_SECONDS, remaining))


def _render_done_event(
    index: int,
    sentence: str,
    task_id: str,
    status: str,
    video_url: str | None,
    error: str | None = None,
) -> dict[str, Any]:
    event = {
        "type": "render_done",
        "index": index,
        "text": sentence,
        "sentence": sentence,
        "status": status,
        "task_id": task_id,
        "video_url": video_url,
    }
    if error:
        event["error"] = error
    return event


def _sentence_event(index: int, sentence: str) -> dict[str, Any]:
    return {
        "type": "sentence",
        "index": index,
        "text": sentence,
        "sentence": sentence,
    }


def _parse_sentence_emotion(sentence: str) -> tuple[str, str]:
    sentence = sentence.strip()
    if len(sentence) >= 3 and sentence[0] == "[" and sentence[2] == "]":
        emotion = _TTS_EMOTION_TAGS.get(sentence[1])
        if emotion is not None:
            return sentence[3:].strip(), emotion
    return sentence, "warm"


def _strip_emotion_tags(text: str) -> str:
    stripped, _ = _pop_display_text(text, final=True)
    return stripped


def _pop_display_text(buffer: str, *, final: bool = False) -> tuple[str, str]:
    if not buffer:
        return "", ""

    output: list[str] = []
    index = 0
    while index < len(buffer):
        char = buffer[index]
        if char != "[":
            output.append(char)
            index += 1
            continue

        if index + 2 >= len(buffer):
            if not final:
                break
            output.append(char)
            index += 1
            continue

        if buffer[index + 1] in _TTS_EMOTION_TAGS and buffer[index + 2] == "]":
            index += 3
            continue

        output.append(char)
        index += 1

    return "".join(output), buffer[index:]


def _pop_complete_sentences(buffer: str) -> tuple[list[tuple[str, str]], str]:
    if not buffer:
        return [], ""

    complete: list[tuple[str, str]] = []
    start = 0
    index = 0
    while index < len(buffer):
        char = buffer[index]
        if char not in _SENTENCE_BOUNDARIES:
            index += 1
            continue

        end = index + 1
        if char in _SENTENCE_PUNCTUATION_BOUNDARIES:
            while (
                end < len(buffer)
                and buffer[end] in _SENTENCE_PUNCTUATION_BOUNDARIES
            ):
                end += 1

        sentence = buffer[start:end].strip()
        if sentence:
            parsed_sentence, emotion = _parse_sentence_emotion(sentence)
            if parsed_sentence:
                complete.append((parsed_sentence, emotion))

        start = end
        while start < len(buffer) and buffer[start].isspace():
            start += 1
        index = start

    MIN_SENTENCE_CHARS = 15
    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(complete):
        sentence, emotion = complete[i]
        # 持续向后合并，直到句子够长或没有后续句子
        while len(sentence) < MIN_SENTENCE_CHARS and i + 1 < len(complete):
            i += 1
            next_sentence, next_emotion = complete[i]
            sentence = sentence + next_sentence
            emotion = next_emotion if next_emotion != "neutral" else emotion
        merged.append((sentence, emotion))
        i += 1
    complete = merged

    return complete, buffer[start:]


async def _get_checkpointer() -> Any:
    global _checkpointer, _checkpointer_context

    if _checkpointer is None:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        _ensure_agent_db()
        checkpoint_path = Path(agent_settings.agent_db_dir) / "checkpoints.sqlite"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        _checkpointer_context = AsyncSqliteSaver.from_conn_string(
            str(checkpoint_path),
        )
        _checkpointer = await _checkpointer_context.__aenter__()

    return _checkpointer


def _ensure_agent_db() -> None:
    agent_db.init_db(Path(agent_settings.agent_db_dir) / "agent.sqlite")


def _ensure_memory() -> None:
    global _memory_initialized

    if not _memory_initialized:
        from app.agent import memory as agent_memory

        chroma_dir = Path(agent_settings.agent_db_dir) / "chroma"
        agent_memory.init_memory(chroma_dir)
        _memory_initialized = True


def _get_session_row(session_id: str) -> Any | None:
    with agent_db._connect() as conn:
        return conn.execute(
            """
            SELECT
                id,
                user_id,
                started_at,
                last_active_at,
                duration_minutes,
                turn_count,
                summary
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()


def _session_info(row: Any) -> SessionInfo:
    return SessionInfo(
        session_id=str(row["id"]),
        user_id=str(row["user_id"]),
        started_at=str(row["started_at"]),
        last_active_at=str(row["last_active_at"]),
        duration_minutes=int(row["duration_minutes"]),
        turn_count=int(row["turn_count"]),
        summary=row["summary"],
    )


def _duration_minutes(row: Any | None) -> int:
    if row is None:
        return 0

    started_at = _parse_datetime(str(row["started_at"]))
    if started_at is None:
        return int(row["duration_minutes"])

    return max(
        0,
        int((datetime.now(timezone.utc) - started_at).total_seconds() // 60),
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _thread_config(session_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": session_id}}


def _identity_disclosure(is_first_turn: bool) -> str | None:
    if is_first_turn and agent_settings.enforce_identity_disclosure:
        return IDENTITY_DISCLOSURE
    return None


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
