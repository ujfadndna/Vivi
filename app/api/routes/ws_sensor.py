"""WebSocket bridge: phone browser sensor data -> Unity WebGL.

Phone connects to /ws/sensor/{session_id} and sends JSON sensor frames.
Unity connects to /ws/unity/{session_id} and receives forwarded frames.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.routes.ws_audio import get_connected_sessions

router = APIRouter()

# Phone connections: session_id -> WebSocket
_phone_connections: dict[str, WebSocket] = {}
# Unity sensor connections: session_id -> WebSocket
_unity_sensor_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/sensor/{session_id}")
async def phone_sensor_stream(websocket: WebSocket, session_id: str):
    """Phone browser connects here and sends sensor data frames."""
    await websocket.accept()
    _phone_connections[session_id] = websocket
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue

            unity_ws = _unity_sensor_connections.get(session_id)
            if unity_ws is not None:
                try:
                    await unity_ws.send_text(json.dumps(frame, ensure_ascii=False))
                except Exception:
                    if _unity_sensor_connections.get(session_id) is unity_ws:
                        _unity_sensor_connections.pop(session_id, None)
    except WebSocketDisconnect:
        pass
    finally:
        if _phone_connections.get(session_id) is websocket:
            _phone_connections.pop(session_id, None)


@router.websocket("/ws/unity/{session_id}")
async def unity_sensor_receiver(websocket: WebSocket, session_id: str):
    """Unity connects here to receive forwarded sensor data from the phone."""
    await websocket.accept()
    _unity_sensor_connections[session_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        if _unity_sensor_connections.get(session_id) is websocket:
            _unity_sensor_connections.pop(session_id, None)


@router.get("/ws/status")
async def ws_status():
    return {
        "phone_connections": list(_phone_connections.keys()),
        "unity_audio_sessions": get_connected_sessions(),
        "unity_sensor_connections": list(_unity_sensor_connections.keys()),
    }
