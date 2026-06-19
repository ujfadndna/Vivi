"""In-process frame streaming fan-out for render previews."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StreamSubscriber:
    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop
    task_id: str | None


class StreamHub:
    """Thread-safe publisher for WebSocket render events.

    MuseTalk's persistent worker reader runs in a background thread, while
    WebSocket clients live on the FastAPI event loop.  Each subscriber keeps
    its own event loop so publishers can safely enqueue from either context.
    """

    def __init__(self, max_queue_size: int = 64) -> None:
        self._max_queue_size = max_queue_size
        self._lock = threading.Lock()
        self._subscribers: set[StreamSubscriber] = set()

    def subscribe(self, task_id: str | None = None) -> StreamSubscriber:
        subscriber = StreamSubscriber(
            queue=asyncio.Queue(maxsize=self._max_queue_size),
            loop=asyncio.get_running_loop(),
            task_id=task_id,
        )
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: StreamSubscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event from any thread.

        Slow clients drop their oldest queued event instead of blocking render
        workers.  Frame previews are transient; the final MP4 remains the
        source of truth.
        """
        task_id = _event_task_id(event)
        with self._lock:
            subscribers = list(self._subscribers)

        for subscriber in subscribers:
            if subscriber.task_id and subscriber.task_id != task_id:
                continue
            subscriber.loop.call_soon_threadsafe(
                self._enqueue_latest,
                subscriber.queue,
                dict(event),
            )

    @staticmethod
    def _enqueue_latest(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _event_task_id(event: dict[str, Any]) -> str | None:
    value = event.get("task_id")
    return value if isinstance(value, str) and value else None


stream_hub = StreamHub()
