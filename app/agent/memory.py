"""Stable long-term memory interface backed by Chroma.

The functions in this module are the public contract for agent long memory.
Callers should depend on this interface rather than Chroma details so the
storage backend can be replaced later without touching agent workflow code.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

_COLLECTION_NAME = "long_term_memory"
_logger = logging.getLogger(__name__)

_client: Any | None = None
_collection: Any | None = None


def init_memory(chroma_dir: Path) -> None:
    """Initialize the persistent Chroma collection for long-term memory."""
    global _client, _collection

    import chromadb

    chroma_path = Path(chroma_dir)
    chroma_path.mkdir(parents=True, exist_ok=True)

    _client = chromadb.PersistentClient(path=str(chroma_path))
    _collection = _client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def store_memory(
    user_id: str,
    session_id: str,
    content: str,
    memory_type: str,
    confidence: float = 1.0,
    source_turn: int | None = None,
) -> str:
    """Store one long-term memory and return its generated entry id."""
    collection = _get_collection()
    entry_id = f"mem_{uuid4().hex}"

    metadata: dict[str, str | int | float] = {
        "user_id": user_id,
        "session_id": session_id,
        "memory_type": memory_type,
        "confidence": float(confidence),
        "created_at": _now(),
    }
    if source_turn is not None:
        metadata["source_turn"] = int(source_turn)

    try:
        collection.add(
            ids=[entry_id],
            documents=[content],
            metadatas=[metadata],
        )
    except Exception as e:  # noqa: BLE001 - memory writes are best-effort.
        _logger.warning("store_memory failed: %s", e)
    return entry_id


def recall_memories(user_id: str, query: str, top_k: int = 5) -> list[str]:
    """Return semantically relevant memory contents for one user."""
    if top_k <= 0:
        return []

    collection = _get_collection()
    if collection is None:
        return []

    try:
        # ChromaDB 默认 embedding function 需要网络。
        # 如果 collection 为空则不需要 query（避免触发 embedding 调用）。
        if collection.count() == 0:
            return []
        result = collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"user_id": user_id},
            include=["documents"],
        )
    except Exception as e:
        _logger.warning("recall_memories failed: %s", e)
        return []

    documents = result.get("documents") or []
    if not documents:
        return []

    return [doc for doc in documents[0] if doc is not None]


def delete_user_memories(user_id: str) -> None:
    """Delete all long-term memories for one user."""
    collection = _get_collection()
    collection.delete(where={"user_id": user_id})


def _get_collection() -> Any:
    if _collection is None:
        raise RuntimeError("call init_memory() before using memory helpers")
    return _collection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
