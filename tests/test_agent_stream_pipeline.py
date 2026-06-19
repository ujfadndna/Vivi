from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from app.api.routes import agent
from app.schemas import TaskState
from app.tasks import store


def test_pop_complete_sentences_handles_newlines_and_ascii_boundaries():
    sentences, rest = agent._pop_complete_sentences(
        "第一句。\n第二句!\n第三句还没结束"
    )

    assert sentences == [("第一句。第二句!", "warm")]
    assert rest == "第三句还没结束"


def test_chat_stream_events_runs_langgraph_updates(monkeypatch):
    session_id = "test-langgraph-stream"
    node_events: list[str] = []

    class FakeGraph:
        async def astream(self, input_state, config, stream_mode):
            assert input_state["messages"] == [HumanMessage(content="你好")]
            assert input_state["user_id"] == "user-1"
            assert input_state["session_id"] == session_id
            assert config == {"configurable": {"thread_id": session_id}}
            assert stream_mode == "updates"
            for node_name, update in [
                ("perceive", {"user_emotion": "难过"}),
                ("safety_check", {"risk_level": "safe"}),
                ("retrieve_memory", {"retrieved_memories": []}),
                ("think", {"response_text": "我听到了。我们慢慢来。"}),
                ("calibrate_emotion", {"tts_emotion": "warm", "pause_required": False}),
                ("render", {"messages": []}),
            ]:
                node_events.append(node_name)
                yield {node_name: update}

    class FakeCheckpointer:
        async def aget(self, config):
            return None

    async def run_test() -> list[dict]:
        monkeypatch.setattr(agent, "_get_checkpointer", lambda: _async_value(FakeCheckpointer()))
        monkeypatch.setattr(agent, "_get_graph", lambda: _async_value(FakeGraph()))
        monkeypatch.setattr(agent, "_ensure_agent_db", lambda: None)
        monkeypatch.setattr(agent, "_ensure_memory", lambda: None)
        monkeypatch.setattr(agent.agent_db, "upsert_session", lambda **kwargs: None)
        monkeypatch.setattr(agent, "_get_session_row", lambda session_id: None)
        monkeypatch.setattr(agent.agent_db, "update_session_turn", lambda **kwargs: None)
        monkeypatch.setattr(agent, "_extract_and_store_conversation_memories", _async_noop)

        req = agent.ChatRequest(
            user_id="user-1",
            session_id=session_id,
            text="你好",
            render_video=False,
        )
        return [event async for event in agent._chat_stream_events(req)]

    events = asyncio.run(run_test())

    assert node_events == [
        "perceive",
        "safety_check",
        "retrieve_memory",
        "think",
        "calibrate_emotion",
        "render",
    ]
    assert [event["type"] for event in events] == [
        "session",
        "token",
        "sentence",
        "done",
    ]
    assert events[1]["text"] == "我听到了。我们慢慢来。"
    assert events[2]["text"] == "我听到了。我们慢慢来。"
    assert events[-1]["response_text"] == "我听到了。我们慢慢来。"
    assert events[-1]["risk_level"] == "safe"
    assert events[-1]["tts_emotion"] == "warm"


def test_render_sentence_pipeline_submits_after_tts_and_emits_done(monkeypatch):
    events: list[str] = []
    task_id = "test-agent-stream-pipeline"

    def fake_synthesize(sentence: str, emotion: str, fps: float) -> str:
        assert sentence == "第一句。"
        assert emotion == "warm"
        assert fps == 25.0
        events.append("tts")
        return "audio"

    def fake_create_task() -> str:
        store.create(task_id)
        return task_id

    def fake_submit(task_id: str, video, audio) -> None:
        assert task_id == "test-agent-stream-pipeline"
        assert video.fps == 25.0
        assert audio == "audio"
        events.append("submit")
        loop = asyncio.get_running_loop()
        loop.call_soon(store.set_status, task_id, TaskState.processing)
        loop.call_soon(store.finish, task_id, "/outputs/test-agent-stream-pipeline.mp4")

    async def run_test() -> list[dict]:
        monkeypatch.setattr(agent, "_RENDER_POLL_INTERVAL_SECONDS", 0)
        monkeypatch.setattr(agent, "_synthesize_sentence_audio", fake_synthesize)
        monkeypatch.setattr(agent, "_create_render_task_id", fake_create_task)
        monkeypatch.setattr(agent, "_submit_render_task_from_audio", fake_submit)

        queue: asyncio.Queue[dict | object] = asyncio.Queue()
        avatar_task = asyncio.create_task(_fake_avatar())
        await agent._render_sentence_pipeline(
            index=0,
            sentence="第一句。",
            tts_emotion="warm",
            avatar_task=avatar_task,
            event_queue=queue,
        )

        queued_events: list[dict] = []
        while not queue.empty():
            queued_events.append(queue.get_nowait())
        return queued_events

    queued_events = asyncio.run(run_test())

    assert events == ["tts", "submit"]
    assert [event["type"] for event in queued_events] == [
        "render_start",
        "render_done",
    ]
    assert queued_events[0]["task_id"] == task_id
    assert queued_events[0]["text"] == "第一句。"
    assert queued_events[0]["sentence"] == "第一句。"
    assert queued_events[1]["status"] == "completed"
    assert queued_events[1]["text"] == "第一句。"
    assert queued_events[1]["sentence"] == "第一句。"
    assert queued_events[1]["video_url"] == "/outputs/test-agent-stream-pipeline.mp4"


def test_wait_for_render_done_backfills_missing_video_url(monkeypatch):
    task_id = "test-agent-stream-missing-url"
    store.create(task_id)
    store.set_status(task_id, TaskState.completed)

    async def run_test() -> dict:
        monkeypatch.setattr(agent, "_RENDER_POLL_INTERVAL_SECONDS", 0)
        return await agent._wait_for_render_done(
            index=2,
            sentence="第三句。",
            task_id=task_id,
        )

    event = asyncio.run(run_test())

    assert event == {
        "type": "render_done",
        "index": 2,
        "text": "第三句。",
        "sentence": "第三句。",
        "status": "completed",
        "task_id": task_id,
        "video_url": "/outputs/test-agent-stream-missing-url.mp4",
    }
    assert store.get(task_id).video_url == "/outputs/test-agent-stream-missing-url.mp4"


async def _fake_avatar() -> SimpleNamespace:
    return SimpleNamespace(fps=25.0)


async def _async_value(value):
    return value


async def _async_noop(*args, **kwargs):
    return None
