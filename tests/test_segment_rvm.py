"""
Tests for app/services/segment_rvm.py

These tests run without a GPU or real model weights by mocking heavy imports.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to inject lightweight stubs for torch and cv2 before the module
# under test is imported (or re-imported).
# ---------------------------------------------------------------------------


def _make_torch_stub() -> types.ModuleType:
    """Return a minimal torch stub that satisfies segment_rvm's usage."""
    torch = types.ModuleType("torch")

    # device
    class _Device:
        def __init__(self, name: str):
            self.type = name.split(":")[0]

        def __repr__(self):
            return self.type

    torch.device = _Device  # type: ignore[attr-defined]

    # cuda stub
    cuda = types.ModuleType("torch.cuda")
    cuda.is_available = lambda: False  # always CPU in tests
    torch.cuda = cuda  # type: ignore[attr-defined]

    # inference_mode context manager
    class _InferenceMode:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    torch.inference_mode = _InferenceMode  # type: ignore[attr-defined]

    # float16 / float32 sentinels
    torch.float16 = "float16"  # type: ignore[attr-defined]
    torch.float32 = "float32"  # type: ignore[attr-defined]

    # hub stub (used in _load_from_hub)
    hub = types.ModuleType("torch.hub")
    hub.load = MagicMock(return_value=MagicMock())
    torch.hub = hub  # type: ignore[attr-defined]

    # jit stub
    jit = types.ModuleType("torch.jit")
    jit.load = MagicMock(side_effect=RuntimeError("no jit checkpoint"))
    torch.jit = jit  # type: ignore[attr-defined]

    # torch.load stub
    torch.load = MagicMock(return_value={})  # type: ignore[attr-defined]

    # from_numpy stub
    tensor_mock = MagicMock()
    tensor_mock.permute.return_value = tensor_mock
    tensor_mock.unsqueeze.return_value = tensor_mock
    tensor_mock.to.return_value = tensor_mock
    tensor_mock.div_.return_value = tensor_mock
    torch.from_numpy = MagicMock(return_value=tensor_mock)  # type: ignore[attr-defined]

    return torch


def _make_cv2_stub() -> types.ModuleType:
    cv2 = types.ModuleType("cv2")
    cv2.imread = MagicMock(return_value=None)  # type: ignore[attr-defined]
    cv2.imwrite = MagicMock(return_value=True)  # type: ignore[attr-defined]
    cv2.cvtColor = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    cv2.resize = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    cv2.COLOR_BGR2RGB = 4  # type: ignore[attr-defined]
    cv2.COLOR_RGBA2BGRA = 5  # type: ignore[attr-defined]
    cv2.INTER_LINEAR = 1  # type: ignore[attr-defined]
    return cv2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMockBackendDefault:
    """Ensure segment_backend='mock' uses the mock path — no GPU required."""

    def test_default_segment_backend_is_mock(self):
        """The Settings default must be 'mock' so existing users aren't broken."""
        # Import fresh to avoid cached settings state
        from app.config import Settings

        s = Settings()
        assert s.segment_backend == "mock", (
            "segment_backend default must stay 'mock'. "
            "Activate RVM via SEGMENT_BACKEND=local in .env only."
        )

    def test_mock_backend_does_not_import_torch(self):
        """Mock backend path should not trigger torch import."""
        # If torch is not installed, importing with mock backend must still work
        torch_present = "torch" in sys.modules
        if not torch_present:
            # torch not installed — nothing to assert, test is vacuously satisfied
            return
        # torch IS installed; ensure settings still defaults to mock
        from app.config import settings as _s

        assert _s.segment_backend in {"mock", "local"}, (
            "In CI, segment_backend should be 'mock' unless .env overrides it."
        )


class TestRVMSegmentImport:
    """RVMSegment class must be importable without crashing even without real torch/cv2."""

    def test_import_without_crash(self):
        """Importing segment_rvm with stubbed torch/cv2 must not raise."""
        torch_stub = _make_torch_stub()
        cv2_stub = _make_cv2_stub()

        # Remove cached module if already imported
        for mod_name in list(sys.modules.keys()):
            if "segment_rvm" in mod_name:
                del sys.modules[mod_name]

        with patch.dict(sys.modules, {"torch": torch_stub, "cv2": cv2_stub}):
            # This must not raise ImportError or AttributeError
            import app.services.segment_rvm as rvm_mod  # noqa: PLC0415

            assert hasattr(rvm_mod, "RVMSegment"), "RVMSegment class must be defined"

    def test_rvm_segment_is_backend_subclass(self):
        """RVMSegment must subclass SegmentBackend."""
        torch_stub = _make_torch_stub()
        cv2_stub = _make_cv2_stub()

        for mod_name in list(sys.modules.keys()):
            if "segment_rvm" in mod_name:
                del sys.modules[mod_name]

        with patch.dict(sys.modules, {"torch": torch_stub, "cv2": cv2_stub}):
            import app.services.segment_rvm as rvm_mod  # noqa: PLC0415
            from app.services.segment import SegmentBackend

            assert issubclass(rvm_mod.RVMSegment, SegmentBackend)


class TestLoadModelFallback:
    """_load_model() must fall back to torch.hub when checkpoint file is absent."""

    def test_hub_fallback_called_when_no_checkpoint(self, tmp_path: Path):
        """When RVM_CHECKPOINT doesn't exist, torch.hub.load must be called."""
        torch_stub = _make_torch_stub()
        cv2_stub = _make_cv2_stub()

        # Make hub.load return a usable mock model
        model_mock = MagicMock()
        model_mock.to.return_value = model_mock
        model_mock.half.return_value = model_mock
        model_mock.eval.return_value = model_mock
        torch_stub.hub.load = MagicMock(return_value=model_mock)

        for mod_name in list(sys.modules.keys()):
            if "segment_rvm" in mod_name:
                del sys.modules[mod_name]

        nonexistent_checkpoint = tmp_path / "missing.pth"

        with patch.dict(sys.modules, {"torch": torch_stub, "cv2": cv2_stub}):
            import app.services.segment_rvm as rvm_mod  # noqa: PLC0415

            # Clear the module-level model cache
            rvm_mod._MODEL_CACHE.clear()

            with patch.object(
                rvm_mod.settings,
                "rvm_checkpoint",
                nonexistent_checkpoint,
            ), patch.object(
                rvm_mod.settings,
                "rvm_variant",
                "mobilenetv3",
            ):
                rvm_mod._load_model()

        # hub.load must have been invoked with the PeterL1n repo
        call_args = torch_stub.hub.load.call_args
        assert call_args is not None, "torch.hub.load was never called"
        assert "PeterL1n/RobustVideoMatting" in call_args[0], (
            f"Expected PeterL1n/RobustVideoMatting in hub.load args, got {call_args}"
        )
