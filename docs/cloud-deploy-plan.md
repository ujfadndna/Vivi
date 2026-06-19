# 云端部署与测试计划

## 1. 环境概览

| 项 | 值 |
|---|---|
| 平台 | 任意可 SSH 登录的 GPU 云主机 |
| GPU | 建议 NVIDIA RTX 3090/4090 或同级 24GB VRAM |
| CUDA | 12.1（torch 2.5.1+cu121） |
| Python | 3.10.12（conda env: torch） |
| OS | Ubuntu 22.04 |
| 数据盘 | 建议 `/data` 或同等持久化数据盘 |
| 项目路径 | /data/Her |
| SSH | `ssh -p <port> <user>@<host>` |
| 费用 | 按所选云平台计费 |

---

## 2. 当前部署状态 ✅ 端到端验证通过（2026-06-13）

| 组件 | 状态 | 备注 |
|---|---|---|
| FastAPI 服务 | ✅ 运行中 | uvicorn, port 8000 |
| IndexTTS2 推理 | ✅ 已验证 | 热启动推理 3~5s；依赖模型已全部本地化 |
| indextts 包 | ✅ 已安装 | pip install -e /data/index-tts-main |
| MuseTalk Worker | ✅ 已验证 | 常驻子进程热推理，542帧约3分钟 |
| MuseTalk 权重 | ✅ 已部署 | musetalkV15/unet.pth, musetalk.json |
| mmcv/mmpose/mmdet | ✅ 已安装 | mmcv 2.1.0, mmdet 3.3.0, mmpose 1.3.1 |
| RVM 分割 | ✅ 已验证 | models/rvm/rvm_mobilenetv3.pth, 端到端通过 |
| 视频合成 | ✅ 已验证 | 输出 MP4 可正常播放（802KB） |
| Demo UI | ✅ 已部署 | /static/demo.html |
| /health | ✅ 返回 200 | `{"status":"ok"}` |
| 端到端推理 | ✅ **通过** | 首句 25.2s；短句 ~23s；长句（9s）~96s |
| 性能优化 | ✅ 已部署 | 截帧+Ingest缓存+Worker缓存+pipe+异步Runner |

---

## 3. 关键路径说明

### Python 环境

云端使用 conda `torch` 环境，所有命令需用：
```bash
/data/miniconda/envs/torch/bin/python
/data/miniconda/envs/torch/bin/pip
```

### MuseTalk sys.path 修复

Worker 子进程需要精确控制 `sys.path` 顺序：
- project_root (`/data/Her`) — 确保 `app.config` 正确
- repo_dir (`/data/Her/third_party/MuseTalk`) — 确保 `musetalk.utils` 可 import
- 已在 `musetalk_worker.py` 中通过 sys.path.clear() + 精确重建实现

### GitHub 不可达

云端无法访问 github.com，所有需要 GitHub 的操作通过本机 scp 传输：
- index-tts 源码：本机打包 → scp → pip install -e
- RVM 权重：本机 scp
- s3fd face detection 模型：本机 ~/.cache/torch/hub 传过去

### HuggingFace 不可达（已解决）

IndexTTS2 依赖多个 HF 模型，云端通过 hf-mirror.com 或本机 scp 部署到本地：

| 模型 | 本地路径 | 来源 |
|---|---|---|
| facebook/w2v-bert-2.0 | /data/huggingface_cache/facebook/w2v-bert-2.0 | hf-mirror.com |
| nvidia/bigvgan_v2_22khz_80band_256x | /data/huggingface_cache/nvidia/bigvgan_v2_22khz_80band_256x | 本机 scp |
| amphion/MaskGCT semantic_codec | /data/huggingface_cache/amphion/MaskGCT/semantic_codec/ | 本机 scp |
| funasr/campplus | /data/huggingface_cache/funasr/campplus/ | 本机 scp |

对应代码修改：
- `/data/index-tts-main/indextts/infer_v2.py` — 3处 from_pretrained 路径改为本地
- `/data/index-tts-main/indextts/utils/maskgct_utils.py` — Wav2Vec2BertModel 路径改为本地
- `app/main.py` — 启动时设置 `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` / `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`

---

## 4. 启动命令

```bash
# tmux 会话
tmux new -s her
cd /data/Her
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /data/miniconda/envs/torch/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# Ctrl+B D 挂到后台
```

