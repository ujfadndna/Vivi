"""LangGraph workflow for the therapist agent."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph

from app.agent import memory as mem_store
from app.agent.agent_config import agent_settings
from app.agent.prompts import *
from app.agent.safety import check_safety, get_crisis_response
from app.agent.state import TherapistState
from app.agent.tools import ALL_TOOLS

_llm: BaseChatModel | None = None
_llm_key: tuple[str, str, str | None] | None = None


def get_llm() -> BaseChatModel:
    """Return the shared chat model, initialized on first use."""
    global _llm, _llm_key

    provider = agent_settings.agent_llm_provider.strip().lower()
    key = (
        provider,
        agent_settings.agent_llm_model,
        agent_settings.agent_llm_base_url,
    )
    if _llm is not None and _llm_key == key:
        return _llm

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": agent_settings.agent_llm_model,
            "temperature": agent_settings.agent_llm_temperature,
        }
        if agent_settings.agent_llm_api_key:
            kwargs["api_key"] = agent_settings.agent_llm_api_key
        _llm = ChatAnthropic(**kwargs)
    elif provider in {"openai", "deepseek"}:
        from langchain_openai import ChatOpenAI

        base_url = agent_settings.agent_llm_base_url
        if provider == "deepseek" and not base_url:
            base_url = "https://api.deepseek.com"
        kwargs = {
            "model": agent_settings.agent_llm_model,
            "temperature": agent_settings.agent_llm_temperature,
        }
        if base_url:
            kwargs["base_url"] = base_url
        if agent_settings.agent_llm_api_key:
            kwargs["api_key"] = agent_settings.agent_llm_api_key
        _llm = ChatOpenAI(**kwargs)
    else:
        raise ValueError(
            "AGENT_LLM_PROVIDER must be one of: anthropic, openai, deepseek"
        )

    _llm_key = key
    return _llm


async def perceive(state: TherapistState) -> dict[str, str]:
    """Classify the latest user emotion with the LLM."""
    user_text = _latest_human_text(state)
    prompt = PERCEIVE_PROMPT.format(user_input=user_text)
    response = await get_llm().ainvoke([HumanMessage(content=prompt)])
    return {"user_emotion": _normalize_emotion(_message_content_to_text(response.content))}


def safety_check(state: TherapistState) -> dict[str, str]:
    """Run deterministic safety checks against the latest user message."""
    result = check_safety(_latest_human_text(state))
    return {"risk_level": result.risk_level}


def crisis_response(state: TherapistState) -> dict[str, str]:
    """Return the fixed crisis response for unsafe inputs."""
    return {
        "response_text": get_crisis_response(state["risk_level"]),
        "tts_emotion": "calm",
    }


def retrieve_memory(state: TherapistState) -> dict[str, list[str]]:
    """Recall long-term memories relevant to the latest user message."""
    memories = mem_store.recall_memories(
        user_id=state["user_id"],
        query=_latest_human_text(state),
        top_k=agent_settings.long_memory_top_k,
    )
    return {"retrieved_memories": memories}


async def think(state: TherapistState) -> dict[str, str]:
    """Generate the therapist response from system prompt, memories, and history."""
    system_prompt = _build_system_prompt(state.get("retrieved_memories", []))
    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        *state["messages"][-40:],
    ]
    response = await get_llm().bind_tools(ALL_TOOLS).ainvoke(messages)

    if getattr(response, "tool_calls", None):
        tool_map = {tool.name: tool for tool in ALL_TOOLS}
        tool_results: list[BaseMessage] = [response]
        for tool_call in response.tool_calls:
            tool_name = tool_call.get("name")
            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                result = f"未知工具: {tool_name}"
            else:
                tool_args = dict(tool_call.get("args") or {})
                if tool_name in {"add_todo", "list_todos"}:
                    tool_args.setdefault("user_id", state["user_id"])
                try:
                    result = tool_fn.invoke(tool_args)
                except Exception as e:  # noqa: BLE001 - return tool errors to the model.
                    result = f"工具调用失败: {e}"
            tool_results.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )

        final_response = await get_llm().ainvoke(messages + tool_results)
        return {"response_text": _message_content_to_text(final_response.content).strip()}

    return {"response_text": _message_content_to_text(response.content).strip()}


def calibrate_emotion(state: TherapistState) -> dict[str, str | bool]:
    """Map user emotion to TTS emotion and decide whether a pause is required."""
    emotion_map = {
        "\u60b2\u4f24": "warm",
        "\u96be\u8fc7": "warm",
        "\u4f24\u5fc3": "warm",
        "\u5931\u843d": "warm",
        "\u75db\u82e6": "warm",
        "\u5b64\u72ec": "warm",
        "\u6cae\u4e27": "warm",
        "\u5fe7\u90c1": "warm",
        "\u59d4\u5c48": "warm",
        "\u54ed\u6ce3": "warm",
        "\u96be\u53d7": "warm",
        "sad": "warm",
        "sadness": "warm",
        "upset": "warm",
        "depressed": "warm",
        "lonely": "warm",
        "crying": "warm",
        "\u7126\u8651": "calm",
        "\u7d27\u5f20": "calm",
        "\u62c5\u5fe7": "calm",
        "\u538b\u529b": "calm",
        "\u75b2\u60eb": "calm",
        "\u5d29\u6e83": "calm",
        "\u65e0\u529b": "calm",
        "\u614c\u5f20": "calm",
        "anxious": "calm",
        "anxiety": "calm",
        "nervous": "calm",
        "worried": "calm",
        "stressed": "calm",
        "tired": "calm",
        "overwhelmed": "calm",
        "panic": "calm",
        "\u6124\u6012": "calm",
        "\u7f9e\u803b": "calm",
        "\u81ea\u8d23": "calm",
        "\u540e\u6094": "calm",
        "\u61ca\u6094": "calm",
        "angry": "calm",
        "anger": "calm",
        "ashamed": "calm",
        "guilty": "calm",
        "regret": "calm",
        "\u5f00\u5fc3": "encouraging",
        "\u9ad8\u5174": "encouraging",
        "\u5feb\u4e50": "encouraging",
        "\u6109\u5feb": "encouraging",
        "\u6ee1\u8db3": "encouraging",
        "\u671f\u5f85": "encouraging",
        "\u5174\u594b": "encouraging",
        "\u611f\u6fc0": "encouraging",
        "happy": "encouraging",
        "joy": "encouraging",
        "joyful": "encouraging",
        "excited": "encouraging",
        "grateful": "encouraging",
        "\u5e73\u9759": "neutral",
        "\u5e73\u548c": "neutral",
        "\u597d": "neutral",
        "\u8fd8\u597d": "neutral",
        "\u8fd8\u884c": "neutral",
        "\u4e00\u822c": "neutral",
        "neutral": "neutral",
        "calm": "neutral",
        "peaceful": "neutral",
        "\u5bb3\u6015": "calm",
        "\u6050\u60e7": "calm",
        "\u6050\u614c": "calm",
        "fear": "calm",
        "afraid": "calm",
        "scared": "calm",
    }
    user_emotion = state.get("user_emotion", "").strip().lower()
    return {
        "tts_emotion": emotion_map.get(user_emotion, "warm"),
        "pause_required": state.get("session_duration_minutes", 0) >= 120,
    }


def render(state: TherapistState) -> dict[str, list[AIMessage]]:
    """Append the generated assistant response to the message history."""
    return {"messages": [AIMessage(content=state["response_text"])]}


def route_after_safety(
    state: TherapistState,
) -> Literal["crisis_response", "retrieve_memory"]:
    """Route unsafe inputs to crisis response, otherwise continue normally."""
    if state["risk_level"] != "safe":
        return "crisis_response"
    return "retrieve_memory"


def build_graph(checkpointer: Any):
    """Build and compile the therapist agent state machine."""
    graph = StateGraph(TherapistState)

    graph.add_node("perceive", perceive)
    graph.add_node("safety_check", safety_check)
    graph.add_node("crisis_response", crisis_response)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("think", think)
    graph.add_node("calibrate_emotion", calibrate_emotion)
    graph.add_node("render", render)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "safety_check")
    graph.add_conditional_edges(
        "safety_check",
        route_after_safety,
        {
            "crisis_response": "crisis_response",
            "retrieve_memory": "retrieve_memory",
        },
    )
    graph.add_edge("crisis_response", END)
    graph.add_edge("retrieve_memory", "think")
    graph.add_edge("think", "calibrate_emotion")
    graph.add_edge("calibrate_emotion", "render")
    graph.add_edge("render", END)

    return graph.compile(checkpointer=checkpointer)


def _latest_human_text(state: TherapistState) -> str:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage) or getattr(message, "type", None) == "human":
            return _message_content_to_text(message.content)
    raise ValueError("TherapistState.messages must include at least one HumanMessage")


def _build_system_prompt(memories: list[str]) -> str:
    today = datetime.now().date().isoformat()
    return f"{THERAPIST_SYSTEM_PROMPT.format(date=today)}{_format_memory_block(memories)}"


def _format_memory_block(memories: list[str]) -> str:
    header = "\u76f8\u5173\u8bb0\u5fc6"
    if not memories:
        return f"\n\n{header}: \u65e0."

    memory_lines = "\n".join(f"- {memory}" for memory in memories if memory.strip())
    if not memory_lines:
        return f"\n\n{header}: \u65e0."
    return f"\n\n{header}:\n{memory_lines}"


def _normalize_emotion(value: str) -> str:
    trim_chars = " :,\u3002\uff1a\uff0c."
    emotion = value.strip().splitlines()[0].strip(trim_chars) if value.strip() else ""
    return emotion or "neutral"


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)
