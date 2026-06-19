"""Defines shared LangGraph state types for the therapist agent workflow."""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

RiskLevel = Literal["safe", "unsafe_self_harm_risk", "unsafe_harm_to_others"]
TtsEmotion = Literal["neutral", "warm", "calm", "sad_soft", "encouraging"]


class TherapistState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_emotion: str
    risk_level: RiskLevel
    retrieved_memories: list[str]
    response_text: str
    tts_emotion: TtsEmotion
    session_duration_minutes: int
    pause_required: bool
    session_id: str
    user_id: str
