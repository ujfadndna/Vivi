"""Verify the locally testable MVP-2 modules.

The script starts one mock-mode FastAPI service on port 8001, runs the requested
checks in order, prints [PASS]/[FAIL] per validation, and always tears down the
service process.  It intentionally avoids checking segmentation log lines.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


PORT = 8001
HOST = "127.0.0.1"
BASE_URL = f"http://{HOST}:{PORT}"
WS_URL = f"ws://{HOST}:{PORT}/ws/stream"
SERVICE_TIMEOUT_SEC = 60.0
TASK_TIMEOUT_SEC = 35.0

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "workspace" / "verify_mvp2_runtime"
INPUT_VIDEO = RUNTIME_DIR / "verify_input.mp4"
UVICORN_LOG = RUNTIME_DIR / "uvicorn_8001.log"
PYTHON_EXE = None


@dataclass
class Result:
    name: str
    status: str
    reason: str


RESULTS: list[Result] = []
OPTIONAL_RESULTS: list[Result] = []


def main() -> int:
    global PYTHON_EXE
    _configure_stdout()
    PYTHON_EXE = _select_python()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_input_video(INPUT_VIDEO)

    proc: subprocess.Popen[str] | None = None
    timer: threading.Timer | None = None
    service_error: str | None = None

    try:
        proc = _start_service()
        timer = threading.Timer(SERVICE_TIMEOUT_SEC, _kill_service, args=(proc,))
        timer.daemon = True
        timer.start()
        _wait_for_health(proc)
    except Exception as exc:  # noqa: BLE001 - keep running structural checks.
        service_error = str(exc)

    try:
        if service_error:
            record("验证 1：Module 12 - 跳过 RVM", "FAIL", f"服务未启动：{service_error}")
            record("验证 2：Module 13 - WebSocket 流式帧", "FAIL", f"服务未启动：{service_error}")
            _verify_module14_agent_structural(service_ready=False, service_error=service_error)
            record("验证 4：Module 15 - chat.html", "FAIL", f"服务未启动：{service_error}")
            _verify_module11_structure()
        else:
            _verify_module12_skip_rvm()
            _verify_module13_websocket_frames()
            _verify_module14_agent_structural(service_ready=True, service_error=None)
            _verify_module15_chat_html()
            _verify_module11_structure()
    finally:
        if timer is not None:
            timer.cancel()
        if proc is not None:
            _kill_service(proc)

    _print_summary()
    return 0 if all(result.status in {"PASS", "SKIP"} for result in RESULTS) else 1


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def record(name: str, status: str, reason: str) -> None:
    RESULTS.append(Result(name=name, status=status, reason=reason))
    print(f"[{status}] {name} - {reason}", flush=True)


def record_optional(name: str, status: str, reason: str) -> None:
    OPTIONAL_RESULTS.append(Result(name=name, status=status, reason=reason))
    print(f"[{status}] {name} - {reason}", flush=True)


def _start_service() -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "INGEST_BACKEND": "mock",
            "TTS_BACKEND": "mock",
            "MUSETALK_BACKEND": "mock",
            "SEGMENT_BACKEND": "mock",
            "BACKGROUND_BACKEND": "mock",
            "COMPOSITE_BACKEND": "mock",
            "SKIP_RVM": "true",
            "MUSETALK_STREAM_FRAMES": "true",
            "WORKSPACE_DIR": str(RUNTIME_DIR),
            "AGENT_DB_DIR": str(RUNTIME_DIR / "agent"),
            "RENDER_BASE_URL": BASE_URL,
            # No real key is used; this keeps structural LLM construction local.
            "AGENT_LLM_PROVIDER": "deepseek",
            "AGENT_LLM_MODEL": "deepseek-chat",
            "AGENT_LLM_API_KEY": "mvp2-dummy-key",
        }
    )
    UVICORN_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_file = UVICORN_LOG.open("w", encoding="utf-8", errors="replace")
    return subprocess.Popen(
        [
            PYTHON_EXE or sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "info",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_health(proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20.0
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn 进程已退出，returncode={proc.returncode}，日志：{UVICORN_LOG}"
            )
        try:
            status, payload = _http_request("GET", "/health", timeout=1.5)
            if status == 200:
                data = json.loads(payload.decode("utf-8"))
                if data.get("status") == "ok":
                    return
        except Exception as exc:  # noqa: BLE001 - retry until deadline.
            last_error = str(exc)
        time.sleep(0.4)
    raise TimeoutError(f"/health 未在 20s 内返回 200；最后错误：{last_error}")


def _kill_service(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def _verify_module12_skip_rvm() -> None:
    name = "验证 1：Module 12 - 跳过 RVM"
    try:
        task_id = _submit_generate(INPUT_VIDEO, text="测试")
        status = _wait_for_task(task_id, timeout=TASK_TIMEOUT_SEC)
        if status.get("status") != "completed":
            record(name, "FAIL", f"任务未完成：status={status.get('status')} error={status.get('error')}")
            return

        progress = status.get("progress") or {}
        segmentation = progress.get("segmentation")
        if segmentation != "skipped":
            record(name, "FAIL", f"任务完成但 segmentation={segmentation!r}，预期 skipped")
            return

        output_path = RUNTIME_DIR / "outputs" / f"{task_id}.mp4"
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            record(name, "FAIL", f"MP4 未生成或为空：{output_path}")
            return

        video_url = status.get("video_url")
        record(
            name,
            "PASS",
            f"status=completed，segmentation=skipped，MP4={output_path} ({output_path.stat().st_size} bytes)，video_url={video_url}",
        )
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"{exc}")


def _verify_module13_websocket_frames() -> None:
    name = "验证 2：Module 13 - WebSocket 流式帧"
    try:
        try:
            import websockets  # noqa: F401
        except ModuleNotFoundError:
            _verify_websocket_endpoint_handshake()
            record(name, "PASS", "websockets 未安装；已用标准库 WebSocket 握手确认 /ws/stream 返回 101")
            return

        detail = asyncio.run(_websocket_frame_batch_check())
        record(name, "PASS", detail)
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"{exc}")


async def _websocket_frame_batch_check() -> str:
    import websockets

    async with websockets.connect(WS_URL, open_timeout=5, close_timeout=2) as ws:
        raw_ready = await asyncio.wait_for(ws.recv(), timeout=5)
        ready = json.loads(raw_ready)
        if ready.get("type") != "ready":
            raise AssertionError(f"握手消息不是 ready：{ready}")

        task_id = await asyncio.to_thread(_submit_generate, INPUT_VIDEO, "流式帧")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            raw_event = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.monotonic()))
            event = json.loads(raw_event)
            if event.get("type") != "frame_batch":
                continue
            if event.get("task_id") != task_id:
                continue
            frames = event.get("frames")
            if not isinstance(frames, list) or not frames:
                raise AssertionError(f"frame_batch 缺少 frames：{event}")
            return f"ready 握手成功，task_id={task_id}，收到 frame_batch(start_index={event.get('start_index')}, frames={len(frames)})"

        raise TimeoutError("30s 内未收到当前任务的 frame_batch")


def _verify_websocket_endpoint_handshake() -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    headers = (
        f"GET /ws/stream HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(headers.encode("ascii"))
        response = sock.recv(4096)
    status_line = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    if " 101 " not in f" {status_line} ":
        raise AssertionError(f"WebSocket 握手未返回 101：{status_line}")


def _verify_module14_agent_structural(service_ready: bool, service_error: str | None) -> None:
    name = "验证 3：Module 14 - Agent LLM（仅结构验证）"
    checks: list[str] = []
    failures: list[str] = []

    if service_ready:
        try:
            code = _post_agent_chat_stream_status()
            if code == 404:
                failures.append("/agent/chat/stream 返回 404")
            else:
                checks.append(f"/agent/chat/stream 非 404(status={code})")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"/agent/chat/stream 请求失败：{exc}")
    else:
        failures.append(f"/agent/chat/stream 未验证：服务未启动：{service_error}")

    ok, detail = _run_python_check(
        """