---

## 5. 访问方式

云端防火墙可能未开放 8000 端口，通过 SSH 隧道访问：

```bash
# 本机 PowerShell（后台运行）
ssh -f -N -L 8000:localhost:8000 -p <port> <user>@<host>
```

然后浏览器访问：`http://localhost:8000/static/demo.html`

---

## 6. 验证测试清单

| 测试项 | 命令 | 成功标准 | 状态 |
|---|---|---|---|
| 服务健康检查 | `curl http://localhost:8000/health` | 返回 `{"status":"ok"}` | ✅ |
| Demo UI | 浏览器访问 /static/demo.html | 页面正常渲染 | ✅ |
| IndexTTS2 推理 | generate-text-only + speaker_id | 生成 wav，RTF < 2 | ✅ 热启动 3~5s |
| MuseTalk Worker 热启动 | 第二次推理 | 无模型重载 | ✅ |
| RVM 端到端 | 提交任务（SEGMENT_BACKEND=local） | segmentation: completed | ✅ |
| 视频合成 | 检查输出 MP4 | 可正常播放 | ✅ 802KB |
| 端到端全链路 | generate-text-only 完整流程 | 输出可播放视频 | ✅ 3次连续成功 |

### 实测性能（RTX 4090，2026-06-13，优化后）

| 指标 | 优化前 | 优化后 | MVP-1 目标 |
|---|---|---|---|
| IndexTTS2 模型加载 | 34s（首次） | 34s（首次） | — |
| IndexTTS2 推理（热） | 3~5s | 2~7s | — |
| MuseTalk Worker 推理（短句 51 帧） | — | **14.5s** | — |
| MuseTalk Worker 推理（长句 265 帧） | ~3 分钟 | **35s** | ≤ 60s |
| 分句流水线首句可见 | 不可用 | **25.2s** | ≤ 25s |
| 端到端（热启动，短句） | — | **~23s** | ≤ 60s |

**优化措施：**
- 截帧（542→audio_duration 帧）
- Ingest 缓存（同一头像跳过抽帧，省 ~20s）
- Worker landmark/VAE 增量缓存（跨请求复用 DWPose+VAE 编码，省 ~30-60s）
- FFmpeg rawvideo pipe（跳过 PNG 写磁盘，省 ~10s）
- 异步 Runner（POST 立即返回，不阻塞事件循环）

---

## 7. 故障排查

| 问题 | 原因 | 解决 |
|---|---|---|
| `musetalk is not a package` | sys.path 顺序错误 | musetalk_worker.py 已修复（精确重建 sys.path） |
| `No module named 'mmpose'` | mmcv/mmpose 未安装 | `mim install mmcv==2.1.0 mmdet==3.3.0 mmpose==1.3.1` |
| `MMCV incompatible` | mmdet 版本要求 | mmdet 升级到 3.3.0 兼容 mmcv 2.1.0 |
| GitHub 下载超时 | 云端无法访问 github.com | 从本机 scp 传输 |
| HuggingFace 下载超时 | 云端无法访问 huggingface.co | 使用 hf-mirror.com 或本机 scp + 本地路径 |
| `MuseTalk models not usable` | symlink 未创建 | `ln -s /data/Her/models /data/Her/third_party/MuseTalk/models` |
| modelscope 下载超时 | 网络不稳定 | 重试，cache 在 /data/modelscope_cache |
| `Descriptors cannot be created` | protobuf 版本冲突 | `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` |
| `local MuseTalk 后端不可用` | musetalk_service.py 未同步 | scp 该文件到云端 |
| `未找到 scripts/inference.py` | _validate_repo 过时检查 | 已移除（persistent worker 不需要） |
| IndexTTS2 缺 speaker_id | generate-text-only 未传参 | 已加 speaker_id 表单参数 |

---

## 8. 费用控制

| 场景 | 预计时长 | 费用 |
|---|---|---|
| 单次调试验证 | 2~4 小时 | ¥3.72~7.44 |
| 完整 MVP-1 验证 | 累计 8~10 小时 | ¥15~19 |
| 忘关机一天 | 24 小时 | ¥44.64 |

**要点：**
- 调试完立刻关机（控制台→停止实例）
- `/data` 目录关机不丢失，下次开机数据还在
- 所有权重已部署完毕，下次开机只需启动服务
