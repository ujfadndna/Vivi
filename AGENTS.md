# AGENTS.md

本文件给进入 Her 仓库的团队 agent 使用。开始任何任务前先读本文件，再按任务类型读取对应设计文档和配置。这里记录的是当前代码形态下的协作规则，不替代源码。

## 任务入口

先确认工作目录和状态：

```bash
cd D:/Her
git status --short
```

优先使用 `rg` / `rg --files` 查找文件和符号。所有应用代码在 `app/` 下，模型后端按子包组织（`app/services/flashhead/`、`musetalk/`、`tts/`）。

**做代码修改前必须读：**

| 文件 | 为什么读 |
|------|---------|
| `README.md` | 当前启动路线、真实模型接入的已知坑（PyTorch 2.6 breaking change、Whisper 格式转换、GPU 显存限制等） |
| `docs/digital-human-design.md` | 系统架构、数据流时序图、视频驱动 vs 图像驱动的架构决策 |
| `docs/agent-design.md` | Agent 层设计、LangGraph 7 节点状态机、安全护栏、合规要求 |
| `docs/plan.md` | 当前里程碑进度（MVP-3.1 待实现）、已知遗留问题和瓶颈 |
| `app/config.py` | `Settings` 类定义（pydantic-settings），所有模块后端选择和模型路径的配置入口 |
| `.env.example` | 所有可配置环境变量和默认值、切换后端的注释说明 |

不要凭旧记忆假设路径。Her 项目根目录在 `D:/Her`，模型文件在 `./models/`，工作区在 `./workspace/`，第三方仓库在 `./third_party/`。

## 项目边界

Her 是可控 2D 数字人系统，负责：

- 视频素材接入（OpenCV 抽帧 + Haar 人脸检测）
- TTS 文本转语音（Mock / CosyVoice / IndexTTS2 / Qwen3-TTS，全部可插拔）
- 嘴型同步渲染（MuseTalk / FlashHead Pro，支持离线批量和实时流式）
- 人像分割（RVM） + 背景替换 + FFmpeg 视频合成
- AI 心理陪伴 Agent 对话层（LangGraph 状态机 + ChromaDB RAG + 工具调用）
- FastAPI API + Celery 任务编排

Her 不负责：

- LLM / TTS / STT 服务本身的托管（通过 API 调用外部服务）
- 模型权重的训练、fine-tune 和完整生命周期管理
- 多卡 GPU 调度、分布式推理集群
- 前端 UI（`app/static/chat.html` 和 `demo.html` 仅用于开发调试和 WebSocket 测试）
- 生产级认证、权限、多租户、TURN 服务器

## 关键目录

```text
Her/
├── app/
│   ├── agent/           # LangGraph 对话 Agent（状态机、记忆、安全护栏、工具）
│   ├── api/routes/      # FastAPI 路由（generate、stream、agent、WebSocket）
│   ├── services/        # 模型后端（TTS、MuseTalk、FlashHead、RVM、合成）
│   │   ├── flashhead/   # FlashHead 实时渲染（persistent/real/worker）
│   │   ├── musetalk/    # MuseTalk 嘴型同步（persistent/real/service/worker）
│   │   ├── tts/         # TTS 后端（base/cosyvoice/indextts/qwen3）
│   │   └── rvm/         # RVM 人像分割模型（mobilenetv3 等变体）
│   ├── tasks/           # Celery 任务编排（pipeline、runner、store）
│   ├── static/          # 开发调试用 HTML 页面（chat.html、demo.html）
│   ├── config.py        # Settings 配置类（pydantic-settings，所有环境变量入口）
│   ├── main.py          # FastAPI app 工厂 + 生命周期管理
│   ├── schemas.py       # Pydantic 请求/响应模型
│   └── storage.py       # 任务状态存储抽象
├── deploy/              # 部署脚本（setup.sh、benchmark.py、upload.ps1）
├── docs/                # 设计文档（架构、Agent 设计、部署、竞品分析、计划）
├── models/              # 模型权重和 checkpoint（不提交进 git）
├── scripts/             # CLI 工具脚本（generate.py、deploy、e2e 测试）
├── tests/               # pytest 测试
├── third_party/         # 第三方仓库（MuseTalk、SoulX-FlashHead，不提交进 git）
├── workspace/           # 运行时工作目录（视频、音频、输出、agent db）
│   ├── avatar/          # 数字人视频和图片素材
│   ├── videos/          # 接入的视频帧缓存
│   ├── audio/           # TTS 生成的音频
│   ├── outputs/         # 合成输出视频
│   └── agent/           # Agent SQLite DB + LangGraph checkpoint
├── .env.example         # 环境变量模板
├── pyproject.toml       # 项目元数据 + 统一依赖管理（核心 + 可选分组）
├── requirements.txt     # 核心依赖（所有模块 Mock 模式可跑）
├── requirements-tts.txt           # CosyVoice TTS 额外依赖
├── requirements-tts-indextts.txt  # IndexTTS2 TTS 额外依赖
├── requirements-flashhead.txt     # FlashHead 渲染额外依赖
├── requirements-musetalk.txt      # MuseTalk 嘴型同步额外依赖
├── requirements-segment.txt       # RVM 分割额外依赖
├── requirements-agent.txt         # Agent（LangGraph/ChromaDB）额外依赖
└── pytest.ini           # pytest 配置
```

