# Unity 虚拟形象数字人项目方案

分支：`unity-digital-human-jd`  
目标岗位：数字人实习生，方向覆盖 2D/3D 数字人建模与驱动、音唇同步、动作生成、表情合成、渲染、多模态学习与论文式实验。

## 对标 JD 与前沿参考

JD 中最关键的能力点不是单一的“会 Unity”，而是能把计算机视觉、计算机图形学、语音/NLP、多模态学习和工程系统串成一个可演示、可评测、可扩展的数字人系统。本项目定位为：

> 基于 Unity 的实时 3D 虚拟形象数字人，支持文本/语音输入、智能回复、TTS 语音、音素级口型、情绪表情、语义手势、凝视与场景交互，并提供一套可量化评测与算法创新实验。

联网参考的技术趋势：

| 参考方向 | 可借鉴点 | 对本项目的启发 |
|---|---|---|
| NVIDIA ACE | 面向游戏/助手的数字人套件，强调语音、智能、动画，以及 AI 推理和图形负载协同 | 本项目要做“能感知、能对话、能行动”的 Unity 角色，而不是只做说话头 |
| Unity Sentis / Unity AI Inference | 在 Unity 中导入并实时运行神经网络模型，使用终端设备 GPU/CPU 推理 | 轻量表情/动作模型可以 ONNX 化后放进 Unity 端，降低后端延迟 |
| Azure TTS Avatar | 文本到头像视频，支持异步和实时合成 | 可作为云端 avatar 服务基线，但本项目重点放在可控 3D 角色与算法实验 |
| OmniHuman-1 | 2025 年音频/视频/混合驱动的人体动画，支持头像、半身、全身、唱歌和人-物交互 | 说明前沿已经从 lip-sync 走向全身、多条件、交互式人体动画 |
| HunyuanVideo-Avatar | 2025 年音频驱动人类动画，强调动态表现、情绪控制、多角色对话 | 本项目的多角色与情绪对齐可作为 v2 扩展方向 |
| VASA-1 / VASA-3D | 单图音频驱动的实时说话脸与 3D 头部 avatar | 本项目不复制高成本视频生成，而抽取“音频到表情/头动”的可控中间表示 |
| EchoMimic / EchoMimicV2 | 音频 + landmark/pose 条件驱动肖像/半身动画 | 本项目的算法创新也采用“音频韵律 + 语义锚点 + 姿态约束”的多条件策略 |

参考链接见文末。

## 1. 项目背景与目的

### 背景

现有仓库"D:\Her"已经有 2D 数字人视频生成链路：视频输入、TTS、MuseTalk 口型、RVM 抠图、背景合成、任务编排。它适合展示“生成一段视频”，但对 JD 中的 3D 数字人、Unity 驱动、动作生成、表情合成、场景交互覆盖不足。

数字人方向的主线正在从“离线生成一段会说话的视频”转向“实时交互的具身角色”。一个有竞争力的求职项目应该展示三层能力：

1. 模型能力：语音、文本、情绪、动作、表情等多模态信号的建模。
2. 图形与动画能力：Unity 中的 avatar rig、blendshape、Animator、IK、渲染和性能优化。
3. 工程能力：低延迟流式通信、状态机、缓存、评测、监控和可复现实验。

### 目的

构建一个 Unity 3D 数字人系统，形成可面试展示的“研究 + 工程”项目：

1. 用户输入文本或语音，数字人能实时回复。
2. 回复过程中，数字人具备稳定的唇形同步、自然头动、情绪表情、语义手势和凝视行为。
3. Unity 场景中支持简单人-物/人-场景交互，例如指向物体、看向目标、拿起物体、走到展示区。
4. 系统提供测试集、评测指标、A/B 对比和实验记录，可写成技术报告或论文型项目经历。
5. 提出一个针对“语音语义与表情/手势不同步”的算法创新，并做可量化验证。

## 2. 目标与非目标

### 目标

| 编号 | 目标 | 验收方式 |
|---|---|---|
| G1 | Unity 中加载 3D avatar，支持 ARKit/VRM blendshape 和 Humanoid 骨骼动画 | 可切换至少 2 个 avatar，并保持口型/表情可用 |
| G2 | 文本/语音输入到数字人回复的完整交互链路 | 麦克风或文本框输入后，数字人能说出回复 |
| G3 | 音素/viseme 级口型同步 | 口型偏移 P95 小于 80 ms，主观无明显错位 |
| G4 | 情绪表情合成 | 至少支持 neutral、happy、sad、angry、surprised 5 类 |
| G5 | 语义手势生成 | 解释、强调、指向、否定、欢迎等动作与句子语义匹配 |
| G6 | 具备可解释行为状态机 | Idle、Listening、Thinking、Speaking、Acting、Interrupted、Error 状态可观测 |
| G7 | 提供测试集与版本对比 | Baseline、Rule、Proposed 三个版本可自动跑指标 |
| G8 | 形成算法创新点 | 有问题定义、方法、损失/规则、指标和消融实验 |

### 非目标