from app.agent.agent_config import agent_settings
assert agent_settings.agent_llm_provider == "deepseek", agent_settings.agent_llm_provider
print(agent_settings.agent_llm_provider)
""",
        env_overrides={
            "AGENT_LLM_PROVIDER": "deepseek",
            "AGENT_LLM_MODEL": "deepseek-chat",
            "AGENT_LLM_API_KEY": "mvp2-dummy-key",
        },
    )
    if ok:
        checks.append("agent_config 解析 AGENT_LLM_PROVIDER=deepseek")
    else:
        failures.append(f"agent_config 解析失败：{detail}")

    graph_status, graph_detail = _check_graph_get_llm_deepseek()
    if graph_status == "PASS":
        checks.append("graph.get_llm(deepseek) 实例化成功")
    elif graph_status == "SKIP":
        record_optional(
            "验证 3：Module 14 - graph.get_llm(deepseek)",
            "SKIP",
            graph_detail,
        )
        checks.append("graph.get_llm(deepseek) 按可选依赖规则跳过")
    else:
        failures.append(f"graph.get_llm(deepseek) 失败：{graph_detail}")

    if failures:
        record(name, "FAIL", "; ".join(failures) + ("; 已通过：" + ", ".join(checks) if checks else ""))
    else:
        record(name, "PASS", "; ".join(checks))


def _post_agent_chat_stream_status() -> int:
    payload = {
        "user_id": "verify_mvp2",
        "session_id": f"verify_{uuid.uuid4().hex}",
        "text": "hello",
        "render_video": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{BASE_URL}/agent/chat/stream",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    try:
        resp = request.urlopen(req, timeout=5)
        try:
            return int(resp.status)
        finally:
            resp.close()
    except error.HTTPError as exc:
        return int(exc.code)


def _check_graph_get_llm_deepseek() -> tuple[str, str]:
    code = """
