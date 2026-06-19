"""分句流水线本地测试脚本。

通过 SSH tunnel (localhost:8000) 调用云端服务，模拟 Agent 层的分句并发渲染。
运行：python scripts/test_pipeline_stream.py
"""
import asyncio
import os
import sys
import time

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")
from app.agent.render_scheduler import render_response_stream, split_sentences

TEXT = "我理解你的感受。压力大的时候要学会放松。试试深呼吸，会好很多的。"


async def main():
    print(f"输入文本：{TEXT}")
    print(f"分句结果：{split_sentences(TEXT)}")
    print(f"共 {len(split_sentences(TEXT))} 句，开始并发渲染...\n")

    t0 = time.time()
    first_time = None
    n = 0

    async for seg in render_response_stream(TEXT, "neutral"):
        dt = time.time() - t0
        if first_time is None:
            first_time = dt
        n += 1
        status_icon = "[OK]" if seg.status == "completed" else "[FAIL]"
        print(f"  {status_icon} [{dt:.1f}s] 第{n}句: \"{seg.sentence}\"")
        if seg.video_url:
            print(f"       视频: http://localhost:8000{seg.video_url}")
        print()

    total = time.time() - t0
    print("─" * 50)
    print(f"首句就绪: {first_time:.1f}s")
    print(f"全部完成: {total:.1f}s")
    print(f"总句数:   {n}")

    if first_time and total > 0:
        串行预估 = total / n * n  # 如果串行，总时间不变
        print(f"\n流水线收益: 用户在 {first_time:.0f}s 就能看到第一段视频")
        print(f"           （若串行等待全部完成需 {total:.0f}s）")


if __name__ == "__main__":
    asyncio.run(main())