| 非目标 | 原因 |
|---|---|
| 不训练 OmniHuman/HunyuanVideo 级别的大模型 | 算力和数据成本过高，不适合作为个人求职项目主线 |
| 不以照片级真人克隆为主目标 | 安全风险和肖像授权成本高，且 Unity 3D avatar 更能覆盖 3D 建模/驱动能力 |
| 不做商业级多租户平台 | 重点是算法与端到端系统，不先做计费、租户隔离、后台运营 |
| 不追求所有平台实时运行 | MVP 优先 Windows 桌面端，WebGL/移动端作为后续优化 |
| 不把 LLM 当作唯一亮点 | LLM 只负责对话和高层意图，核心展示在数字人驱动算法和 Unity 表现 |

## 3. 用户与使用场景

### 用户

| 用户 | 诉求 |
|---|---|
| 面试官/导师 | 快速判断候选人是否懂数字人系统、算法、Unity 工程和评测 |
| 项目开发者 | 能本地复现、替换模型、看清楚模块边界 |
| 算法评审者 | 能看到具体问题、实验设计和改进指标 |
| 普通体验者 | 能与虚拟形象自然对话，看见表情和动作反馈 |

### 场景

| 场景 | 描述 | 展示能力 |
|---|---|---|
| 自我介绍数字人 | 数字人用自然表情和手势介绍项目 | TTS、口型、表情、手势、镜头 |
| 技术问答助手 | 用户问“你的算法创新是什么”，数字人分句回答 | 对话、流式生成、动作规划 |
| 场景讲解员 | 用户要求介绍场景里的模型/海报，数字人看向并指向目标 | 视觉目标、凝视、指向、IK |
| 情绪控制演示 | 同一句话用不同情绪说出 | 情绪表情、语速、动作幅度 |
| 中英混合演示 | 输入中文或英文，数字人切换语言和口型 | 多语言 TTS 与 viseme 映射 |
| 对比实验演示 | 同一段输入播放 baseline 和 proposed | 量化评测、A/B 展示 |

## 4. 功能和非功能需求

### 功能需求

| 模块 | 需求 |
|---|---|
| Avatar 管理 | 导入 VRM/FBX/Ready Player Me avatar，维护骨骼、blendshape、材质、LOD |
| 输入层 | 支持文本输入、麦克风输入、预设脚本输入 |
| ASR | 语音转文本，输出文本、时间戳、置信度 |
| 对话层 | 根据角色设定、场景状态、用户问题生成回复 |
| TTS | 输出 wav/pcm 音频、音素/词级时间戳、prosody 特征 |
| 口型驱动 | phoneme/viseme 到 blendshape，支持 coarticulation 平滑 |
| 表情合成 | 根据情绪、语义和 prosody 生成 blendshape 权重曲线 |
| 手势生成 | 根据语义、重音、停顿、场景目标生成手臂、手掌、躯干动作 |
| 头动与凝视 | 听用户时看向用户，说话时在用户/目标/思考方向间切换 |
| 场景交互 | 识别可交互物体，生成看向、指向、靠近、拿取等动作指令 |
| 流式播放 | 分句生成与播放，先播首句，后续句子后台生成 |
| 录制与导出 | 支持录制 demo mp4，保存行为计划和指标 |
| 评测面板 | 展示延迟、FPS、口型误差、动作平滑度、失败原因 |

### 非功能需求

| 类别 | 指标 |
|---|---|
| 延迟 | 文本输入到首个语音帧小于 1.5 s；分句首段 avatar 开始说话小于 2.5 s |
| Unity 性能 | 1080p 下 RTX 4060/3060 级别 GPU 保持 60 FPS；集显降级到 30 FPS |
| 口型稳定性 | blendshape 权重无明显抖动；相邻帧 mouth delta P95 小于设定阈值 |
| 动作自然度 | 手势不过密，动作 jerk 低于 baseline；无明显穿模、手臂折叠 |
| 可扩展性 | avatar、TTS、LLM、动作模型可替换，不影响上层接口 |
| 可复现性 | 一键启动后端，Unity 场景可直接运行，测试集可重复跑 |
| 安全性 | 肖像/声音素材需授权；输出可加水印；对话内容可过滤 |
| 可观测性 | 每次 session 有日志、指标、模型版本、输入输出摘要 |

## 5. 总体架构与数据流

### 总体架构

```text
User
  |
  | text / microphone / scene command
  v
Unity Client
  |-- Input UI / Mic Capture
  |-- Avatar Renderer
  |-- Facial Rig Controller
  |-- Gesture Controller
  |-- Gaze + IK Controller
  |-- Scene Interaction Layer
  |-- Metrics Overlay
  |
  | WebSocket: audio chunks, text, state, animation packets
  v
Backend Service
  |-- Session Manager
  |-- ASR Service
  |-- LLM / Dialogue Manager
  |-- TTS + Alignment Service
  |-- Behavior Planner
  |-- Motion Retrieval / Motion Model
  |-- Evaluation Service
  |
  v
Storage / DB
  |-- PostgreSQL: sessions, turns, metrics, experiments
  |-- Object Storage: audio, clips, logs, exports
  |-- Redis: streaming state, task queue, cache
```

### 在线数据流

