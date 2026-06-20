<h1 align="center">Vivi</h1>

<p align="center">
  <b>一个可本地运行、可接云端模型的 2D 数字人桌面应用</b>
  

https://github.com/user-attachments/assets/10781ed2-54cc-4fdd-9fd9-8525774b84e0


</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-18-61dafb.svg" alt="React">
  <img src="https://img.shields.io/badge/Electron-Windows-47848f.svg" alt="Electron">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ed.svg" alt="Docker Compose">
</p>

<p align="center">
  <a href="#vivi-是什么">项目简介</a> ·
  <a href="#选择运行路线">运行路线</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#接入真实模型">接入模型</a> ·
  <a href="#开发与测试">开发测试</a> ·
  <a href="#目录结构">目录结构</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## Vivi 是什么

Vivi 是一套面向桌面端体验的数字人对话系统。用户可以上传一张数字人参考图、配置声音参考和模型 endpoint，然后在聊天页面里完成：

1. 输入一句话。
2. LLM 生成回复。
3. TTS 把回复转成语音。
4. FlashHead / MuseTalk 等渲染后端把头像驱动成说话视频。
5. 前端展示回复、字幕和 MP4 播放结果。

Vivi 的重点不是把所有大模型权重塞进桌面安装包，而是把 **桌面交互、profile 持久化、模型编排、远端推理接口** 做成一套可以跑通的产品链路。第一次运行可以全 Mock，不需要 GPU、不需要 LLM key；验证完成后再切到远端或本地真实模型。

## 当前能做什么

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Windows 桌面入口 | 可用 | 根目录提供 `Vivi Desktop.cmd` / `Vivi Stop.cmd`，Electron 壳在 `desktop/` |
| React 聊天界面 | 可用 | `/chat` 页面支持头像、声音、LLM、TTS、Render 配置 |
| Mock 全链路 | 可用 | 不需要模型权重，适合首次安装、UI 验收和打包前测试 |
| Remote 真实链路 | 可用 | 桌面端调用 OpenAI-compatible LLM、HTTP TTS、远端 Render |
| 头像上传同步 | 可用 | remote 渲染请求会把当前头像作为 `avatar_file` 发给 Render 服务 |
| 声音参考上传 | 可用 | 本地保存并校验音频；remote 是否使用克隆音色取决于你的 TTS 服务实现 |
| Profile 持久化 | 可用 | profile、头像、参考音频、endpoint 和加密后的 key 保存在 `workspace/profiles/` |
| Electron 安装包 | 可构建 | 构建产物在 `desktop/release/`，不进入 git |

## 选择运行路线

| 路线 | 需要准备 | 适合场景 | 结果 |
| --- | --- | --- | --- |
| Mock 桌面体验 | Docker Desktop | 第一次运行、UI 验收、演示占位链路 | 能聊天并生成占位 MP4 |
| Remote 真实模型 | LLM key、TTS endpoint、Render endpoint | 普通用户机器 + 远端 GPU 服务 | 本机轻量运行，云端生成真实数字人视频 |
| Local 开发模式 | Python/Node.js，按需安装模型依赖和权重 | 调试后端、接入新模型、改 API | 本机直接跑 FastAPI 和 React |
| Local 真实模型 | GPU、模型权重、对应 `requirements-*.txt` | 私有化验证和模型开发 | 本机完成 TTS / 渲染 / 合成 |

推荐顺序：

1. 先用 Mock 跑通桌面、上传、保存配置和视频播放。
2. 再切 Remote，接入真实 LLM / TTS / Render。
3. 最后按需要部署本地或云端真实模型服务。

## 快速开始

### 1. Windows 桌面模式

前置条件：

- Windows 10/11
- Docker Desktop 已安装并启动
- 已安装 Git

```powershell
git clone <your-her-repo-url>
cd Vivi
```

然后双击：

```text
Vivi Desktop.cmd
```

启动脚本会检查 Docker Desktop，必要时构建镜像，启动 `web / api / redis` 三个服务，然后打开聊天页面：

