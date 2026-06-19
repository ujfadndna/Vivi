#!/bin/bash
set -e
PYTHON=/data/miniconda/envs/torch/bin/python
PIP=/data/miniconda/envs/torch/bin/pip

echo '[1/6] apt packages'
apt-get update -qq && apt-get install -y ffmpeg git wget 2>&1 | tail -3

echo '[2/6] torch already in conda env]'
$PYTHON -c 'import torch; print("torch", torch.__version__, "cuda:", torch.cuda.is_available())'

echo '[3/6] pip requirements (conda torch env)'
cd /data/Her
$PIP install -r requirements.txt 2>&1 | tail -3
$PIP install -r requirements-agent.txt 2>&1 | tail -3
$PIP install -r requirements-tts-indextts.txt 2>&1 | tail -3
$PIP install -r requirements-musetalk.txt 2>&1 | tail -3
$PIP install -r requirements-segment.txt 2>&1 | tail -3

echo '[4/6] clone & install index-tts'
if [ ! -d /data/index-tts-main ]; then
  git clone https://github.com/index-tts/index-tts /data/index-tts-main 2>&1 | tail -3
else
  echo 'already cloned'
fi
$PIP install -e /data/index-tts-main 2>&1 | tail -3

echo '[5/6] download IndexTTS2 weights (modelscope)'
$PIP install modelscope 2>&1 | tail -2
mkdir -p /data/modelscope_cache
$PYTHON - <<'PYEOF'
import os
os.environ['MODELSCOPE_CACHE'] = '/data/modelscope_cache'
from modelscope import snapshot_download
snapshot_download('IndexTeam/IndexTTS-2', cache_dir='/data/modelscope_cache/hub/models')
print('IndexTTS2 weights done')
PYEOF

echo '[6/6] download RVM weight'
mkdir -p /data/Her/models/rvm
if [ ! -f /data/Her/models/rvm/rvm_mobilenetv3.pth ]; then
  wget -q --show-progress -O /data/Her/models/rvm/rvm_mobilenetv3.pth \
    https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3.pth \
    && echo 'RVM done' || echo 'RVM download failed'
else
  echo 'RVM already exists'
fi

echo '=== SETUP COMPLETE ==='