```text
1. 用户输入
   text 或 microphone audio

2. 语义理解
   ASR(optional) -> user_text -> Dialogue Manager -> response_text

3. 语音与时间轴
   response_text -> TTS -> audio_pcm + phoneme_timestamps + word_timestamps + prosody

4. 行为规划
   response_text + timestamps + prosody + emotion + scene_state
   -> BehaviorPlan
   -> viseme_curve + expression_curve + gesture_events + gaze_targets

5. Unity 播放
   audio_pcm streaming
   animation packets streaming
   -> blendshape / Animator / IK / camera

6. 指标回传
   latency, FPS, dropped_packets, blendshape jitter, gesture count
   -> Evaluation Service
```

### 离线实验数据流

```text
test_script.json
  -> batch_generate
  -> baseline / rule / proposed 三组 BehaviorPlan
  -> Unity headless or capture mode
  -> metrics.json + video.mp4
  -> report.html
```

## 6. 模块拆解与技术选型

| 模块 | MVP 技术选型 | v2 技术选型 | 选择理由 |
|---|---|---|---|
| Unity 版本 | Unity 2022/2023 LTS 或 Unity 6 LTS，按本机稳定性选择 | Unity 6 + Sentis/AI Inference | MVP 先保证插件生态稳定，后续接入端侧推理 |
| Avatar | VRM 1.0 + UniVRM，或 Ready Player Me Unity SDK | 自建 Blender/CC4 角色 | VRM/Ready Player Me 上手快，blendshape 和 humanoid rig 完整 |
| 面部表情 | ARKit 52 blendshape 子集 + 自定义表情层 | 轻量 Transformer 输出 blendshape 曲线 | ARKit blendshape 易评测、易迁移 |
| 口型 | phoneme-to-viseme 映射 + 平滑 | ONNX/Sentis 音频到 viseme 模型 | MVP 可控，v2 减少规则依赖 |
| TTS | IndexTTS2 / CosyVoice / 云 TTS，可复用现有后端经验 | 情绪 TTS + 流式 TTS | 先保证时间戳和音质，再优化情感 |
| ASR | Whisper / faster-whisper | 流式 ASR | 本项目重点不是 ASR，优先稳定 |
| 对话 | 本地 LLM 或可配置 API | 带场景记忆和工具调用的 Agent | 对话层要能输出意图和情绪标签 |
| 行为规划 | 规则 + 检索式 Motion Graph | 本项目算法：SPCG Planner | 先可运行，再做可发表的改进 |
| 手势动画 | Mixamo/自录动作库 + Animator Override | 语义-韵律动作生成模型 | Motion library 可快速保证质量 |
| IK/约束 | Unity Animation Rigging | FinalIK 或自研约束层 | 避免指向、拿取、凝视穿帮 |
| 渲染 | URP + Cinemachine + Timeline | HDRP/皮肤 shader/实时阴影优化 | 求职 demo 优先稳定和可录制 |
| 后端 | FastAPI + WebSocket + Redis + PostgreSQL | gRPC + 多 worker 调度 | Python 便于模型集成 |
| 端侧推理 | 暂不强依赖 | Unity Sentis/AI Inference 加载 ONNX | 降低延迟，体现 Unity AI 工程能力 |

### Unity 客户端模块

| 模块 | 职责 |
|---|---|
| `AvatarRuntime` | 统一 avatar 初始化、骨骼绑定、blendshape 查询、LOD 设置 |
| `FacialAnimationController` | 接收 viseme/expression 曲线，写入 SkinnedMeshRenderer |
| `GestureAnimationController` | 接收 gesture event，触发 Animator layer、clip、blend tree |
| `GazeController` | 管理眼睛、头部、上身朝向，支持目标权重和过渡 |
| `InteractionController` | 与场景物体交互，维护 affordance，例如 pointable、pickupable |
| `AudioPlaybackSync` | 播放流式音频，并以 audio clock 驱动动画时间轴 |
| `NetworkClient` | WebSocket 通信、断线重连、包序号校验 |
| `MetricsHUD` | 显示 FPS、延迟、队列长度、状态机状态 |

### 后端模块

| 模块 | 职责 |
|---|---|
| `SessionManager` | 创建 session、维护 turn、用户和 avatar 配置 |
| `DialogueManager` | 角色设定、上下文管理、回复生成、输出意图标签 |
| `TTSAlignmentService` | 生成语音，输出音素、词、停顿、F0、energy、duration |
| `BehaviorPlanner` | 生成统一行为计划，包括口型、表情、手势、凝视 |
| `MotionService` | 检索动作片段、做时间伸缩、约束检查 |
| `EvaluationService` | 批量跑测试集并生成指标 |
| `SafetyService` | 输入输出过滤、授权校验、水印配置 |

## 7. Schema、接口、数据库和状态设计

### 核心数据 Schema

```json
{
  "AvatarProfile": {
    "avatar_id": "vrm_female_001",
    "rig_type": "vrm_humanoid",
    "blendshape_schema": "arkit52_subset",
    "voice_id": "speaker_zh_01",
    "style": {
      "gesture_density": 0.55,
      "expressiveness": 0.70,
      "eye_contact": 0.65
    }
  }
}
```

```json
{
  "DialogueTurn": {
    "turn_id": "turn_001",
    "session_id": "sess_001",
    "user_text": "介绍一下你的算法创新",
    "response_text": "我的核心创新是语义和韵律联合驱动的表情手势规划。",
    "emotion": "confident",
    "dialogue_act": "explain",
    "created_at": "2026-06-13T20:00:00+08:00"
  }
}
```

