"""Agent-specific configuration."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    render_base_url: str = "http://localhost:8000"
    agent_db_dir: Path = Path("./workspace/agent")
    agent_llm_provider: str = "anthropic"
    agent_llm_model: str = "claude-haiku-4-5-20251001"
    agent_llm_temperature: float = 0.7
    agent_llm_base_url: str | None = None
    agent_llm_api_key: str | None = None
    short_memory_turns: int = 20
    long_memory_top_k: int = 4
    session_max_minutes: int = 120
    enforce_identity_disclosure: bool = True


agent_settings = AgentSettings()
