#!/usr/bin/env python3
"""Use Paramiko to run a FlashHead end-to-end test on the cloud server.

Example:
    python scripts/flashhead_cloud_e2e.py
    # or override credentials via env:
    FUNHPC_HOST=... FUNHPC_PORT=... FUNHPC_USER=root FUNHPC_PASS=... python scripts/flashhead_cloud_e2e.py
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import paramiko

HOST = os.environ.get("FUNHPC_HOST", "")
PORT = int(os.environ.get("FUNHPC_PORT", "22"))
USER = os.environ.get("FUNHPC_USER", "root")
PASS = os.environ.get("FUNHPC_PASS", "")

REMOTE_ROOT = "/data/Her"
REMOTE_PY = "/data/miniconda/envs/torch/bin/python"
REMOTE_ENV = f"{REMOTE_ROOT}/.env"

DEPLOY_FILES = [
    ("app/services/flashhead/worker.py", f"{REMOTE_ROOT}/app/services/flashhead/worker.py"),
    ("app/services/flashhead/persistent.py", f"{REMOTE_ROOT}/app/services/flashhead/persistent.py"),
    ("app/services/flashhead/real.py", f"{REMOTE_ROOT}/app/services/flashhead/real.py"),
    ("app/config.py", f"{REMOTE_ROOT}/app/config.py"),
    ("app/main.py", f"{REMOTE_ROOT}/app/main.py"),
    ("app/services/musetalk/service.py", f"{REMOTE_ROOT}/app/services/musetalk/service.py"),
]


def run_cmd(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str, str]:
    print(f"  $ {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return rc, out, err


def upload_file(ssh: paramiko.SSHClient, local_rel: str, remote: str) -> None:
    local = Path(__file__).resolve().parents[1] / local_rel
    data = local.read_bytes()
    b64 = base64.b64encode(data).decode()
    rdir = os.path.dirname(remote)
    script = (
        f"import base64,os; "
        f"os.makedirs('{rdir}', exist_ok=True); "
        f"open('{remote}','wb').write(base64.b64decode('{b64}'))"
    )
    rc, _, err = run_cmd(ssh, f"python3 -c \"{script}\"")
    if rc != 0:
        print(f"  FAIL upload {local_rel}: {err}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK upload {local_rel}")


def ensure_musetalk_backend(ssh: paramiko.SSHClient) -> bool:
    """Ensure .env contains MUSETALK_BACKEND=local; return True if changed."""
    check = (
        f"import re; p='{REMOTE_ENV}'; s=open(p).read(); "
        f"print('local' if re.search(r'^MUSETALK_BACKEND\s*=\s*local', s, re.M) else 'missing')"
    )
    rc, out, _ = run_cmd(ssh, f"python3 -c \"{check}\"")
    if out.strip() == "local":
        print("  .env already has MUSETALK_BACKEND=local")
        return False

    patch = (
        f"p='{REMOTE_ENV}'; s=open(p).read(); "
        f"lines=[l for l in s.splitlines() if not l.startswith('MUSETALK_BACKEND=')]; "
        f"lines.append('MUSETALK_BACKEND=local'); "
        f"open(p,'w').write('\\n'.join(lines)+'\\n')"
    )
    rc, _, err = run_cmd(ssh, f"python3 -c \"{patch}\"")
    if rc != 0:
        print(f"  FAIL patch .env: {err}", file=sys.stderr)
        sys.exit(1)
    print("  OK patched .env -> MUSETALK_BACKEND=local")
    return True


def restart_server(ssh: paramiko.SSHClient) -> None:
    print("\n--- Restarting server ---")
    rc, out, err = run_cmd(ssh, f"bash {REMOTE_ROOT}/restart.sh", timeout=30)
    print(out)
    if err:
        print(err, file=sys.stderr)

    print("  waiting for /health ...")
    deadline = time.time() + 60
    while time.time() < deadline:
        rc, out, _ = run_cmd(ssh, "curl -sf http://localhost:8000/health || echo FAIL", timeout=10)
        if out.strip() == '{"status":"ok"}':
            print("  OK /health is up")
            return
        time.sleep(2)
    print("  FAIL server did not come up", file=sys.stderr)
    sys.exit(1)


def upload_remote_e2e_script(ssh: paramiko.SSHClient) -> str:
    remote_path = f"{REMOTE_ROOT}/scripts/flashhead_e2e_remote.py"
    upload_file(ssh, "scripts/flashhead_e2e_remote.py", remote_path)
    return remote_path


def run_remote_e2e(
    ssh: paramiko.SSHClient,
    remote_script: str,
    text: str,
    timeout: int,
) -> dict[str, Any]:
    env = f"E2E_TEXT={text!r} E2E_TIMEOUT={timeout}"
    cmd = (
        f"cd {REMOTE_ROOT} && {env} {REMOTE_PY} -u {remote_script}"
    )
    print(f"\n--- Running remote e2e (timeout={timeout}s) ---")
    rc, out, err = run_cmd(ssh, cmd, timeout=timeout + 60)

    # Print streamed remote logs
    for line in (out + "\n" + err).splitlines():
        if line.strip():
            print(f"  {line.rstrip()}")

    result: dict[str, Any] | None = None
    for line in out.splitlines():
        if line.startswith("E2E_RESULT:"):
            try:
                result = json.loads(line[len("E2E_RESULT:") :])
            except json.JSONDecodeError as exc:
                print(f"  WARN failed to parse result JSON: {exc}", file=sys.stderr)
    if result is None:
        result = {"status": "unknown", "rc": rc, "raw_stdout": out, "raw_stderr": err}
    return result


def download_video(
    ssh: paramiko.SSHClient, remote_path: str, local_path: Path
) -> None:
    print(f"\n--- Downloading video to {local_path} ---")
    sftp = ssh.open_sftp()
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        sftp.get(remote_path, str(local_path))
        print(f"  OK {local_path.stat().st_size} bytes")
    finally:
        sftp.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FlashHead cloud e2e via Paramiko")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--user", default=USER)
    parser.add_argument("--password", default=PASS)
    parser.add_argument("--no-deploy", action="store_true", help="skip uploading app code")
    parser.add_argument("--no-restart", action="store_true", help="skip .env patch + restart")
    parser.add_argument("--text", default="你好，这是 FlashHead 云端端到端测试。", help="text to synthesize")
    parser.add_argument("--timeout", type=int, default=1200, help="max seconds to wait for generation")
    parser.add_argument("--download", type=Path, default=Path("workspace/outputs/flashhead_cloud_e2e.mp4"),
                        help="local path to save the output video")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.host:
        print("Host 为空，请设置 --host 或 FUNHPC_HOST 环境变量", file=sys.stderr)
        return 1
    if not args.password:
        print("Pass 为空，请设置 --password 或 FUNHPC_PASS 环境变量", file=sys.stderr)
        return 1

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {args.host}:{args.port} ...")
    ssh.connect(args.host, args.port, args.user, args.password, timeout=15)
    print("Connected.")

    try:
        if not args.no_deploy:
            print("\n--- Deploying latest FlashHead app files ---")
            for local_rel, remote in DEPLOY_FILES:
                upload_file(ssh, local_rel, remote)

        if not args.no_restart:
            env_changed = ensure_musetalk_backend(ssh)
            # Always restart after deploy or env change
            restart_server(ssh)
        else:
            print("\n--- Skipping .env patch / restart ---")

        remote_script = upload_remote_e2e_script(ssh)
        result = run_remote_e2e(ssh, remote_script, args.text, args.timeout)

        if result.get("status") == "completed":
            remote_video = result.get("video_local")
            if remote_video and args.download:
                download_video(ssh, remote_video, args.download)
            print("\n=== FlashHead cloud e2e PASSED ===")
            print(f"  task_id: {result.get('task_id')}")
            print(f"  video_url: {result.get('video_url')}")
            print(f"  video_bytes: {result.get('video_bytes')}")
            print(f"  progress: {result.get('progress')}")
            return 0
        else:
            print("\n=== FlashHead cloud e2e FAILED ===", file=sys.stderr)
            print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
    finally:
        ssh.close()


if __name__ == "__main__":
    raise SystemExit(main())
