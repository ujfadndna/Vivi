#!/bin/bash
# 生成静默头像视频，用于句间停顿时循环播放
ffmpeg -y -i /data/Her/workspace/avatar/default.mp4 \
  -an \
  -c:v copy \
  -t 10 \
  /data/Her/app/static/avatar_silent.mp4
echo "Done: /data/Her/app/static/avatar_silent.mp4"
