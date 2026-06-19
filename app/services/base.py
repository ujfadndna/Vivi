"""后端注册表。每个模块的实现（mock / local / cloud）注册到此，
按 config 选择。这是「模型服务完全可插拔」的落地机制。

用法：
    @register("tts", "mock")
    class MockTTS(TTSBackend):
        ...

    backend = get_backend("tts", settings.tts_backend)
"""
from __future__ import annotations

from typing import Type

_REGISTRY: dict[str, dict[str, Type]] = {}


def register(module: str, backend: str):
    def deco(cls: Type) -> Type:
        _REGISTRY.setdefault(module, {})[backend] = cls
        return cls

    return deco


def get_backend(module: str, backend: str) -> Type:
    try:
        return _REGISTRY[module][backend]
    except KeyError as e:
        available = list(_REGISTRY.get(module, {}).keys())
        raise ValueError(
            f"未注册的后端 module={module!r} backend={backend!r}；"
            f"已注册：{available}"
        ) from e
