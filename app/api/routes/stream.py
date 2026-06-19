"""WebSocket routes for streaming MuseTalk preview frames."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.stream_bus import stream_hub

router = APIRouter(tags=["stream"])


@router.websocket("/ws/stream")
async def stream_frames(websocket: WebSocket) -> None:
    await websocket.accept()
    task_id = websocket.query_params.get("task_id") or None
    subscriber = stream_hub.subscribe(task_id=task_id)
    await websocket.send_json({"type": "ready", "task_id": task_id})
    try:
        while True:
            event = await subscriber.queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        stream_hub.unsubscribe(subscriber)