import importlib.util
import sys

if importlib.util.find_spec("langchain_openai") is None:
    print("langchain_openai not installed")
    raise SystemExit(77)

from app.agent import graph

graph._llm = None
graph._llm_key = None
llm = graph.get_llm()
assert llm.__class__.__name__ == "ChatOpenAI", llm.__class__.__name__
print(llm.__class__.__name__)
"""
    ok, detail, returncode = _run_python_check_with_returncode(
        code,
        env_overrides={
            "AGENT_LLM_PROVIDER": "deepseek",
            "AGENT_LLM_MODEL": "deepseek-chat",
            "AGENT_LLM_API_KEY": "mvp2-dummy-key",
        },
    )
    if returncode == 77:
        return "SKIP", detail.strip() or "langchain_openai not installed"
    if ok:
        return "PASS", detail.strip()
    return "FAIL", detail


def _verify_module15_chat_html() -> None:
    name = "验证 4：Module 15 - chat.html"
    try:
        status, payload = _http_request("GET", "/static/chat.html", timeout=5)
        body = payload.decode("utf-8", errors="replace")
        missing = [needle for needle in ('id="messages"', 'id="canvas"', 'id="video"') if needle not in body]
        if status != 200:
            record(name, "FAIL", f"GET /static/chat.html status={status}")
        elif missing:
            record(name, "FAIL", f"缺少 DOM 元素：{', '.join(missing)}")
        else:
            record(name, "PASS", "GET /static/chat.html=200，包含 id=\"messages\"、id=\"canvas\"、id=\"video\"")
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"{exc}")


def _verify_module11_structure() -> None:
    name = "验证 5：Module 11 - 代码结构验证（不跑 GPU）"
    code = r'''
import inspect
import app.services.musetalk.worker as mw

cls = mw.PersistentMuseTalkWorker
missing = [
    name
    for name in ("prepare_material", "_blend_with_mask", "_blend_frame")
    if not callable(getattr(cls, name, None))
]
assert not missing, f"missing methods: {missing}"

source = inspect.getsource(cls)
assert "self._mask_cache" in source, "_mask_cache not found in class source"
print("PersistentMuseTalkWorker structure ok")
'''
    ok, detail = _run_python_check(code)
    if ok:
        record(name, "PASS", "musetalk_worker import 成功，方法齐全，源码中存在 self._mask_cache")
    else:
        record(name, "FAIL", detail)


def _submit_generate(video_path: Path, text: str) -> str:
    boundary = f"----mvp2-{uuid.uuid4().hex}"
    body = _multipart_body(
        boundary,
        fields={
            "text": text,
            "language": "zh",
            "background_mode": "static",
            "emotion": "neutral",
            "speed": "1.0",
        },
        files={
            "video_file": (
                video_path.name,
                "video/mp4",
                video_path.read_bytes(),
            )
        },
    )
    status, payload = _http_request(
        "POST",
        "/api/v1/generate",
        body=body,
        timeout=10,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    if status not in {200, 202}:
        raise RuntimeError(f"POST /api/v1/generate status={status} body={payload[:500]!r}")
    data = json.loads(payload.decode("utf-8"))
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError(f"响应缺少 task_id：{data}")
    return task_id


def _wait_for_task(task_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        status_code, payload = _http_request("GET", f"/api/v1/generate/{task_id}", timeout=5)
        if status_code != 200:
            raise RuntimeError(f"GET task status={status_code} body={payload[:500]!r}")
        last_status = json.loads(payload.decode("utf-8"))
        state = last_status.get("status")
        if state in {"completed", "failed"}:
            return last_status
        time.sleep(0.5)
    raise TimeoutError(f"任务 {task_id} 在 {timeout:.0f}s 内未结束，最后状态：{last_status}")


def _http_request(
    method: str,
    path: str,
    body: bytes | None = None,
    timeout: float = 5,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    req = request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read()
    except error.HTTPError as exc:
        return int(exc.code), exc.read()


def _multipart_body(
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> bytes:
    chunks: list[bytes] = []
    b = boundary.encode("ascii")
    for name, value in fields.items():
        chunks.extend(
            [
                b"--" + b + b"\r\n",
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, content_type, data) in files.items():
        chunks.extend(
            [
                b"--" + b + b"\r\n",
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                data,
                b"\r\n",
            ]
        )
    chunks.append(b"--" + b + b"--\r\n")
    return b"".join(chunks)


def _ensure_input_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import cv2
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"生成验证视频需要 opencv-python/numpy：{exc}") from exc

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 25.0, (160, 120))
    if not writer.isOpened():
        raise RuntimeError(f"无法创建验证 MP4：{path}")
    try:
        for index in range(16):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            frame[:, :] = (40 + index * 3, 80, 130)
            cv2.rectangle(frame, (55, 28), (105, 88), (180, 170, 150), -1)
            cv2.circle(frame, (72, 52), 4, (20, 20, 20), -1)
            cv2.circle(frame, (88, 52), 4, (20, 20, 20), -1)
            cv2.rectangle(frame, (70, 68), (92, 73), (25, 25, 25), -1)
            cv2.putText(
                frame,
                str(index),
                (8, 112),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (230, 230, 230),
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
    finally:
        writer.release()

    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"验证 MP4 写入失败：{path}")


def _run_python_check(
    code: str,
    env_overrides: dict[str, str] | None = None,
) -> tuple[bool, str]:
    ok, detail, _returncode = _run_python_check_with_returncode(code, env_overrides)
    return ok, detail


def _run_python_check_with_returncode(
    code: str,
    env_overrides: dict[str, str] | None = None,
) -> tuple[bool, str, int]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        [PYTHON_EXE or sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    output = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
    if proc.returncode == 0:
        return True, output, proc.returncode
    return False, output or f"python check failed with returncode={proc.returncode}", proc.returncode


def _select_python() -> str:
    candidates = [
        REPO_ROOT / "venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        proc = subprocess.run(
            [str(candidate), "-c", "import uvicorn, fastapi, cv2, numpy"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return str(candidate)
    return sys.executable


def _print_summary() -> None:
    counts: dict[str, int] = {}
    all_results = [*RESULTS, *OPTIONAL_RESULTS]
    for result in all_results:
        counts[result.status] = counts.get(result.status, 0) + 1
    total = len(RESULTS)
    print("\n汇总：", flush=True)
    for result in RESULTS:
        print(f"- [{result.status}] {result.name}: {result.reason}", flush=True)
    if OPTIONAL_RESULTS:
        print("可选/降级项：", flush=True)
        for result in OPTIONAL_RESULTS:
            print(f"- [{result.status}] {result.name}: {result.reason}", flush=True)
    print(
        f"验证项 {total} 项：PASS={sum(1 for result in RESULTS if result.status == 'PASS')} "
        f"FAIL={sum(1 for result in RESULTS if result.status == 'FAIL')}；"
        f"含可选项总计 {len(all_results)} 项：PASS={counts.get('PASS', 0)} "
        f"FAIL={counts.get('FAIL', 0)} SKIP={counts.get('SKIP', 0)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
