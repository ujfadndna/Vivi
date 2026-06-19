"""Deploy FlashHead integration to cloud server."""
import base64
import os
import sys

import paramiko

HOST = os.environ.get("FUNHPC_HOST", "")
PORT = int(os.environ.get("FUNHPC_PORT", "22"))
USER = os.environ.get("FUNHPC_USER", "root")
PASS = os.environ.get("FUNHPC_PASS", "")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = [
    # MVP-2 core
    ("app/services/flashhead/worker.py",     "/data/Her/app/services/flashhead/worker.py"),
    ("app/services/flashhead/persistent.py", "/data/Her/app/services/flashhead/persistent.py"),
    ("app/services/flashhead/real.py",       "/data/Her/app/services/flashhead/real.py"),
    ("app/config.py",                        "/data/Her/app/config.py"),
    ("app/main.py",                          "/data/Her/app/main.py"),
    ("docs/plan.md",                         "/data/Her/docs/plan.md"),
    # MVP-3 additions
    ("app/services/tts/qwen3.py",            "/data/Her/app/services/tts/qwen3.py"),
    ("app/services/tts/base.py",              "/data/Her/app/services/tts/base.py"),
    ("app/agent/graph.py",                   "/data/Her/app/agent/graph.py"),
    ("app/api/routes/agent.py",              "/data/Her/app/api/routes/agent.py"),
]


def upload(ssh: paramiko.SSHClient, local_rel: str, remote: str) -> None:
    local = os.path.join(PROJECT_ROOT, local_rel)
    with open(local, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode()
    remote_dir = os.path.dirname(remote)
    script = (
        f"import base64,os; "
        f"os.makedirs('{remote_dir}', exist_ok=True); "
        f"open('{remote}','wb').write(base64.b64decode('{b64}'))"
    )
    _, stdout, stderr = ssh.exec_command(f"python3 -c \"{script}\"")
    rc = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    if rc != 0 or err:
        print(f"  FAIL {local_rel}: {err}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK   {local_rel}")


def run_cmd(ssh: paramiko.SSHClient, cmd: str, timeout: int | None = None) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if rc != 0:
        print(f"CMD FAILED (rc={rc}): {cmd}\n{err}", file=sys.stderr)
        sys.exit(1)
    return out


def main() -> None:
    if not HOST:
        print("FUNHPC_HOST is required", file=sys.stderr)
        sys.exit(1)
    if not PASS:
        print("FUNHPC_PASS is required", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASS, timeout=15)
    print(f"Connected to {HOST}:{PORT}")

    print("\n--- Uploading files ---")
    for local_rel, remote in FILES:
        upload(ssh, local_rel, remote)

    print("\n--- Checking Qwen3-TTS model ---")
    result = run_cmd(
        ssh,
        "[ -d /data/Her/models/Qwen3-TTS-1.7B ] "
        "&& ls /data/Her/models/Qwen3-TTS-1.7B 2>&1 | head -5 "
        "|| echo NOT_FOUND",
    )
    print(f"  Qwen3-TTS model: {result[:120]}")

    if "NOT_FOUND" in result:
        print("  Qwen3-TTS model not found, downloading via modelscope...")
        run_cmd(ssh, "/data/miniconda/envs/torch/bin/pip install -q modelscope", timeout=300)
        dl_cmd = (
            "/data/miniconda/envs/torch/bin/python -c \""
            "from modelscope import snapshot_download; "
            "snapshot_download('Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice', "
            "local_dir='/data/Her/models/Qwen3-TTS-1.7B')"
            "\""
        )
        run_cmd(ssh, dl_cmd, timeout=1800)
        print("  Qwen3-TTS model downloaded.")

    print("\n--- Installing qwen-tts ---")
    check = run_cmd(ssh, "/data/miniconda/envs/torch/bin/pip show qwen-tts 2>&1 || echo NOT_INSTALLED")
    if "NOT_INSTALLED" in check or "not found" in check.lower():
        run_cmd(ssh, "/data/miniconda/envs/torch/bin/pip install -q qwen-tts", timeout=300)
        print("  qwen-tts installed.")
    else:
        print("  qwen-tts already installed.")

    print("\n--- Checking .env TTS_BACKEND ---")
    env_val = run_cmd(ssh, "grep TTS_BACKEND /data/Her/.env 2>/dev/null || echo NOT_SET")
    print(f"  TTS_BACKEND: {env_val}")
    if "qwen3" not in env_val:
        print("  WARNING: TTS_BACKEND is not set to qwen3. Run manually:")
        print("    echo 'TTS_BACKEND=qwen3' >> /data/Her/.env")

    print("\n--- Checking FlashHead model weights ---")
    result = run_cmd(ssh, "ls /data/Her/models/SoulX-FlashHead-1_3B 2>&1 | head -5 || echo NOT_FOUND")
    print(f"  FlashHead weights: {result[:120]}")

    result = run_cmd(ssh, "ls /data/Her/models/wav2vec2-base-960h 2>&1 | head -3 || echo NOT_FOUND")
    print(f"  wav2vec2 weights: {result[:80]}")

    print("\n--- Checking disk space ---")
    disk = run_cmd(ssh, "df -h /data | tail -1")
    print(f"  {disk}")

    print("\n--- Restarting server ---")
    run_cmd(ssh, "bash /data/Her/restart.sh")
    import time; time.sleep(3)

    print("\n--- Health check ---")
    health = run_cmd(ssh, "curl -sf http://localhost:8000/health || echo FAIL")
    print(f"  /health: {health}")

    ssh.close()
    print("\nDeploy complete.")


if __name__ == "__main__":
    main()
