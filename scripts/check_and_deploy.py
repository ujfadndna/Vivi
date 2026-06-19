"""Check FlashHead download progress; upload code and restart when done."""
import base64
import os
import sys
import time
from pathlib import Path

import paramiko

HOST = os.environ.get("FUNHPC_HOST", "")
PORT = int(os.environ.get("FUNHPC_PORT", "22"))
USER = os.environ.get("FUNHPC_USER", "root")
PASS = os.environ.get("FUNHPC_PASS", "")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ("app/services/flashhead/worker.py",     "/data/Her/app/services/flashhead/worker.py"),
    ("app/services/flashhead/persistent.py", "/data/Her/app/services/flashhead/persistent.py"),
    ("app/services/flashhead/real.py",       "/data/Her/app/services/flashhead/real.py"),
    ("app/config.py",                        "/data/Her/app/config.py"),
    ("app/main.py",                          "/data/Her/app/main.py"),
    ("app/services/musetalk/service.py",     "/data/Her/app/services/musetalk/service.py"),
    ("requirements-flashhead.txt",           "/data/Her/requirements-flashhead.txt"),
    ("docs/plan.md",                         "/data/Her/docs/plan.md"),
]


def connect():
    if not HOST:
        raise RuntimeError("FUNHPC_HOST is required")
    if not PASS:
        raise RuntimeError("FUNHPC_PASS is required")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASS, timeout=15)
    return ssh


def run(ssh, cmd):
    _, out, err = ssh.exec_command(cmd)
    out.channel.recv_exit_status()
    return out.read().decode().strip()


def upload(ssh, local_rel, remote):
    local = PROJECT_ROOT / local_rel
    data = local.read_bytes()
    b64 = base64.b64encode(data).decode()
    remote_dir = os.path.dirname(remote)
    script = (
        f"import base64,os; os.makedirs('{remote_dir}', exist_ok=True); "
        f"open('{remote}','wb').write(base64.b64decode('{b64}'))"
    )
    _, out, err = ssh.exec_command(f"python3 -c \"{script}\"")
    rc = out.channel.recv_exit_status()
    if rc != 0:
        print(f"  FAIL {local_rel}: {err.read().decode().strip()}", file=sys.stderr)
        sys.exit(1)
    print(f"  OK   {local_rel}")


def check_progress(ssh):
    procs = run(ssh, "pgrep -f huggingface_hub | grep -v grep || true")
    fh_tail = run(ssh, "tail -2 /data/Her/logs/download_flashhead.log 2>/dev/null || echo '(no log)'")
    fh_size = run(ssh, "du -sh /data/Her/models/SoulX-FlashHead-1_3B 2>/dev/null | cut -f1 || echo '0'")
    fh_files = run(ssh, "find /data/Her/models/SoulX-FlashHead-1_3B -type f 2>/dev/null | wc -l")
    w2v_size = run(ssh, "du -sh /data/Her/models/wav2vec2-base-960h 2>/dev/null | cut -f1 || echo '0'")

    print(f"FlashHead: {fh_size}, {fh_files} files")
    print(f"wav2vec2:  {w2v_size}")
    print(f"log tail:  {fh_tail.splitlines()[-1] if fh_tail else ''}")
    still_running = bool(procs.strip())
    print(f"processes: {'still downloading...' if still_running else 'DONE'}")
    return not still_running


def deploy(ssh):
    print("\n--- Uploading code ---")
    for local_rel, remote in FILES:
        upload(ssh, local_rel, remote)

    print("\n--- Model sizes ---")
    for model, path in [("FlashHead", "/data/Her/models/SoulX-FlashHead-1_3B"),
                        ("wav2vec2",  "/data/Her/models/wav2vec2-base-960h")]:
        size = run(ssh, f"du -sh {path} 2>/dev/null | cut -f1")
        files = run(ssh, f"find {path} -type f 2>/dev/null | wc -l")
        print(f"  {model}: {size}, {files} files")

    print("\n--- Restarting server ---")
    out = run(ssh, "bash /data/Her/restart.sh 2>&1")
    print(out[:300] if out else "(no output)")

    time.sleep(6)
    health = run(ssh, "curl -sf http://localhost:8000/health || echo FAIL")
    print(f"\n/health: {health}")


def main():
    ssh = connect()
    print(f"Connected to {HOST}:{PORT}\n")

    done = check_progress(ssh)
    if done:
        deploy(ssh)
    else:
        print("\nDownload still in progress. Run this script again when done.")

    ssh.close()


if __name__ == "__main__":
    main()
