"""Setup FlashHead on cloud: clone repo, update .env, install deps."""
import base64
import os
import paramiko
import time

HOST = os.environ.get("FUNHPC_HOST", "")
PORT = int(os.environ.get("FUNHPC_PORT", "22"))
USER = os.environ.get("FUNHPC_USER", "root")
PASS = os.environ.get("FUNHPC_PASS", "")
PY = "/data/miniconda/envs/torch/bin/python"
PIP = "/data/miniconda/envs/torch/bin/pip"

ENV_PATCH = (
    "\n# -- FlashHead --\n"
    "FLASHHEAD_REPO=/data/Her/third_party/SoulX-FlashHead\n"
    "FLASHHEAD_CKPT_DIR=/data/Her/models/SoulX-FlashHead-1_3B\n"
    "FLASHHEAD_WAV2VEC_DIR=/data/Her/models/wav2vec2-base-960h\n"
    "FLASHHEAD_MODEL_TYPE=lite\n"
    "FLASHHEAD_STREAM_FRAMES=1\n"
    "DEFAULT_AVATAR_IMAGE=/data/Her/workspace/avatar/default.png\n"
)

STRIP_PREFIXES = ["FLASHHEAD_", "DEFAULT_AVATAR_IMAGE"]


def run(ssh, cmd, timeout=120):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    out.channel.recv_exit_status()
    return out.read().decode().strip(), err.read().decode().strip()


def upload_script(ssh, local_path, remote_path):
    data = open(local_path, "rb").read()
    b64 = base64.b64encode(data).decode()
    rdir = os.path.dirname(remote_path)
    cmd = (
        f"python3 -c \""
        f"import base64,os; os.makedirs('{rdir}',exist_ok=True); "
        f"open('{remote_path}','wb').write(base64.b64decode('{b64}'))\""
    )
    _, out, err = ssh.exec_command(cmd)
    out.channel.recv_exit_status()


def main():
    if not HOST:
        raise RuntimeError("FUNHPC_HOST is required")
    if not PASS:
        raise RuntimeError("FUNHPC_PASS is required")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, PORT, USER, PASS, timeout=15)
    print(f"Connected to {HOST}:{PORT}")

    # 1. Clone repo
    print("\n=== Clone SoulX-FlashHead ===")
    o, e = run(ssh, "ls /data/Her/third_party/SoulX-FlashHead/flash_head 2>/dev/null | head -3 || echo NOT_FOUND")
    if "NOT_FOUND" in o:
        mirrors = [
            "https://ghproxy.cn/https://github.com/Soul-AILab/SoulX-FlashHead.git",
            "https://mirror.ghproxy.com/https://github.com/Soul-AILab/SoulX-FlashHead.git",
        ]
        for mirror in mirrors:
            o, e = run(ssh, f"cd /data/Her/third_party && git clone {mirror} SoulX-FlashHead 2>&1 | tail -4", timeout=300)
            print(o or e)
            if "done" in o.lower() or "already exists" in o.lower():
                break
    else:
        print("already cloned:", o[:80])

    # 2. Update .env
    print("\n=== Update .env ===")
    o, _ = run(ssh, "cat /data/Her/.env")
    lines = [l for l in o.splitlines() if not any(l.startswith(p) for p in STRIP_PREFIXES)]
    new_env = "\n".join(lines) + ENV_PATCH
    b64 = base64.b64encode(new_env.encode()).decode()
    cmd = f"python3 -c \"import base64; open('/data/Her/.env','wb').write(base64.b64decode('{b64}'))\""
    run(ssh, cmd)
    o, _ = run(ssh, "grep FLASHHEAD /data/Her/.env")
    print(o)

    # 3. Install FlashHead as package
    print("\n=== pip install FlashHead repo ===")
    o, e = run(ssh, f"cd /data/Her/third_party/SoulX-FlashHead && {PIP} install -e . --quiet 2>&1 | tail -5", timeout=120)
    print(o or e)

    # 4. Install missing deps (no flash_attn - needs compilation, skip for now)
    print("\n=== pip install deps ===")
    pkgs = "xfuser>=0.4.3 mediapipe==0.10.9 pyloudnorm loguru decord"
    o, e = run(ssh, f"{PIP} install {pkgs} --quiet 2>&1 | tail -5", timeout=300)
    print(o or e)

    # 5. Check flash_attn - try prebuilt wheel
    print("\n=== flash_attn check ===")
    o, _ = run(ssh, f"{PY} -c 'import flash_attn; print(flash_attn.__version__)' 2>&1")
    if "version" not in o.lower():
        # Try pip install prebuilt
        torch_ver = run(ssh, f"{PY} -c 'import torch; print(torch.__version__)'")[0]
        cuda_ver = run(ssh, "nvcc --version 2>/dev/null | grep release | awk '{print $6}' | tr -d ','")[0] or "12.1"
        print(f"torch={torch_ver}, cuda={cuda_ver} — trying prebuilt flash_attn wheel")
        o, e = run(ssh, f"{PIP} install flash_attn==2.8.0.post2 --no-build-isolation --quiet 2>&1 | tail -8", timeout=600)
        print(o or e)
    else:
        print(f"flash_attn already installed: {o}")

    # 6. Quick import test
    print("\n=== Import test ===")
    o, e = run(ssh, f"{PY} -c \"import sys; sys.path.insert(0,'/data/Her/third_party/SoulX-FlashHead'); from flash_head.inference import get_pipeline; print('flash_head import OK')\" 2>&1")
    print(o or e)

    # 7. Restart server
    print("\n=== Restart server ===")
    o, _ = run(ssh, "bash /data/Her/restart.sh 2>&1 | tail -3")
    print(o)
    time.sleep(6)
    o, _ = run(ssh, "curl -sf http://localhost:8000/health || echo FAIL")
    print(f"/health: {o}")

    ssh.close()
    print("\nSetup complete.")


if __name__ == "__main__":
    main()