不要把 `models/`、`workspace/`、`third_party/` 下的权重、缓存、生成媒体、私有资产提交进 git。`.env` 不要提交。

## 启动与运行

### 最快验证（全 Mock，无需 GPU）

```bash
cd D:/Her
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

全 Mock 模式下 TTS 产生正弦占位音频，MuseTalk 复制原帧，RVM 使用居中椭圆 mask。验证链路是否跑通。

### CLI 快速测试

```bash
cd D:/Her
python scripts/generate.py --video input.mp4 --text "你好，我是数字人" --output out.mp4
```

### 启用某个真实后端

在 `app/services/<module>.py` 中用 `@register()` 注册后端类，然后改 `.env`：

```python
# 注册新后端
@register("tts", "local")
class CosyVoiceTTS(TTSBackend):
    def run(self, req, fps): ...
```

```bash
# .env 中切换
TTS_BACKEND=local
```

上层编排（API、CLI、task pipeline）无需改动。

### 当前已注册的后端

| 模块 | 可用后端 | 说明 |
|------|---------|------|
| tts | `mock`, `local`（CosyVoice）, `indextts`（IndexTTS2）, `qwen3`（Qwen3-TTS） | `qwen3` 仅云服务器可用 |
| musetalk | `mock`, `local` | 真实后端 ~3GB VRAM |
| segment | `mock`, `local`（RVM） | 启用前需装 `requirements-segment.txt` |
| flashhead | `mock`, `local` | 真实后端需要 FlashHead checkpoint |
| background | `mock`, `local` | |
| composite | `local` | 始终走真实 FFmpeg（imageio-ffmpeg 自带） |

### 启动 Celery Worker（需要 Redis）

```bash
cd D:/Her
# 默认 eager 同步执行，无需 Redis。如需真实异步：
# 1) 启动 Redis
# 2) .env 设 CELERY_TASK_ALWAYS_EAGER=false
# 3) 起 worker
celery -A app.tasks.celery_app worker --loglevel=info
```

### FlashHead 实时渲染路线

```bash
cd D:/Her
# 安装依赖
pip install -r requirements.txt -r requirements-flashhead.txt
# 确认 .env 中设置了 flashhead 相关路径
# 启动服务后走 /chat/stream 端点
```

### 常见问题速查

- **`torch.load` UnpicklingError**：PyTorch 2.6+ 改默认 `weights_only=True`，旧 checkpoint（MuseTalk UNet、mmpose 等）需 monkey-patch
- **Whisper 格式**：MuseTalk 需要 HuggingFace 格式的 Whisper，openai/whisper-tiny 的 `.pt` 需要手动转 `model.safetensors`
- **HuggingFace 离线**：设置 `HUGGINGFACE_HUB_OFFLINE=1` + `HF_HOME` 指向本地缓存
- **GPU 显存**：IndexTTS2 ~5-6GB + MuseTalk ~3GB，8GB 卡不能同时驻留两个模型
- **ffmpeg**：MuseTalk 子进程需要 `ffmpeg.exe`，`imageio-ffmpeg` 的二进制名为 `ffmpeg-win64-v4.2.2.exe`

## 配置规则

### 优先级

1. 进程环境变量（最高优先级）
2. `.env` 文件
3. `app/config.py` `Settings` 类的 `Field(default=...)`（最低优先级）

`pydantic-settings` 自动加载 `.env`，字段名自动大写下划线映射。例如 `tts_backend: str = "mock"` 对应 `.env` 中的 `TTS_BACKEND`。

### 后端注册机制

`app/services/base.py` 提供全局注册表：

```python
_REGISTRY: dict[str, dict[str, Type]] = {}
# _REGISTRY["tts"]["mock"] → MockTTS 类
# _REGISTRY["tts"]["local"] → CosyVoiceTTS 类
```

- `@register(module, backend)`：注册后端类
- `get_backend(module, backend)`：按配置获取后端类
- 注册失败的 `KeyError` 会列出该模块所有已注册后端

### 两套 Settings

| 类 | 文件 | 用途 |
|----|------|------|
| `Settings` | `app/config.py` | 渲染链路配置（TTS/MuseTalk/FlashHead/RVM 后端、模型路径） |
| `AgentSettings` | `app/agent/agent_config.py` | Agent 层配置（LLM provider/model/key、记忆参数、会话限制） |

两者都继承 `BaseSettings`，都读 `.env`。Agent 层的 LLM API key 和 base URL 通过 `AgentSettings` 管理，不要混入 `Settings`。

### Agent LLM 切换

```bash
# .env 中设置
AGENT_LLM_PROVIDER=deepseek    # anthropic | openai | deepseek
AGENT_LLM_MODEL=deepseek-chat
AGENT_LLM_API_KEY=sk-xxx
AGENT_LLM_BASE_URL=https://api.deepseek.com   # deepseek 自动设，其他 provider 可选
```

`graph.py` 中 `get_llm()` 根据 `AGENT_LLM_PROVIDER` 自动选择 `ChatAnthropic` 或 `ChatOpenAI`（DeepSeek 走 OpenAI 兼容接口）。

## 开发命令

### 安装依赖

```bash
# 核心（Mock 模式全链路可跑）— 两种方式等价
pip install -r requirements.txt
# 或
pip install -e "."