```json
{
  "AlignedSpeech": {
    "audio_id": "aud_001",
    "sample_rate": 24000,
    "duration_ms": 3120,
    "phonemes": [
      {"p": "w", "start_ms": 0, "end_ms": 60},
      {"p": "o", "start_ms": 60, "end_ms": 180}
    ],
    "words": [
      {"text": "核心", "start_ms": 460, "end_ms": 780, "stress": 0.72}
    ],
    "prosody": {
      "f0_hz": "array_ref:f0_001.npy",
      "energy": "array_ref:energy_001.npy",
      "pause_segments": [[1180, 1360]]
    }
  }
}
```

```json
{
  "BehaviorPlan": {
    "plan_id": "plan_001",
    "turn_id": "turn_001",
    "timebase": "audio_ms",
    "viseme_curve": [
      {"t": 0, "viseme": "sil", "weight": 1.0},
      {"t": 60, "viseme": "O", "weight": 0.8}
    ],
    "expression_curve": [
      {"t": 0, "name": "browInnerUp", "weight": 0.1},
      {"t": 400, "name": "mouthSmile_L", "weight": 0.3}
    ],
    "gesture_events": [
      {
        "start_ms": 520,
        "end_ms": 1420,
        "type": "explain_open_palm",
        "hand": "both",
        "intensity": 0.64,
        "target": null
      }
    ],
    "gaze_events": [
      {"start_ms": 0, "end_ms": 800, "target": "user", "weight": 0.9},
      {"start_ms": 1600, "end_ms": 2400, "target": "screen_algorithm", "weight": 0.8}
    ]
  }
}
```

### WebSocket 消息

```json
{
  "type": "session.start",
  "payload": {
    "avatar_id": "vrm_female_001",
    "language": "zh",
    "scene_id": "demo_lab"
  }
}
```

```json
{
  "type": "turn.submit_text",
  "payload": {
    "text": "请介绍你的项目背景和算法创新"
  }
}
```

```json
{
  "type": "audio.chunk",
  "payload": {
    "turn_id": "turn_001",
    "seq": 12,
    "format": "pcm_s16le",
    "sample_rate": 24000,
    "base64": "..."
  }
}
```

```json
{
  "type": "animation.packet",
  "payload": {
    "turn_id": "turn_001",
    "seq": 12,
    "start_ms": 480,
    "end_ms": 560,
    "blendshapes": {
      "jawOpen": 0.32,
      "mouthFunnel": 0.18,
      "browInnerUp": 0.08
    },
    "animator": {
      "gesture_state": "explain_open_palm",
      "gesture_weight": 0.46
    },
    "gaze": {
      "target": "user",
      "weight": 0.9
    }
  }
}
```

### REST API

| 接口 | 用途 |
|---|---|
| `POST /api/v1/sessions` | 创建会话 |
| `GET /api/v1/sessions/{id}` | 获取会话状态 |
| `POST /api/v1/turns/text` | 提交文本输入 |
| `POST /api/v1/turns/audio` | 提交语音输入 |
| `GET /api/v1/turns/{id}/behavior-plan` | 获取行为计划 |
| `POST /api/v1/eval/run` | 批量跑测试集 |
| `GET /api/v1/eval/runs/{id}` | 获取评测结果 |
| `POST /api/v1/assets/avatar` | 上传 avatar 配置 |
| `GET /api/v1/assets/motions` | 查看动作库 |

### 数据库表

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    avatar_id VARCHAR(128) NOT NULL,
    scene_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ
);

