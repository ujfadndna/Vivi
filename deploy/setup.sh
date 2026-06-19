#!/bin/bash
# 云端初始化脚本 - 在 /data/Her 目录下运行
# 用法: bash deploy/setup.sh
set -e

echo "=== [1/6] 安装系统依赖 ==="
apt-get update -qq
apt-get install -y git tmux redis-server ffmpeg

echo "=== [2/6] 安装 Python 依赖 ==="
pip install -q -r requirements.txt
pip install -q -r requirements-agent.txt

echo "=== [3/6] 安装 IndexTTS2 依赖 ==="
pip install -q modelscope huggingface_hub

echo "=== [4/6] 下载 IndexTTS2 权重 (modelscope) ==="
python - << 'PYEOF'
import os
os.environ.setdefault("MODELSCOPE_CACHE", "/root/.cache/modelscope")
from modelscope import snapshot_download
print("Downloading IndexTTS-2 weights...")
snapshot_download(
    "IndexTeam/IndexTTS-2",
    cache_dir="/root/.cache/modelscope/hub/models"
)
print("Done.")
PYEOF

echo "=== [5/6] 克隆 IndexTTS2 源码 ==="
if [ ! -d "/root/index-tts-main" ]; then
    git clone https://github.com/index-tts/index-tts /root/index-tts-main
else
    echo "  已存在，跳过"
fi

echo "=== [6/6] 创建工作目录 ==="
mkdir -p workspace/{audio,videos,outputs,processing,avatar}
mkdir -p workspace/agent/chroma
mkdir -p workspace/uploads

echo ""
echo "=== Setup 完成 ==="
echo "下一步: 复制 deploy/.env.cloud 为 .env 并填写 ANTHROPIC_API_KEY"
echo "然后运行: tmux new -s her && uvicorn app.main:app --host 0.0.0.0 --port 8000"