```text
http://localhost:5173/chat
```

停止服务：

```text
Vivi Stop.cmd
```

命令行启动也可以：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch_desktop.ps1
```

Mock 桌面模式默认不读取你本机 `.env` 里的真实模型配置，避免轻量桌面包误加载 FlashHead、MuseTalk、IndexTTS 等重依赖。

### 2. Docker Compose

```powershell
docker compose --env-file .env.docker.mock up -d --build
```

访问：

| 地址 | 用途 |
| --- | --- |
| `http://localhost:5173/chat` | React 聊天应用 |
| `http://localhost:5173/health` | 经 Web 反代后的健康检查 |
| `http://localhost:5173/api/v1/profile` | 当前 profile，已脱敏 |
| `http://localhost:8100/health` | FastAPI 直连健康检查 |

停止：

```powershell
docker compose down
```

### 3. 源码开发模式

后端：

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8100
```

前端：

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Electron 开发：

```powershell
cd desktop
npm install
npm run dev
```

构建 Windows 安装包：

```powershell
cd desktop
npm run dist:win
```

## 接入真实模型

Vivi 的桌面端只要求三个外部能力：LLM、TTS 和 Render。你可以使用同一个 Vivi 仓库在 GPU 服务器上部署 Render 服务，也可以接第三方兼容服务。

### Remote 模式需要什么

| 配置 | 要求 |
| --- | --- |
| LLM Base URL | OpenAI-compatible，提供 `/chat/completions` |
| LLM Model | 例如 `deepseek-chat`、`gpt-4o-mini` 或你的兼容模型名 |
| LLM API Key | 保存在本机 profile 中，落盘前会加密 |
| TTS API URL | 提供 `POST /synthesize`，返回 JSON 至少包含 `audio_b64` |
| Render API URL | 提供 `POST /api/v1/generate-text-batch`，返回 JSON 至少包含 `video_urls` |

在 `/chat` 设置抽屉中选择：

```text
Deployment Mode: remote
TTS Backend: indextts_http
Render Backend: flashhead
```

然后填入你的 LLM、TTS、Render endpoint。

### Render endpoint 契约

Vivi 桌面端会向 Render 服务提交 multipart form：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `sentences` | string | 要生成的视频文本，可以是多行 |
| `language` | string | 默认 `zh` |
| `emotion` | string | 默认 `calm` |
| `speed` | string/float | 默认 `1.0` |
| `tts_api_url` | string，可选 | 让 Render 服务调用指定 TTS |
| `avatar_file` | file，可选 | 当前 profile 的头像图片 |

响应示例：

```json
{
  "video_urls": ["https://your-render.example.com/outputs/gen_xxx.mp4"],
  "subtitle_segments": [
    {"text": "你好，我是 Vivi。", "start": 0.0, "end": 2.4}
  ],
  "duration_sec": 2.4
}
```

`video_urls` 可以是完整 URL，也可以是 `/outputs/*.mp4` 这种相对路径。Remote 模式下，Vivi 会把相对路径补成 Render 服务的完整地址。

### TTS endpoint 契约

最小可用接口：

```http
POST /synthesize
Content-Type: application/json
```

请求示例：

```json
{
  "text": "你好，这是一次端到端测试。",
  "language": "zh",
  "emotion": "calm",
  "speed": 1.0
}
```

响应示例：

```json
{
  "audio_b64": "<base64 wav data>"
}
```

如果你希望 remote 模式也使用用户上传的声音参考，需要在你的 TTS 或 Render 服务中扩展 speaker 上传、speaker URL 或 speaker ID 的契约。Vivi 本地已经负责保存和校验参考音频，但不会假设所有第三方 TTS 都支持音色克隆。

## 模式说明

| 模式 | 行为 |
| --- | --- |
| `mock` | 不调用真实 LLM/TTS/Render。适合首次启动和 UI 验收 |
| `remote` | 本机调用 LLM，Render 服务负责 TTS/FlashHead/MuseTalk 等重模型 |
| `local` | 本机按 `.env` 中的后端配置加载模型，适合开发者和 GPU 机器 |

Docker 桌面包默认以 `mock` 启动；用户在 UI 中保存为 `remote` 后，配置会持久化到 `workspace/profiles/`。

## 开发与测试

后端全量测试：

```powershell
pytest -q
```

重点链路测试：

```powershell
pytest tests/test_chat_page.py tests/test_profile_api.py tests/test_profile_store.py tests/test_tts_profile_runtime.py tests/test_generate_batch.py tests/test_flashhead_avatar.py -q
```

前端构建：

```powershell
cd frontend
npm run build
```

Electron 开发启动：

```powershell
cd desktop
npm run dev
```

## 目录结构

```text
Vivi/
├── app/                    # FastAPI、模型编排、profile、任务队列
│   ├── api/routes/         # chat、generate、profile、stream 等接口
│   ├── agent/              # LangGraph Agent、记忆、安全护栏
│   ├── services/           # TTS、FlashHead、MuseTalk、RVM、合成后端
│   └── tasks/              # 生成任务编排和状态存储
├── frontend/               # React + Vite 聊天界面
├── desktop/                # Electron Windows 桌面壳
├── scripts/                # 本地启动、停止、验证和部署辅助脚本
├── docs/                   # 架构、Agent 设计、部署和路线文档
├── tests/                  # pytest 测试
├── docker-compose.yml      # 桌面 Docker 运行时
├── Dockerfile.api          # API 镜像
├── Vivi Desktop.cmd        # Windows 双击启动入口
├── Vivi Stop.cmd           # Windows 双击停止入口
├── Her Desktop.cmd         # 旧名称兼容入口
└── Her Stop.cmd            # 旧名称兼容入口
```

这些目录默认不进入 git：

```text
workspace/       # profile、头像、参考音频、输出视频、运行时数据
models/          # 模型权重
frontend/dist/   # 前端构建产物
desktop/release/ # Electron 安装包
node_modules/    # npm 依赖
.env             # 私有环境变量和 key
```

## 不包含什么

为了让仓库能公开、能轻量安装，Vivi 不会把这些内容提交进 git：

- 模型权重、checkpoint、HuggingFace / ModelScope 缓存。
- 用户头像、参考音频、生成视频。
- `.env`、LLM API key、云端 SSH 信息。
- Docker Desktop 安装程序。
- 生产级认证、多租户、计费、内容审核后台。
- 稳定公网域名或云端隧道策略。

## Roadmap

- [ ] 更稳定的 Remote speaker 契约，让上传参考音频也能标准化传给远端 TTS。
- [ ] GPU 云端 Docker 镜像，把 TTS / FlashHead / MuseTalk 服务化部署流程固定下来。
- [ ] Electron 安装包签名、自动更新和更完整的错误诊断页面。
- [ ] 模型 endpoint 健康检查和设置抽屉中的连接测试。
- [ ] 多 profile / 多角色资产库。
- [ ] 长会话记忆、RAG 知识库和更完整的 Agent 工作流。

## 文档

- [数字人系统设计](docs/digital-human-design.md)
- [Agent 设计](docs/agent-design.md)
- [里程碑计划](docs/plan.md)
- [云端部署计划](docs/cloud-deploy-plan.md)

## 安全与隐私

Vivi 默认把运行时数据放在 `workspace/`，并通过 `.gitignore` 排除。LLM API key 在 profile 中加密保存，不会以明文写进 profile JSON。

公开仓库前请再次确认：

```powershell
git status --short
git ls-files --others --exclude-standard
rg -n "sk-|password|root@|ssh -p|192\\.168|C:/Users|D:/index" .
```

## 致谢

Vivi 的数字人链路参考并集成了多个开源方向的成果，包括 FastAPI、React、Electron、Docker Compose、MuseTalk、FlashHead、RVM、LangGraph、OpenAI-compatible LLM 生态和 FFmpeg。

## License

`pyproject.toml` 当前声明为 MIT。正式公开发布前，建议补充根目录 `LICENSE` 文件。