CREATE TABLE dialogue_turns (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    user_text TEXT,
    response_text TEXT,
    language VARCHAR(16),
    emotion VARCHAR(64),
    dialogue_act VARCHAR(64),
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE speech_assets (
    id UUID PRIMARY KEY,
    turn_id UUID REFERENCES dialogue_turns(id),
    audio_path TEXT NOT NULL,
    alignment_json JSONB NOT NULL,
    duration_ms INT NOT NULL,
    tts_model VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE behavior_plans (
    id UUID PRIMARY KEY,
    turn_id UUID REFERENCES dialogue_turns(id),
    planner_version VARCHAR(128) NOT NULL,
    plan_json JSONB NOT NULL,
    confidence FLOAT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE eval_runs (
    id UUID PRIMARY KEY,
    version_name VARCHAR(128) NOT NULL,
    testset_name VARCHAR(128) NOT NULL,
    metrics_json JSONB NOT NULL,
    artifact_dir TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
```

### Runtime 状态机

```text
Idle
  -> Listening      用户开始说话或输入
  -> Thinking       ASR/LLM 处理中
  -> Speaking       TTS 音频和动画包播放
  -> Acting         需要执行场景动作，例如指向/拿取
  -> Interrupted    用户打断，停止当前音频和动作
  -> Error          模型或网络失败
  -> Idle
```

Unity Animator 参数建议：

| 参数 | 类型 | 用途 |
|---|---|---|
| `LocomotionSpeed` | float | 走路/站立 |
| `GestureType` | int | 当前手势类别 |
| `GestureWeight` | float | 手势层权重 |
| `EmotionIndex` | int | 情绪表情类别 |
| `EmotionIntensity` | float | 情绪强度 |
| `IsSpeaking` | bool | 说话状态 |
| `IsListening` | bool | 倾听状态 |
| `GazeTargetWeight` | float | 凝视目标权重 |

### 核心算法创新：SPCG 语义-韵律耦合的表情手势规划

### 具体问题

很多数字人 demo 能做到“口型对上声音”，但表情和手势经常出现三个问题：

1. 手势与语义无关，例如解释算法时随机挥手。
2. 表情与声音情绪不同步，例如语气上扬但眉眼不响应。
3. 动作节奏不贴合重音和停顿，例如重音落点没有动作强调，停顿时身体还在动。

这些问题会让数字人看起来像“会动的模型”，而不是“在表达的人”。

### 创新目标

提出 SPCG Planner：Semantic-Prosody Coupled Gesture and Expression Planner，语义-韵律耦合的表情手势规划器。

目标是把文本语义、语音韵律和 Unity 动作约束统一到一个时间轴上，生成低延迟、可控、可解释的行为计划：

```text
response_text
+ phoneme/word timestamps
+ prosody(F0, energy, pause, speaking rate)
+ dialogue_act
+ emotion
+ scene affordance
-> viseme curve
-> expression curve
-> gesture events
-> gaze targets
-> IK constraints
```

### 方法概述

SPCG 采用三阶段设计，MVP 可用规则和检索实现，v2 可训练轻量模型。

#### 阶段 A：语义锚点提取

从回复文本中抽取可驱动动作的语义锚点：

| 锚点 | 示例 | 动作倾向 |
|---|---|---|
| emphasis | “核心创新”“最重要” | beat gesture、上身前倾 |
| contrast | “不是 A，而是 B” | 左右分区手势、摇头 |
| enumeration | “第一、第二、第三” | 计数手势 |
| deictic | “这里”“这个模型” | 指向目标、看向目标 |
| affect | “高兴”“遗憾”“惊讶” | smile、brow、eye widen |
| uncertainty | “可能”“大概” | 低幅度手势、视线偏移 |

实现方式：

1. MVP：关键词 + 依存句法 + LLM 输出结构化标签。
2. v2：训练一个小型 token classifier，输出每个词的 `anchor_type` 和 `importance`。

#### 阶段 B：韵律对齐

TTS 输出音素、词级时间戳，并计算 F0、energy、pause、speaking rate。系统将语义锚点对齐到音频时间轴：

```text
word_i = {
  text,
  start_ms,
  end_ms,
  stress = normalize(energy + f0_delta + duration)
}

anchor_score_i = semantic_importance_i * stress_i
```

当 `anchor_score` 高时，系统在该词附近安排动作 apex，例如手势最高点、眉毛上扬、头点动。

#### 阶段 C：约束感知动作合成

动作不直接逐帧生成，而是从动作库中检索 primitive，再做时间伸缩和 IK 约束：

```text
motion_primitive = retrieve(
    anchor_type,
    emotion,
    dialogue_act,
    avatar_style,
    scene_target
)

scheduled_motion = time_warp(
    primitive,
    onset = anchor_start - pre_onset,
    apex = anchor_peak,
    release = anchor_end + release_tail
)
```

约束包括：

1. 不在 1.2 秒内连续触发两个大幅手势。
2. 指向动作必须有合法 target。
3. 手部 IK 不穿过躯干，不超过肩部极限。
4. 说话停顿时可保留微表情，但降低手势速度。
5. 动作 confidence 低时降级为小幅 beat gesture 或 idle fidget。

### 损失函数与训练方案

v2 如果训练轻量模型，可使用如下目标：

```text
L = L_viseme
  + λ1 * L_emotion_PAD
  + λ2 * L_anchor_contrastive
  + λ3 * L_motion_smooth
  + λ4 * L_gesture_timing
  + λ5 * L_ik_constraint
```

| Loss | 作用 |
|---|---|
| `L_viseme` | 保证 phoneme/viseme 与口型一致 |
| `L_emotion_PAD` | 情绪 valence/arousal/dominance 与文本/语音匹配 |
| `L_anchor_contrastive` | 让语义锚点和对应动作在 embedding 空间靠近 |
| `L_motion_smooth` | 降低关节 jerk 和 blendshape 抖动 |
| `L_gesture_timing` | 让手势 apex 接近重音词时间 |
| `L_ik_constraint` | 惩罚穿模、超关节角、目标偏移 |

训练数据来源：

1. 公开 co-speech gesture 数据集，例如 BEAT、Trinity、TalkSHOW 等。
2. Unity 中自建 motion library，对动作片段标注语义类型。
3. TTS 合成数据，用同一文本生成不同情绪和语速，增加覆盖。
4. 人工标注小测试集，用于验证面试 demo 的核心句子。

### 与普通方案的差异

| 方案 | 输入 | 输出 | 问题 |
|---|---|---|---|
| Baseline 1：音频驱动口型 | 音频 | 口型 | 无语义手势 |
| Baseline 2：规则手势 | 关键词 | 固定动作 | 节奏不贴语音，动作重复 |
| Baseline 3：LLM 直接给动作 | 文本 | 粗粒度动作标签 | 时间轴不准，Unity 约束弱 |
| SPCG | 文本 + 词/音素时间戳 + 韵律 + 场景 | 口型、表情、手势、凝视统一计划 | 语义、节奏、约束同时考虑 |

### 可发表/可讲述的贡献点

1. 提出语义锚点与语音重音联合驱动的动作 apex 对齐策略。
2. 将 LLM 高层意图转成 Unity 可执行的行为计划，而不是直接让 LLM 控动画。
3. 使用 confidence-gated fallback，让生成模型不确定时退回可控规则，保证 demo 稳定。
4. 设计面向实时 Unity avatar 的多指标评测：唇形同步、手势时序、动作平滑、情绪一致、FPS。

## 8. 成功标准

### MVP 成功标准

| 指标 | 目标 |
|---|---|
| 端到端可用 | 文本输入后数字人能完成回答、发声、口型、表情、手势 |
| 首段响应 | 文本输入到开始说话小于 2.5 s |
| Unity 帧率 | 1080p 桌面端大于 60 FPS |
| 口型同步 | 主观无明显错位，P95 偏移小于 80 ms |
| 手势自然度 | 1 分钟回答中无明显随机挥手，动作与重音/语义有对应 |
| 稳定性 | 连续 20 轮对话无崩溃，断线可恢复 |
| 可复现 | README 中一键启动后端和 Unity demo |

### 项目包装成功标准

| 目标 | 输出物 |
|---|---|
| 面试展示 | 2 分钟成片 + 现场可交互 demo |
| 算法能力 | SPCG 方法说明、伪代码、消融实验 |
| 工程能力 | 架构图、接口文档、模块化代码 |
| 科研潜力 | 测试集、指标、baseline 对比、失败案例分析 |

## 9. 测试集与版本对比方案

### 测试集设计

构建 `DigitalHumanEval-ZHEN-50` 小测试集：

| 类别 | 数量 | 示例 |
|---|---:|---|
| 自我介绍 | 5 | “你好，我是一个 Unity 数字人项目。” |
| 技术解释 | 10 | “我的核心算法是语义和韵律联合驱动。” |
| 枚举说明 | 8 | “第一是口型，第二是表情，第三是动作。” |
| 对比转折 | 8 | “它不是简单随机手势，而是根据重音安排动作。” |
| 场景指向 | 6 | “请看右侧的模型结构图。” |
| 情绪句子 | 8 | 高兴、抱歉、惊讶、严肃 |
| 中英混合 | 5 | “This module controls blendshapes and gesture timing.” |

每条样本包含：

```json
{
  "id": "case_001",
  "text": "我的核心创新是语义和韵律联合驱动。",
  "language": "zh",
  "expected_emotion": "confident",
  "expected_anchors": [
    {"word": "核心创新", "type": "emphasis"},
    {"word": "语义", "type": "concept"},
    {"word": "韵律", "type": "concept"}
  ],
  "scene_targets": []
}
```

### 对比版本

| 版本 | 描述 | 目的 |
|---|---|---|
| V0 Baseline | Unity 原生 idle + 简单 mouth open | 最低基线 |
| V1 Rule | phoneme-to-viseme + 关键词手势 | 工程可用基线 |
| V2 SPCG-MVP | 语义锚点 + 韵律重音 + 动作检索 | 验证创新策略 |
| V3 SPCG-Model | 轻量模型预测 anchor/gesture 权重，Sentis 端侧推理 | 验证算法泛化和低延迟 |

### 评测指标

| 指标 | 计算方式 |
|---|---|
| Lip Offset | viseme 峰值与 phoneme/word 边界的时间偏移 |
| Viseme Smoothness | 相邻帧 blendshape delta 和 jerk |
| Gesture Timing Error | gesture apex 与语义重音词 peak 的时间差 |
| Gesture Diversity | 每分钟不同 gesture type 数量和重复率 |
| Gesture Density | 每分钟大幅动作次数，避免过度表演 |
| Emotion Consistency | 文本/语音情绪与表情曲线的分类一致性 |
| Gaze Validity | 凝视目标是否存在，头眼角度是否超过限制 |
| IK Violation Rate | 穿模、超关节角、目标偏移次数 |
| Runtime FPS | Unity 平均 FPS 和 P5 FPS |
| E2E Latency | 输入结束到首个音频/动画帧播放时间 |
| Subjective MOS | 5 分制：自然度、同步性、表达力、可信度 |

### 消融实验

| 实验 | 去掉的部分 | 预期现象 |
|---|---|---|
| A1 | 去掉语义锚点 | 手势节奏可能还行，但动作含义变弱 |
| A2 | 去掉韵律重音 | 手势类型对，但 apex 与说话重点错位 |
| A3 | 去掉 IK 约束 | 指向/拿取更容易穿模 |
| A4 | 去掉 confidence fallback | 模型不确定时动作更随机 |
| A5 | 只用 LLM 粗标签 | 表情和手势时间轴不精确 |

## 10. 分阶段计划

### P0：项目分支与设计文档，0.5 周

| 任务 | 交付 |
|---|---|
| 新建 `unity-digital-human-jd` 分支 | 已完成 |
| 完成项目方案文档 | 本文档 |
| 明确 avatar、Unity 版本、后端协议 | 决策记录 |

### P1：Unity avatar MVP，1 周

| 任务 | 交付 |
|---|---|
| 创建 Unity 项目与基础场景 | `unity/AvatarDemo` |
| 导入 VRM/Ready Player Me avatar | 可播放 idle、表情、口型 |
| 实现 `FacialAnimationController` | 支持 ARKit/VRM blendshape 写入 |
| 实现本地脚本驱动 | 不依赖后端即可播放预设行为计划 |

验收：加载 avatar 后可播放一段预设音频和口型曲线。

### P2：后端对话与 TTS 时间轴，1 周

| 任务 | 交付 |
|---|---|
| FastAPI/WebSocket 服务 | Unity 可连接 |
| TTS 与 alignment 输出 | audio + phoneme/word timestamps |
| 分句流式返回 | 首句先播，后续句子继续生成 |
| 基础状态机 | Idle/Listening/Thinking/Speaking |

验收：文本输入后 Unity 数字人能说出 TTS，并播放口型。

### P3：SPCG-MVP 行为规划，1.5 周

| 任务 | 交付 |
|---|---|
| 语义锚点抽取 | anchor JSON |
| 韵律特征计算 | F0、energy、pause、stress |
| gesture motion library | 10 到 20 个动作片段 |
| 动作调度与时间伸缩 | gesture events |
| 表情曲线生成 | emotion + prosody blendshape |

验收：解释类、枚举类、指向类句子能触发对应手势。

### P4：场景交互与 IK，1 周

| 任务 | 交付 |
|---|---|
| 场景目标注册 | 可指向物体列表 |
| gaze/head/upper-body IK | 看向用户和物体 |
| point/pickup 动作 | 简单人-物互动 |
| 约束检查 | IK violation log |

验收：数字人能说“请看右侧结构图”并看向/指向对应目标。

### P5：评测与对比实验，1 周

| 任务 | 交付 |
|---|---|
| 构建 50 条测试集 | `eval/testsets/digital_human_eval.json` |
| 跑 V0/V1/V2 对比 | `eval/results/*.json` |
| 生成报告 | `eval/report.html` |
| 录制 demo | 2 分钟展示视频 |

验收：能展示 SPCG 相比 baseline 的量化提升。

### P6：v2 轻量模型与 Sentis，2 到 3 周

| 任务 | 交付 |
|---|---|
| 训练 anchor/gesture 小模型 | PyTorch checkpoint |
| 导出 ONNX | `models/spcg_planner.onnx` |
| Unity Sentis 加载 | 端侧推理 demo |
| 与后端模型对比 | 延迟和质量报告 |

验收：部分行为规划可在 Unity 端运行，网络断开时仍可降级表达。

## 11. 风险、降级和安全方案

### 技术风险与降级

| 风险 | 表现 | 降级方案 |
|---|---|---|
| TTS 延迟高 | 数字人长时间 Thinking | 分句流式、缓存常用句、先播 filler 表情 |
| alignment 不准 | 口型错位 | 退回能量驱动 jawOpen，使用固定 viseme 平滑 |
| 手势随机 | 看起来不自然 | confidence 低时只保留小幅 beat 和 idle |
| IK 穿模 | 指向或拿取动作怪异 | 约束失败时改为 gaze-only |
| Unity 帧率低 | 掉帧、音画不同步 | 降低阴影、LOD、关闭高成本后处理 |
| Avatar 资产不兼容 | blendshape 名称缺失 | 建立 retarget map，缺失时使用 jawOpen/eyes/brows 子集 |
| 网络中断 | 音频或动画包丢失 | 本地播放当前 buffer，超时切换 idle |
| LLM 输出过长 | 生成和播放慢 | 回复长度限制，按句中断，允许用户打断 |

### 安全与合规

| 风险 | 方案 |
|---|---|
| 肖像与声音滥用 | 仅使用授权 avatar 和授权声音；导出视频加水印 |
| Deepfake 误用 | README 明确用途，禁用真实人物克隆默认流程 |
| 不当回复 | SafetyService 做输入输出过滤，敏感内容转安全回答 |
| Prompt injection | 工具调用和场景控制使用白名单 schema |
| 隐私数据 | 不默认上传麦克风原始音频到第三方；日志脱敏 |
| 未成年人/医疗/法律场景 | demo 不提供专业建议，明确非生产用途 |

## 12. 部署、监控与成本

### 本地部署

```text
Backend:
  Python 3.10+
  FastAPI
  Redis
  PostgreSQL
  TTS/ASR model checkpoints

Unity:
  Windows Standalone
  URP scene
  VRM/FBX avatar assets
```

启动方式：

```powershell
# backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# optional
docker compose up -d redis postgres
```

Unity 端配置：

```json
{
  "backend_ws": "ws://localhost:8000/ws/avatar",
  "backend_http": "http://localhost:8000",
  "avatar_id": "vrm_female_001",
  "scene_id": "demo_lab"
}
```

### 云端部署

| 部件 | 推荐 |
|---|---|
| API 服务 | Docker Compose 或 Kubernetes |
| GPU worker | 1 张 24GB GPU 优先，低配可用 8GB 但要串行 |
| 对象存储 | MinIO/S3 |
| 指标 | Prometheus + Grafana |
| 日志 | Loki/ELK |
| 实验追踪 | MLflow 或简单 JSON report |

### 监控指标

| 指标 | 用途 |
|---|---|
| `e2e_latency_ms` | 输入到开始播放 |
| `tts_latency_ms` | TTS 性能 |
| `planner_latency_ms` | SPCG 行为规划耗时 |
| `ws_packet_drop_rate` | 流式通信稳定性 |
| `unity_fps_avg/p5` | 客户端性能 |
| `audio_buffer_underrun_count` | 音频播放是否断流 |
| `ik_violation_count` | 动作约束失败次数 |
| `fallback_rate` | 模型/规划降级频率 |
| `gesture_density` | 是否过度动作 |

### 成本估算

| 模式 | 成本 | 适用 |
|---|---|---|
| 纯本地 CPU/GPU | 主要是本机硬件成本 | 开发和面试演示 |
| 本地 Unity + 云 GPU 后端 | 按 GPU 小时计费 | 训练或高质量 TTS/ASR |
| 云 TTS/LLM API | 按字符/token 计费 | 快速验证，不适合大量测试 |
| 端侧 Sentis 推理 | 前期开发成本高，运行成本低 | v2 低延迟展示 |

MVP 控制成本策略：

1. 对话模型可先用可配置 API 或本地小模型。
2. TTS 对常用测试句做缓存。
3. 行为规划先用规则/检索，不训练大模型。
4. 只在 P6 训练轻量模型，并限制在 anchor/gesture 预测任务。

## 13. 未决问题与决策记录

### 未决问题

| 编号 | 问题 | 影响 |
|---|---|---|
| Q1 | Unity 版本最终选 Unity 6 还是 2022/2023 LTS | 影响插件兼容性和 Sentis 接入 |
| Q2 | Avatar 选择 VRM、Ready Player Me 还是自建 Blender 角色 | 影响表情 rig 和展示风格 |
| Q3 | TTS 使用本地 IndexTTS/CosyVoice 还是云 TTS | 影响音质、延迟和部署复杂度 |
| Q4 | 是否做麦克风实时 ASR | 影响交互完整性，但不是核心算法 |
| Q5 | 测试集是否需要人工 MOS 标注 | 影响实验说服力 |
| Q6 | 是否接入摄像头做人脸表情驱动 | 可增强 CV 覆盖，但会拉大范围 |
| Q7 | 是否需要多人/多角色对话 | 对标 HunyuanVideo-Avatar，但不是 MVP 必需 |

### 决策记录

| 日期 | 决策 | 原因 |
|---|---|---|
| 2026-06-13 | 新建 `unity-digital-human-jd` 分支 | 与现有 2D 数字人链路隔离，避免范围混乱 |
| 2026-06-13 | 新项目主线选择 Unity 3D avatar，而不是继续做 2D 视频生成 | 更贴合 JD 的 3D 建模、驱动、动作、渲染能力 |
| 2026-06-13 | MVP 采用规则 + 检索式行为规划，v2 再训练轻量模型 | 保证先可演示，再做研究增强 |
| 2026-06-13 | 算法创新聚焦“语义-韵律耦合的表情手势规划” | 问题具体、可实验、能体现多模态学习和动画控制 |
| 2026-06-13 | 后端与 Unity 通过 WebSocket 传音频和动画包 | 支持流式播放、低延迟和状态可观测 |
| 2026-06-13 | 评测必须包含 baseline 对比 | 让项目从 demo 变成可论证的研究项目 |

## 附录 A. 简历/面试表述

可以把该项目写成：

> 基于 Unity 构建实时 3D 虚拟形象数字人系统，完成文本/语音输入、对话生成、TTS、音素级口型同步、情绪表情、语义手势、凝视与场景交互的端到端链路。提出 SPCG 语义-韵律耦合行为规划算法，将文本语义锚点、TTS 音素/词级时间戳、F0/energy/pause 韵律特征与 Unity 动作约束联合建模，生成可解释的 viseme、blendshape、gesture 和 gaze 时间轴。构建 50 条中英混合测试集，对比 baseline/rule/proposed 三个版本，在口型偏移、手势重音对齐、动作平滑度、情绪一致性和 Unity FPS 上进行量化评测。

## 附录 B. 参考链接

1. NVIDIA ACE for Games: https://developer.nvidia.com/ace-for-games
2. NVIDIA Digital Humans use case: https://www.nvidia.com/en-us/use-cases/digital-humans/
3. Unity Sentis / AI Inference documentation: https://docs.unity3d.com/Packages/com.unity.ai.inference@latest
4. Azure Text to Speech Avatar overview: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech-avatar/what-is-text-to-speech-avatar
5. Azure real-time text to speech avatar: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech-avatar/real-time-synthesis-avatar
6. OmniHuman-1 paper: https://arxiv.org/abs/2502.01061
7. OmniHuman project page: https://omnihuman-lab.github.io/
8. HunyuanVideo-Avatar paper: https://arxiv.org/abs/2505.20156
9. HunyuanVideo-Avatar project page: https://hunyuanvideo-avatar.github.io/
10. VASA-1 Microsoft Research: https://www.microsoft.com/en-us/research/project/vasa-1/
11. VASA-3D Microsoft Research: https://www.microsoft.com/en-us/research/project/vasa-3d/
12. EchoMimic paper: https://arxiv.org/abs/2407.08136
13. EchoMimicV2 project page: https://antgroup.github.io/ai/echomimic_v2/
