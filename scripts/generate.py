"""端到端 CLI：无需起服务，直接跑完整条链路生成视频。

用法：
    python scripts/generate.py --video input.mp4 --text "你好，我是数字人" \
        --language zh --background static --output output.mp4
"""
from __future__ import annotations

import os
# Disable system proxy for all requests — local cache hits don't need network
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
# Instruct huggingface_hub to use local cache only
os.environ.setdefault("HUGGINGFACE_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HOME", "D:/Her/checkpoints/hf_cache")
# Add bundled ffmpeg to PATH
try:
    import imageio_ffmpeg as _iio_ffmpeg
    import pathlib as _pl
    _ffmpeg_dir = str(_pl.Path(_iio_ffmpeg.get_ffmpeg_exe()).parent)
    os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
except ImportError:
    pass

import argparse
import shutil
import sys
from pathlib import Path

# 允许 `python scripts/generate.py` 直接运行（把项目根加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import GenerateRequest  # noqa: E402
from app.storage import new_id  # noqa: E402
from app.tasks.pipeline import run_generation  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="2D 数字人端到端生成")
    p.add_argument("--video", required=True, help="人物视频路径 (mp4/mov/avi)")
    p.add_argument("--text", required=True, help="要说的文本")
    p.add_argument("--language", default="zh", help="zh | en | ja | ko")
    p.add_argument(
        "--background", default="static",
        choices=["static", "dynamic_video", "generated"],
    )
    p.add_argument("--emotion", default="neutral")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--speaker", default=None, help="参考音频路径（声音克隆，IndexTTS2 使用）")
    p.add_argument("--output", default="output.mp4", help="最终视频拷贝到此路径")
    args = p.parse_args()

    if not Path(args.video).exists():
        p.error(f"视频不存在：{args.video}")

    task_id = new_id("gen")
    req = GenerateRequest(
        text=args.text,
        language=args.language,
        background_mode=args.background,
        emotion=args.emotion,
        speed=args.speed,
        speaker_id=args.speaker,
    )

    print(f"[{task_id}] 开始生成 …")
    final_path = run_generation(task_id, args.video, req)
    shutil.copyfile(final_path, args.output)
    print(f"[{task_id}] 完成 → {args.output}")


if __name__ == "__main__":
    main()
