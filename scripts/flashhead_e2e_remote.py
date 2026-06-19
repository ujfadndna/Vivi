#!/usr/bin/env python3
"""Remote helper: run FlashHead end-to-end test against localhost:8000."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"


def post_form(path: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def log_event(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> int:
    text = os.environ.get("E2E_TEXT", "你好，这是 FlashHead 云端端到端测试。")
    poll_interval = 5
    timeout = int(os.environ.get("E2E_TIMEOUT", "1200"))
    output_dir = Path("/data/Her/workspace/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[e2e] text={text!r} timeout={timeout}s", file=sys.stderr, flush=True)

    # 1. Submit
    print("[e2e] POST /api/v1/generate-text-only", file=sys.stderr, flush=True)
    try:
        resp = post_form(
            "/api/v1/generate-text-only",
            {"text": text, "language": "zh"},
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        log_event({"event": "submit_failed", "status": exc.code, "body": body})
        return 1

    task_id = resp.get("task_id")
    if not task_id:
        log_event({"event": "submit_failed", "response": resp})
        return 1

    log_event({"event": "submitted", "task_id": task_id})

    # 2. Poll
    deadline = time.time() + timeout
    last_status: dict | None = None
    while time.time() < deadline:
        time.sleep(poll_interval)
        try:
            d = get(f"/api/v1/generate/{task_id}")
        except Exception as exc:  # noqa: BLE001
            log_event({"event": "poll_error", "task_id": task_id, "error": str(exc)})
            continue

        last_status = d
        status = d.get("status")
        progress = d.get("progress") or {}
        if status in ("completed", "failed") or int(time.time()) % 30 < poll_interval:
            log_event(
                {
                    "event": "poll",
                    "task_id": task_id,
                    "status": status,
                    "progress": progress,
                    "elapsed": round(time.time() - (deadline - timeout), 1),
                }
            )

        if status == "completed":
            video_url = d.get("video_url") or f"/outputs/{task_id}.mp4"
            full_url = BASE + video_url if video_url.startswith("/") else video_url
            try:
                with urllib.request.urlopen(full_url, timeout=60) as vr:
                    video_bytes = vr.read()
            except Exception as exc:  # noqa: BLE001
                log_event(
                    {
                        "event": "completed",
                        "task_id": task_id,
                        "video_url": video_url,
                        "error": f"download failed: {exc}",
                    }
                )
                return 1

            local_path = output_dir / f"flashhead_e2e_{task_id}.mp4"
            local_path.write_bytes(video_bytes)

            # collect relevant log tail
            log_lines: list[str] = []
            try:
                log = Path("/data/Her/server.log").read_text(errors="replace").splitlines()
                keywords = ("[TIMING]", "[FTIMING]", "[FlashHead]", "[WARMUP]")
                log_lines = [l for l in log if any(k in l for k in keywords)][-40:]
            except Exception:  # noqa: BLE001
                pass

            summary = {
                "event": "completed",
                "task_id": task_id,
                "status": "completed",
                "video_url": video_url,
                "video_local": str(local_path),
                "video_bytes": len(video_bytes),
                "progress": progress,
                "log_tail": log_lines,
            }
            print("E2E_RESULT:" + json.dumps(summary, ensure_ascii=False), flush=True)
            return 0

        if status == "failed":
            summary = {
                "event": "failed",
                "task_id": task_id,
                "status": "failed",
                "error": d.get("error"),
                "progress": progress,
            }
            print("E2E_RESULT:" + json.dumps(summary, ensure_ascii=False), flush=True)
            return 1

    summary = {
        "event": "timeout",
        "task_id": task_id,
        "status": "timeout",
        "last_status": last_status,
    }
    print("E2E_RESULT:" + json.dumps(summary, ensure_ascii=False), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