# 按需追加各模块依赖
pip install -e ".[agent]"       # Agent 对话层
pip install -e ".[flashhead]"   # FlashHead 实时渲染
pip install -e ".[musetalk]"    # MuseTalk 嘴型同步
pip install -e ".[segment]"     # RVM 人像分割
pip install -e ".[cosyvoice]"   # CosyVoice TTS
pip install -e ".[indextts]"    # IndexTTS2 TTS

# 同时装多个模块
pip install -e ".[flashhead,agent,musetalk]"
```

### 测试

```bash
# 全部测试
pytest -q

# 详细输出
pytest -v

# 单文件
pytest tests/test_pipeline.py -v
```

### Lint

```bash
# 当前项目未配置 ruff/black，如需要可手动运行
ruff check app tests
```

## 测试选择

按改动范围选择最小但有效的验证：

| 改动范围 | 建议验证 |
|---------|---------|
| 任务编排 / pipeline | `pytest tests/test_pipeline.py -v` |
| RVM 分割 / segment | `pytest tests/test_segment_rvm.py -v` |
| FlashHead 渲染调度 | `pytest tests/test_render_scheduler.py -v` |
| Agent 流式对话 | `pytest tests/test_agent_stream_pipeline.py -v` |
| API 路由 | 启动服务后 `curl` 测试，或 pytest（当前无独立 API 测试文件） |
| 配置变更 | `pytest -q`（全量回归） |
| 新增 services 后端 | `pytest tests/test_pipeline.py -v` + 手动验证对应的 API 端点 |
| Agent 记忆 / RAG | 当前无独立测试，需启动服务后手动验证 |
| WebSocket 端点 | 当前无独立测试，用 `chat.html` 或 `sensor.html` 手动验证 |

**限制**：真实 LLM、TTS（CosyVoice/IndexTTS2/Qwen3）、FlashHead、GPU/NPU、模型权重相关验证受本地环境限制。缺少依赖、密钥、模型权重或硬件时，报告为环境阻塞，不要推断为代码必然错误。

## 代码协作规则

保持改动小而准。不要顺手重构无关模块，不要格式化整个文件，不要改动用户未要求的文档和需求文件。

### 修改 services/ 后端时

- 先读 `app/services/base.py` 理解 `@register()` / `get_backend()` 机制
- 新后端在对应模块文件中新增类 + `@register(module, backend_name)` 装饰
- 不要改 `@register()` 的 module 字符串，它关联整个注册表
- 后端类的 `run()` 或 `run_streaming()` 签名需与同模块已有后端一致
- 在 `.env.example` 中同步新增后端的配置项注释

### 修改 API 路由时

- 路由放在 `app/api/routes/`，每个文件一个领域
- `generate.py`：离线生成（multipart → task_id → video_url）
- `stream.py`：SSE 流式 Agent 对话
- `agent.py`：Agent 会话管理、WebSocket 传感器端点
- WebSocket 路由用 `async def`，避免阻塞事件循环
- 请求/响应 schema 放在 `app/schemas.py`

### 修改 Agent 层时

- 先读 `docs/agent-design.md`（LangGraph 状态机设计 + 安全护栏规则）
- LangGraph 图定义在 `app/agent/graph.py`（7 节点：perceive → safety_check → retrieve_memory → think → calibrate_emotion → render）
- 状态定义在 `app/agent/state.py`（`TherapistState`）
- 安全检测在 `app/agent/safety.py`（`check_safety()` 必须在 LLM 调用前执行）
- 提示词在 `app/agent/prompts.py`
- 记忆（ChromaDB RAG）在 `app/agent/memory.py`
- Agent 独有配置在 `app/agent/agent_config.py`，不要混入 `app/config.py`
- 新增工具用 LangChain `@tool` 装饰器，注册到 `app/agent/tools.py` 的 `ALL_TOOLS`

### 修改配置时

- 配置入口在 `app/config.py` 的 `Settings` 类
- 每个字段必须有合理的 `Field(default=...)` 默认值（Mock 模式可跑）
- `.env.example` 必须同步更新：注释说明用途、列出可选值、给出示例
- 新增配置项要考虑 Windows 路径（反斜杠 or 正斜杠）兼容性
- 不要把个人路径、token、内网 IP 写成默认值

### 修改脚本时

- `scripts/` 下的脚本保持 Windows cmd / Git Bash 兼容
- 生成脚本（`generate.py`）不要依赖 Redis/Celery，走直接调用路径
- 部署脚本（`deploy/` 和 `scripts/deploy_*.py`）标注目标环境（本地 Windows / FunHPC 云服务器）

### 修改 requirements 文件时

- `requirements.txt` 保持最小集：全 Mock 模式可跑
- 模块特定依赖按功能拆到独立 `requirements-<module>.txt`
- 如果包同时出现在多个 requirements 文件，版本必须一致
- 新增模块依赖时同时更新 `README.md` 的安装说明

## 文档要求

写文档时先说明读者和目标，再给命令。必须做到：

- 命令可复制，标明执行目录（`cd D:/Her` 或 `cd /data/Her`）
- 明确区分 mock / local / indextts / qwen3 / cloud 后端
- 明确写出关键环境变量和默认值来源（`.env` or `config.py`）
- 涉及模型路线时同步 `README.md` 和 `docs/plan.md`
- 涉及 API shape 变更时同步 Swagger docs（FastAPI 自动生成）
- 示例不包含真实密钥、私有 IP、个人绝对路径、不可公开的模型下载地址
- 权重、缓存、生成视频等大文件只说明放置路径，不提交进仓库

避免：

- 用绝对个人路径（如 `C:/Users/<you>/...`、`D:/some-local-model-repo`）写死到文档
- 把云端环境（`/data/Her`）的命令写成本地默认
- 把某个 TTS 后端写成唯一选择，不提其他已注册后端
- 把 `requirements-tts-indextts.txt` 写成所有人必装
- 把 `FLASHHEAD_*` 配置写成所有模型都需要

## 第三方仓库协作

Her 依赖三个外部仓库，均在 `third_party/` 目录下（不提交进 git）：

### MuseTalk（嘴型同步）

```bash
cd D:/Her/third_party/MuseTalk
```

- 当前使用版本：V1.5
- 权重路径：`D:/Her/models/musetalkV15/unet.pth`（~3.2GB）
- Her 侧调用入口：`app/services/musetalk/real.py`、`app/services/musetalk/worker.py`
- 真实后端需 `requirements-musetalk.txt`
- 修改 MuseTalk 代码时注意 `scripts/inference.py` 中的 monkey-patch 不要被覆盖

### SoulX-FlashHead（实时渲染）

```bash
cd D:/Her/third_party/SoulX-FlashHead
```

- 权重路径：`D:/Her/models/SoulX-FlashHead-1_3B`
- Her 侧调用入口：`app/services/flashhead/real.py`、`app/services/flashhead/worker.py`
- 真实后端需 `requirements-flashhead.txt`
- 流式帧输出通过 `app/services/flashhead/worker.py` 的 `stream_tts_to_flashhead` 接口

### IndexTTS2（TTS，可选）

```bash
cd <INDEXTTS_REPO>    # 实际路径见 .env 中 INDEXTTS_REPO 配置
```

- 不在 `third_party/` 下，通过 `INDEXTTS_REPO` 配置指向任意路径
- Her 侧调用入口：`app/services/tts/indextts.py`
- 真实后端需 `requirements-tts-indextts.txt`

### 跨仓修改规则

修改第三方仓库代码时：
- 在 Her 侧的 `README.md` 或对应文档中记录改动原因和 patch 内容
- 不要直接把第三方改动提交到 Her 仓库
- 如果改动是 monkey-patch（如 PyTorch 2.6 `torch.load` 修复），确保加载顺序在模型初始化之前
