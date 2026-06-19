"""WebSocket endpoint: streams TTS PCM audio to Unity WebGL for uLipSync."""
from __future__ import annotations

import json
import struct
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Active Unity WebSocket connections: session_id -> WebSocket
_unity_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/audio/{session_id}")
async def audio_stream(websocket: WebSocket, session_id: str):
    """Unity connects here to receive TTS audio chunks in real-time."""
    await websocket.accept()
    _unity_connections[session_id] = websocket
    try:
        while True:
            # Keep connection alive; Unity sends pings.
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        if _unity_connections.get(session_id) is websocket:
            _unity_connections.pop(session_id, None)


async def push_audio_chunk(session_id: str, pcm_bytes: bytes, sample_rate: int = 22050) -> bool:
    """Push a PCM chunk to the connected Unity client. Returns False if no client."""
    ws = _unity_connections.get(session_id)
    if ws is None:
        return False
    try:
        # Binary frame: 4-byte header (sample_rate as uint32) + PCM bytes.
        header = struct.pack(">I", sample_rate)
        await ws.send_bytes(header + pcm_bytes)
        return True
    except Exception:
        if _unity_connections.get(session_id) is ws:
            _unity_connections.pop(session_id, None)
        return False


async def push_audio_event(session_id: str, event: dict[str, Any]) -> bool:
    """Push a JSON control event (sentence_start, sentence_end, done) to Unity."""
    ws = _unity_connections.get(session_id)
    if ws is None:
        return False
    try:
        await ws.send_text(json.dumps(event, ensure_ascii=False))
        return True
    except Exception:
        if _unity_connections.get(session_id) is ws:
            _unity_connections.pop(session_id, None)
        return False


def get_connected_sessions() -> list[str]:
    return list(_unity_connections.keys())
