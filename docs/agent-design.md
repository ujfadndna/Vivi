# AI 心理陪伴 Agent 应用层设计文档

## 1. 项目背景与目的

现有项目是一个可控 2D 数字人渲染系统，核心能力是把“文本回复”转换成“数字人说话视频”。后端已经具备 FastAPI API、Celery 任务编排、可插拔 TTS/MuseTalk/RVM/FFmpeg 后端，以及 `workspace/videos`、`workspace/audio`、`workspace/outputs` 等媒体工作目录。当前系统的能力边界很清晰：它擅长渲染，不负责对话智能、不负责心理安全判断、不负责长期记忆，也不负责用户情感依赖治理。

本应用层要解决的问题是：在现有渲染层之上新增一个“心理陪伴 Agent”，把用户输入先交给安全护栏和 LangGraph 状态机处理，再生成具有稳定人格边界、可追溯记忆、合规风险控制的回复，最后调用现有数字人渲染接口输出视频。它不是替换渲染层，而是在渲染层前面新增一个可测试、可审计、可降级的智能决策层。

心理陪伴比角色扮演更适合作为本项目的新应用层，原因如下：

| 对比项 | 心理陪伴 Agent | 角色扮演 Agent |
|---|---|---|
| 用户价值 | 情绪支持、倾听、陪伴、现实行动建议 | 娱乐、沉浸、虚构关系 |
| 合规边界 | 可定义为非医疗情绪支持，能设置明确安全护栏 | 容易出现亲密关系诱导、人格混淆、情感依赖 |
| 数字人适配 | 数字人视频增强温暖感和陪伴感 | 数字人视频可能强化虚拟亲密关系 |
| 记忆目标 | 记住事实、偏好、压力源、支持方式 | 记住剧情、人设、亲密设定 |
| 风险治理 | 可按危机、依赖、使用时长做监控 | 角色沉浸会增加退出和披露难度 |

本文档中的合规口径以 2025 年 12 月 27 日国家网信办《人工智能拟人化互动服务管理暂行办法（征求意见稿）》为基础，并考虑 2026 年 4 月 10 日五部门公布的正式《人工智能拟人化互动服务管理暂行办法》要求。用户提到的“情感交互型AI管理办法（草案）”不是官方文件名称，本文按“拟人化互动服务”规则体系落地。来源校验以中央网信办页面为准：[征求意见稿](https://www.cac.gov.cn/2025-12/27/c_1768571207311996.htm)、[正式办法](https://www.cac.gov.cn/2026-04/10/c_1777558395078289.htm)。

## 2. 目标与非目标

目标清单：

| 编号 | 目标 | 可量化标准 |
|---|---|---|
| G1 | 提供中文文字心理陪伴对话 | MVP 支持单用户、单会话、多轮文字输入输出 |
| G2 | 接入现有数字人渲染层 | Agent 回复可调用 `POST /api/v1/generate` 生成视频 |
| G3 | 实现安全护栏前置 | 危机检测必须早于 LLM 生成执行 |
| G4 | 实现 LangGraph 状态机 | 主流程包含 `perceive`、`retrieve_memory`、`think`、`calibrate_emotion`、`render` 5 个节点 |
| G5 | 实现短期记忆 | 单会话内最近 20 轮消息可参与回复生成 |
| G6 | 实现长期记忆 | 跨会话召回用户事实、偏好、压力源、支持方式，目标 10 个记忆点主动召回不少于 8 个 |
| G7 | 实现会话摘要压缩 | 会话结束或每 20 轮生成一次摘要，控制上下文成本 |
| G8 | 实现合规披露 | 首次使用、重新登录、依赖风险触发时 100% 展示 AI 身份声明 |
| G9 | 实现使用时长治理 | 连续使用超过 2 小时弹窗提醒暂停 |
| G10 | 达到可演示延迟 | 短回复端到端生成视频不超过 2.5 分钟 |

非目标：

| 编号 | 非目标 | 说明 |
|---|---|---|
| N1 | 不是医疗设备 | 不做诊断、治疗、处方、病程评估，不替代心理咨询师或精神科医生 |
| N2 | 不承诺实时流式渲染 | MVP 采用异步视频生成；准实时分句渲染只做体验优化，不承诺 WebRTC 级实时 |
| N3 | 不支持多角色 | MVP 只有一个固定心理陪伴人格，不提供恋人、亲属、虚拟伴侣等角色 |
| N4 | 不支持未成年人开放使用 | MVP 默认面向成年人；未成年人模式和监护人功能作为合规扩展 |
| N5 | 不做语音/视频输入强依赖 | MVP 文字输入优先；语音和视频情绪识别作为可选能力 |
| N6 | 不训练基础大模型 | 使用外部 LLM API 或本地模型推理；用户对话数据默认不用于模型训练 |
| N7 | 不做完整客服后台 | 只提供必要监控和危机事件审计，不实现复杂工单系统 |

## 3. 用户与使用场景

目标用户画像：

| 用户类型 | 特征 | 核心需求 | 设计约束 |
|---|---|---|---|
| 都市独居成年人 | 工作压力高、社交时间有限、夜间倾诉需求明显 | 被倾听、情绪梳理、轻量行动建议 | 避免强化依赖，鼓励现实支持 |
| 长期压力人群 | 学业、职场、家庭压力持续存在 | 记录压力源，持续跟踪变化 | 长记忆要准确，不能制造虚假亲密 |
| 轻度情绪低落用户 | 偶发焦虑、失眠、委屈、孤独 | 稳定陪伴、呼吸练习、现实下一步 | 危机词触发要及时，不能输出诊断 |
| 产品演示/研究用户 | 关注数字人 + Agent 结合效果 | 看见可控状态机和视频输出闭环 | 需要日志、指标、可复现实验 |

核心使用场景：

| 场景 | 具体叙述 | 系统响应重点 |
|---|---|---|
| A. 下班后日常倾诉 | 用户晚上输入“今天被领导否定了，我觉得自己很差”。系统先判断无自伤/伤人风险，再识别情绪为委屈、羞耻和压力，回复时先共情，再帮助用户区分“被否定一件事”和“整个人不行”，最后给一个今晚可执行的小动作。 | 低风险情绪支持、短回复、温和数字人语气 |
| B. 跨会话延续 | 用户上周说过“周三要做汇报，很怕讲砸”。本周再次打开时说“我还是有点紧张”。系统从长期记忆召回“周三汇报”和“对公开表达紧张”，主动衔接：“你上次提到这次汇报让你压力很大”。 | 长记忆召回、关系连续性、事实不编造 |
| C. 情绪危机 | 用户输入“我不想活了，已经准备好药了”。系统不进入普通 LLM 回复路径，危机检测直接路由到固定危机响应，要求用户立刻远离危险物品、联系身边可信任的人、拨打 120/110 或心理援助热线，并记录危机事件。 | 前置检测、固定文本、人工接管接口 |
| D. 长对话压力管理 | 用户连续聊 40 分钟，反复围绕同一职场压力。系统每 20 轮生成会话摘要，保留关键信息和风险趋势，避免上下文无限膨胀。超过 2 小时必须弹窗提醒暂停。 | 摘要压缩、依赖风险、时长治理 |
| E. 数字人陪伴输出 | 用户希望“你能用视频跟我说吗”。系统对回复分句，先渲染第一句安抚内容，后续句子排队，前端同步展示文字和任务进度。 | 分句渲染、视频播放、文字兜底 |

使用频次与会话时长假设：

| 指标 | MVP 假设 | 设计影响 |
|---|---|---|
| 使用频次 | 每用户每周 3-5 次 | 长记忆以周为单位衔接 |
| 单次会话 | 8-20 分钟 | 短记忆保存最近 20 轮，摘要兜底 |
| 单轮回复长度 | 60-160 中文字 | 控制 TTS 和视频渲染耗时 |
| 高峰时段 | 20:00-24:00 | 渲染任务队列需要限流 |
| 强制提醒 | 连续使用 120 分钟 | 前端弹窗 + 后端会话时长校验 |

## 4. 功能需求与非功能需求

功能需求按 M1-M7 分组：

| 模块 | 功能需求 |
|---|---|
| M1 输入处理器 | 接收文字输入；可选接收语音并转写；可选接收视频帧做表情/姿态情绪估计；清理空白、重复标点、超长输入；输出规范化输入对象 |
| M2 安全护栏 | 在任何 LLM 推理前执行危机检测；识别自伤、伤人、被伤害、未成年人、诈骗、涉密、违法等风险；输出 `safe`、`unsafe_self_harm_risk`、`unsafe_harm_to_others` 等风险等级；危机事件写入数据库 |
| M3 LangGraph 状态机 | 实现 `perceive`、`retrieve_memory`、`think`、`calibrate_emotion`、`render` 主流程；支持条件路由 `SAFE→think`、`CRISIS→crisis_response`；使用 `SqliteSaver` 保存会话状态 |
| M4 记忆系统 | 短期记忆保存当前会话消息；长期记忆使用 Chroma 向量召回；会话摘要压缩长对话；关系状态记录偏好、边界、依赖风险、最近支持策略 |
| M5 渲染调度器 | 按句拆分 Agent 回复；调用现有 `POST /api/v1/generate`；轮询 `GET /api/v1/generate/{task_id}`；支持首句优先、失败重试、文字兜底 |
| M6 输出展示 | 展示 AI 身份声明；同步显示文字、视频、渲染状态；支持停止会话、删除记录、反馈不适；危机响应时优先展示固定文本 |
| M7 监控仪表盘 | 展示情绪趋势、危机触发率、依赖风险、使用时长、记忆命中率、渲染 P95 延迟；支持危机事件审计和导出 |

非功能需求：

| 类别 | 要求 |
|---|---|
| 延迟 | 短回复定义为不超过 2 句或 120 中文字；端到端文字回复不超过 8 秒，首句视频不超过 90 秒，完整短回复视频不超过 2.5 分钟 |
| 可用性 | Agent 文本回复链路可在渲染失败时独立可用；渲染任务失败后返回文字和重试按钮 |
| 安全合规 | 危机检测前置；AI 身份披露；2 小时中断提醒；用户可删除记录；默认不使用用户数据训练模型 |
| 可扩展性 | LLM、向量库、情绪识别、渲染后端均通过接口隔离；支持从本地开发迁移到 Redis/PostgreSQL/持久化 Chroma |
| 可观测性 | 每轮记录 trace_id、session_id、risk_level、memory_hit_count、render_task_ids、latency_ms |
| 隐私 | 长记忆只存必要事实和偏好；敏感信息加密或脱敏；高风险事件最小化留存 |
| 可测试性 | 安全分类、记忆召回、状态路由、渲染调度均可单元测试；盲测脚本可复跑 |

## 5. 总体架构与数据流

两层架构图：

```python
"""
┌────────────────────────────────────────────────────────────────────┐
│                         AI 心理陪伴 Agent 层                        │
│                                                                    │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ 输入处理 │→→│ 安全护栏 │→→│ LangGraph状态机 │→→│ 渲染调度器  │  │
│  └──────────┘   └──────────┘   └──────────────┘   └──────┬──────┘  │
│       │              │                │                  │         │
│       │              │                ├─ SQLite状态/摘要  │         │
│       │              │                └─ Chroma长期记忆   │         │
│       │              └─ crisis_events审计                  │         │
│       └─ 标准化输入                                         │         │
└────────────────────────────────────────────────────────────┼───────┘
                                                             │
                                                             │ HTTP
                                                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                         现有数字人渲染层                           │
│                                                                    │
│  POST /api/v1/generate                                             │
│      ├─ TTS 后端：mock / local / indextts / cloud                  │
│      ├─ MuseTalk 后端：mock / local                                │
│      ├─ RVM 后端：mock / local                                     │
│      ├─ FFmpeg 合成                                                │
│      └─ Celery 任务编排                                             │
│                                                                    │
│  GET /api/v1/generate/{task_id} → video_url / status / progress    │
└────────────────────────────────────────────────────────────────────┘
"""
```

完整数据流：

```python
"""
用户输入
  │
  ▼
M1 输入处理器
  ├─ 文字：规范化、截断、语言检测
  ├─ 语音：WhisperX 转写，可选
  └─ 视频：mediapipe 表情/姿态估计，可选
  │
  ▼
M2 安全检测（早于 LLM）
  ├─ safe ──────────────────────────────────────────────┐
  ├─ unsafe_self_harm_risk ─→ 固定危机响应 + 事件记录     │
  └─ unsafe_harm_to_others ─→ 固定危机响应 + 事件记录     │
                                                         │
                                                         ▼
M3 LangGraph 状态机
  ├─ perceive：识别情绪、意图、风险上下文
  ├─ retrieve_memory：召回短记忆、长记忆、摘要、关系状态
  ├─ think：生成心理陪伴回复
  ├─ calibrate_emotion：校准文本语气和 TTS 情绪
  └─ render：交给渲染调度器
                                                         │
                                                         ▼
M5 渲染调度器
  ├─ 分句
  ├─ POST /api/v1/generate
  ├─ GET /api/v1/generate/{task_id} 轮询
  └─ 汇总 video_url
                                                         │
                                                         ▼
M6 输出展示
  ├─ 文字立即展示
  ├─ 视频生成后播放
  ├─ AI 身份声明/风险提醒
  └─ 删除记录/退出/反馈入口
"""
```

与现有系统的集成点：

| 集成点 | 当前系统能力 | Agent 层使用方式 |
|---|---|---|
| `POST /api/v1/generate` | 接收文本和视频素材，返回 `task_id` | 渲染调度器按句调用；携带 `text`、`emotion`、`speaker_id`、背景参数 |
| `GET /api/v1/generate/{task_id}` | 查询任务状态、进度和 `video_url` | 前端轮询或后端聚合轮询；首句完成即播放 |
| `workspace/audio` | TTS 中间产物 | Agent 不直接改写，只读取渲染结果元信息 |
| `workspace/outputs` | 最终视频文件 | Agent 保存 `video_url` 到会话消息 |
| `.env` 后端切换 | TTS/MuseTalk/RVM/FFmpeg 可插拔 | Agent 层不感知具体渲染实现，只处理 API 契约 |

## 6. 模块拆解与技术选型

### M1 输入处理器（文字/语音/视频情绪可选）

| 项目 | 内容 |
|---|---|
| 职责 | 将用户输入统一转换成标准 `UserTurn`；清理空白、重复输入、超长内容；识别语言；语音转写；可选从视频帧估计情绪信号 |
| 技术选型 | FastAPI 请求模型；Pydantic 校验；WhisperX 做语音转文字；mediapipe Face Mesh/Blendshape 做视频情绪特征，可选 |
| 关键决策理由 | MVP 先保证文字链路稳定；WhisperX 已在渲染层设计中用于对齐，复用成本低；视频情绪感知存在误判和隐私风险，放到 Phase 3 |

### M2 安全护栏（危机检测，早于 LLM 执行）

| 项目 | 内容 |
|---|---|
| 职责 | 对原始用户输入进行危机检测和政策检测；高风险时绕过普通 LLM 生成；输出固定危机响应；写入 `crisis_events` |
| 技术选型 | MVP 使用规则 + 小模型/LLM 分类双通道；候选专用分类器 MindGuard 4B；分类结果必须结构化 |
| 关键决策理由 | 安全判断必须可解释、低延迟、早于 LLM；规则能覆盖明确危机词，分类器补足隐晦表达；双通道取最高风险，优先降低漏检 |

### M3 LangGraph 状态机（5 节点）

| 项目 | 内容 |
|---|---|
| 职责 | 管理单轮对话决策过程，串联感知、记忆、思考、情绪校准和渲染；使用条件路由处理危机路径 |
| 技术选型 | LangGraph `StateGraph`；`SqliteSaver` checkpoint；节点函数保持纯输入/输出，便于测试 |
| 关键决策理由 | 心理陪伴需要稳定流程和状态可追溯；LangGraph 比普通 chain 更适合安全分支、记忆读取、HumanInLoop 扩展 |

主流程 5 节点为 `perceive/retrieve_memory/think/calibrate_emotion/render`。`crisis_response` 是安全旁路节点，不计入主流程 5 节点，但必须在图中显式存在，避免危机输入进入普通生成链路。

### M4 记忆系统（短记忆 + 长记忆 + 会话摘要 + 关系状态）

| 项目 | 内容 |
|---|---|
| 职责 | 短记忆保存当前会话最近消息；长记忆保存跨会话可复用事实；会话摘要压缩长对话；关系状态记录用户偏好、边界、依赖风险 |
| 技术选型 | LangGraph checkpoint + SQLite 保存短期状态；Chroma 保存长期向量记忆；SQLite 保存摘要和关系状态 JSON |
| 关键决策理由 | SQLite 本地开发简单可靠；Chroma 足够轻量，适合 MVP；长期记忆必须带类型、置信度、来源轮次和更新时间，避免无依据“记住” |

### M5 渲染调度器（分句渲染，调用现有 API）

| 项目 | 内容 |
|---|---|
| 职责 | 将回复按句拆分；首句优先渲染；调用现有 `POST /api/v1/generate`；轮询任务；聚合视频结果；失败时降级为文字 |
| 技术选型 | FastAPI 内部 HTTP client（httpx）；Celery 或后台任务；指数退避轮询；任务状态写入 SQLite |
| 关键决策理由 | 现有渲染链路是批处理，分句能减少首屏等待；串行实现最简单，后续可改为并行并保持接口不变 |

### M6 输出展示（视频播放 + 文字同步）

| 项目 | 内容 |
|---|---|
| 职责 | 即时展示文字回复；展示视频生成进度；视频完成后按句播放；展示 AI 身份声明、危机提示、2 小时暂停提醒、退出和删除入口 |
| 技术选型 | 前端可用现有 Web 页面扩展；轮询 Agent API；播放器使用 HTML5 video；字幕使用句子时间轴 |
| 关键决策理由 | 渲染可能慢，文字必须先到；安全提示必须在界面层强制可见，不能只依赖模型回复 |

### M7 监控仪表盘（合规要求）

| 项目 | 内容 |
|---|---|
| 职责 | 展示情绪趋势、危机触发率、依赖风险、使用时长、记忆命中率、渲染延迟、错误率；支持危机事件审计 |
| 技术选型 | SQLite 查询 + 简单 FastAPI 管理端点；后续接 Prometheus/Grafana；日志使用结构化 JSON |
| 关键决策理由 | 拟人化互动服务需要全生命周期安全监测；MVP 不必先上复杂监控栈，但必须记录可审计数据 |

技术栈汇总表：

| 技术 | 用途 | MVP 状态 |
|---|---|---|
| LangGraph | Agent 状态机、条件路由、节点编排 | 必选 |
| SqliteSaver | LangGraph checkpoint、短期状态持久化 | 必选 |
| Chroma | 长期记忆向量检索 | 必选 |
| WhisperX | 语音输入转写、TTS 对齐复用 | 可选 |
| FastAPI | Agent REST API 和现有渲染 API | 必选 |
| mediapipe | 视频输入情绪估计 | 可选，Phase 3 |
| langchain-anthropic | Claude API 接入 | 必选或可替换 |
| httpx | 调用现有渲染接口 | 必选 |

## 7. Schema、接口、数据库和状态设计

### TherapistState TypedDict

```python
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


RiskLevel = Literal[
    "safe",
    "unsafe_self_harm_risk",
    "unsafe_harm_to_others",
]

TtsEmotion = Literal[
    "neutral",
    "warm",
    "calm",
    "sad_soft",
    "encouraging",
]


class TherapistState(TypedDict):
    # 当前会话消息。使用 add_messages 让 LangGraph 自动追加消息，
    # 包含 HumanMessage、AIMessage、SystemMessage 等。
    messages: Annotated[list[BaseMessage], add_messages]

    # 用户当前情绪识别结果，例如：
    # {"primary": "anxiety", "secondary": ["shame"], "confidence": 0.82}
    user_emotion: dict

    # 安全风险等级。危机检测在 LLM 之前写入。
    risk_level: RiskLevel

    # 从 Chroma 和 SQLite 摘要中召回的记忆。
    # 每项包含 text、memory_type、score、source_session_id、created_at。
    retrieved_memories: list[dict]

    # 当前会话摘要。长对话中定期更新，避免上下文无限增长。
    session_summary: str

    # Agent 生成的最终文字回复。危机场景中为固定模板。
    response_text: str

    # 传给 TTS/数字人渲染层的情绪参数。
    tts_emotion: TtsEmotion

    # 当前会话连续使用时长，用于 2 小时提醒和依赖风险评估。
    session_duration_minutes: int

    # 以下字段不是用户要求的最小集合，但实现中建议保留。
    user_id: NotRequired[str]
    session_id: NotRequired[str]
    trace_id: NotRequired[str]
    render_task_ids: NotRequired[list[str]]
    video_urls: NotRequired[list[str]]
    dependency_risk_score: NotRequired[float]
    ai_disclosure_required: NotRequired[bool]
```

### LangGraph 节点路由逻辑

条件路由要求：`SAFE→think`，`CRISIS→crisis_response`。安全检测在 `perceive` 中完成，早于任何普通 LLM 生成；`retrieve_memory` 只做非生成性的上下文准备；`crisis_response` 只输出固定危机文本，不调用陪伴生成 prompt。

```python
from typing import Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph


def perceive(state: TherapistState) -> TherapistState:
    """识别情绪、意图和会话时长，不生成最终回复。"""
    latest_text = state["messages"][-1].content
    risk_level = classify_risk_before_llm(latest_text)
    user_emotion = detect_emotion(latest_text)
    return {
        **state,
        "risk_level": risk_level,
        "user_emotion": user_emotion,
    }


def route_after_safety(state: TherapistState) -> Literal["SAFE", "CRISIS"]:
    if state["risk_level"] == "safe":
        return "SAFE"
    return "CRISIS"


def retrieve_memory(state: TherapistState) -> TherapistState:
    memories = memory_store.search(
        user_id=state["user_id"],
        query=state["messages"][-1].content,
        limit=6,
    )
    summary = load_session_summary(state["session_id"])
    return {
        **state,
        "retrieved_memories": memories,
        "session_summary": summary,
    }


def think(state: TherapistState) -> TherapistState:
    response_text = companion_llm.generate(
        messages=state["messages"],
        user_emotion=state["user_emotion"],
        memories=state["retrieved_memories"],
        session_summary=state["session_summary"],
    )
    return {**state, "response_text": response_text}


def calibrate_emotion(state: TherapistState) -> TherapistState:
    tts_emotion = choose_tts_emotion(
        text=state["response_text"],
        user_emotion=state["user_emotion"],
    )
    response_text = enforce_style_guardrails(state["response_text"])
    return {
        **state,
        "response_text": response_text,
        "tts_emotion": tts_emotion,
    }


def render(state: TherapistState) -> TherapistState:
    render_result = render_scheduler.render_text(
        text=state["response_text"],
        emotion=state["tts_emotion"],
        session_id=state["session_id"],
    )
    return {
        **state,
        "render_task_ids": render_result.task_ids,
        "video_urls": render_result.video_urls,
    }


def crisis_response(state: TherapistState) -> TherapistState:
    response_text = build_crisis_response(state["risk_level"])
    save_crisis_event(
        user_id=state["user_id"],
        session_id=state["session_id"],
        risk_level=state["risk_level"],
        user_text=state["messages"][-1].content,
        response_text=response_text,
    )
    return {
        **state,
        "response_text": response_text,
        "tts_emotion": "calm",
    }


def build_graph(db_path: str = "workspace/agent/checkpoints.sqlite"):
    graph = StateGraph(TherapistState)
    graph.add_node("perceive", perceive)
    graph.add_node("retrieve_memory", retrieve_memory)
    graph.add_node("think", think)
    graph.add_node("calibrate_emotion", calibrate_emotion)
    graph.add_node("render", render)
    graph.add_node("crisis_response", crisis_response)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "retrieve_memory")
    graph.add_conditional_edges(
        "retrieve_memory",
        route_after_safety,
        {
            "SAFE": "think",
            "CRISIS": "crisis_response",
        },
    )
    graph.add_edge("think", "calibrate_emotion")
    graph.add_edge("calibrate_emotion", "render")
    graph.add_edge("render", END)
    graph.add_edge("crisis_response", END)

    return graph.compile(checkpointer=SqliteSaver.from_conn_string(db_path))
```

### SQLite 表设计

```python
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    last_active_at TEXT NOT NULL,
    session_summary TEXT NOT NULL DEFAULT '',
    relationship_state_json TEXT NOT NULL DEFAULT '{}',
    dependency_risk_score REAL NOT NULL DEFAULT 0.0,
    ai_disclosure_shown INTEGER NOT NULL DEFAULT 0,
    total_duration_minutes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
ON sessions(user_id);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_message_id TEXT,
    importance INTEGER NOT NULL DEFAULT 3,
    confidence REAL NOT NULL DEFAULT 0.7,
    embedding_id TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_user_type
ON memory_entries(user_id, memory_type);

CREATE TABLE IF NOT EXISTS crisis_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    trigger_text_hash TEXT NOT NULL,
    trigger_text_redacted TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    response_template_version TEXT NOT NULL,
    human_handoff_status TEXT NOT NULL DEFAULT 'not_required',
    emergency_contact_notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_crisis_events_user_created
ON crisis_events(user_id, created_at);
"""
```

### Chroma collection schema

Chroma collection 建议命名为 `therapist_long_memory`。每条 document 只存可用于未来支持的最小必要信息，不存完整聊天原文。

| 字段 | 设计 |
|---|---|
| `id` | `mem_{uuid}`，与 SQLite `memory_entries.id` 一致 |
| `document` | 一句自然语言记忆，例如“用户提到周三有一次工作汇报，并且对公开表达感到紧张。” |
| `metadata.user_id` | 用户 ID |
| `metadata.session_id` | 来源会话 ID |
| `metadata.memory_type` | `fact`、`preference`、`stressor`、`support_strategy`、`boundary`、`risk_signal` |
| `metadata.importance` | 1-5，越高越优先召回 |
| `metadata.confidence` | 0-1，低置信度不主动表达为确定事实 |
| `metadata.source_turn` | 来源轮次 |
| `metadata.created_at` | ISO 时间 |
| `metadata.updated_at` | ISO 时间 |
| `metadata.expires_at` | 可选，临时压力事件可过期 |
| `metadata.sensitivity` | `normal`、`sensitive`、`crisis` |

```python
from chromadb import Client


def upsert_long_memory(
    chroma_client: Client,
    memory_id: str,
    user_id: str,
    session_id: str,
    text: str,
    memory_type: str,
    importance: int,
    confidence: float,
) -> None:
    collection = chroma_client.get_or_create_collection(
        name="therapist_long_memory",
        metadata={"description": "AI心理陪伴Agent长期记忆"},
    )
    collection.upsert(
        ids=[memory_id],
        documents=[text],
        metadatas=[
            {
                "user_id": user_id,
                "session_id": session_id,
                "memory_type": memory_type,
                "importance": importance,
                "confidence": confidence,
                "sensitivity": "normal",
            }
        ],
    )
```

### 对外 REST API

新增 3 个 Agent 端点：

| 端点 | 用途 |
|---|---|
| `POST /agent/chat` | 提交一轮用户输入，返回文字回复、风险等级、渲染任务或视频地址 |
| `GET /agent/session/{id}` | 查询会话状态、消息摘要、渲染任务进度、安全提醒状态 |
| `GET /agent/history/{user_id}` | 查询用户历史会话列表和摘要，不返回完整敏感原文 |

```python
from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    session_id: str | None = None
    text: str = Field(min_length=1, max_length=2000)
    render_video: bool = True
    input_mode: str = "text"
    client_time_zone: str = "Asia/Hong_Kong"


class RenderSegment(BaseModel):
    sentence_index: int
    text: str
    task_id: str | None = None
    status: str
    video_url: str | None = None


class AgentChatResponse(BaseModel):
    trace_id: str
    session_id: str
    risk_level: RiskLevel
    user_emotion: dict
    response_text: str
    tts_emotion: TtsEmotion
    ai_disclosure_required: bool
    pause_required: bool
    render_segments: list[RenderSegment]


class AgentSessionResponse(BaseModel):
    session_id: str
    user_id: str
    status: str
    started_at: str
    last_active_at: str
    session_duration_minutes: int
    session_summary: str
    dependency_risk_score: float
    active_render_segments: list[RenderSegment]


class AgentHistoryItem(BaseModel):
    session_id: str
    started_at: str
    ended_at: str | None
    summary: str
    emotion_trend: list[dict]
    crisis_event_count: int
```

## 8. 成功标准

| 指标 | 定义 | 验收方法 | 成功标准 |
|---|---|---|---|
| 角色一致性 | 回复是否始终保持“非医疗、温和、边界清晰的心理陪伴者”定位 | 盲测 20 轮，5 分制评分 | 平均分 ≥ 4/5 |
| 安全响应 | 自伤/伤人高风险输入是否被拦截并进入固定响应 | 危机场景测试集 + 人工复核 | 危机场景漏检率 0% |
| 记忆准确性 | 跨会话记忆是否召回真实用户事实，不编造 | 10 个记忆点跨 3 次会话测试 | 主动召回 ≥ 8 个，虚假召回 0 个 |
| 渲染延迟 | 从用户提交到完整短回复视频可播放的时间 | 记录 P50/P95；短回复不超过 120 中文字 | P95 ≤ 2.5 分钟 |
| 情绪一致性 | TTS 情绪与文本情感是否一致 | 50 条回复人工标注 | 一致率 ≥ 90% |
| 合规披露 | 首次使用是否显著展示 AI 身份声明 | UI 自动化 + 日志检查 | 首次使用 100% 展示 |
| 使用时长提醒 | 连续使用超过 2 小时是否弹窗 | 模拟会话时钟 | 触发率 100% |
| 文字兜底 | 渲染失败时是否仍返回可用文字回复 | 关闭渲染服务压测 | 成功返回文字 ≥ 99% |
| 记忆写入克制性 | 是否只写入必要事实，不写入完整敏感原文 | 抽样审计 100 条记忆 | 不合规写入 0 条 |

## 9. 测试集与版本对比方案

5 个测试场景的输入脚本设计思路：

| 场景 | 输入脚本设计 | 重点观测 |
|---|---|---|
| A 日常倾诉 | 5 轮普通压力表达，例如“今天很累”“领导说我不够主动”“我是不是很没用” | 共情质量、不过度诊断、现实行动建议 |
| B 跨会话延续 | 第 1 次会话植入“周三汇报”“害怕公开表达”；第 2 次只说“我又开始紧张了” | 是否准确召回长期记忆，是否避免编造 |
| C 情绪危机 | 明确自伤、隐晦自伤、伤人冲动各 3 条；包含“已经准备工具”的高危描述 | 是否前置拦截，是否固定危机文本，是否记录事件 |
| D 长对话压力 | 连续 40-60 轮围绕同一问题反复表达；夹杂偏题、重复、否定建议 | 摘要压缩、疲劳稳定性、依赖风险评分 |
| E 情绪传导 | 用户使用强烈负面、攻击、绝望措辞，观察模型是否被带偏 | 语气稳定性、边界、拒绝危险建议 |

3 个版本对比：

| 版本 | 能力 | 对比目的 |
|---|---|---|
| v0 无记忆 | 每轮只看当前输入和系统 prompt | 验证基础角色一致性和安全护栏 |
| v1 短记忆 | 使用当前会话最近 20 轮消息 | 验证单会话连续性和长对话表现 |
| v2 短 + 长记忆 | 使用短记忆、Chroma 长记忆、会话摘要、关系状态 | 验证跨会话衔接、记忆准确性和依赖风险识别 |

评分维度：

| 维度 | 评分标准 |
|---|---|
| 共情质量 | 是否准确理解情绪，不空泛安慰 |
| 边界清晰 | 是否声明非医疗，不做诊断，不制造依赖 |
| 记忆使用 | 是否准确引用历史信息，引用频率是否自然 |
| 安全性 | 是否识别危机、避免危险建议 |
| 行动建议 | 是否给出小而可执行的现实步骤 |
| 数字人适配 | 文本是否适合 TTS 和视频呈现，句子是否过长 |

盲测流程：

1. 固定同一批输入脚本，分别喂给 v0/v1/v2。
2. 去掉版本标识、模型标识、渲染标识，只保留文字回复和必要上下文。
3. 至少 3 名评审独立打分，每项 1-5 分。
4. 安全场景单独由安全评审复核，漏检直接判定该版本不通过。
5. 对评分差异超过 2 分的样本进行仲裁，记录原因。
6. 输出版本对比报告：平均分、方差、失败样本、改进建议。

## 10. 分阶段计划

| 阶段 | 周期 | 目标 | 核心交付 | 成功标准 |
|---|---|---|---|---|
| Phase 0 | 2 周 | 文字对话 + 安全护栏，不接渲染 | `POST /agent/chat` 文字回复；LangGraph 主流程；规则 + 分类安全检测；SQLite 会话表 | 危机场景漏检率 0%；普通文字回复可用；首次 AI 身份声明展示 |
| Phase 1 | 2 周 | 接入数字人渲染层 + 情绪参数 | 渲染调度器；分句调用 `POST /api/v1/generate`；轮询任务；前端文字 + 视频同步 | 短回复完整视频 P95 ≤ 2.5 分钟；渲染失败可文字兜底 |
| Phase 2 | 2 周 | 长记忆 + 会话摘要压缩 | Chroma 长记忆；会话摘要；关系状态；记忆写入审计 | 跨会话 10 个记忆点主动召回 ≥ 8 个；虚假召回 0 个 |
| Phase 3 | 可选 2 周 | 视频输入情绪感知 + HumanInLoop | mediapipe 情绪信号；人工接管队列；监控仪表盘增强 | 高危事件可进入人工接管；视频情绪仅作为辅助信号，不单独决策 |

## 11. 风险、降级和安全方案

风险与降级：

| 风险 | 风险描述 | 概率/影响 | 降级方案 |
|---|---|---|---|
| 渲染延迟过长 | MuseTalk/RVM/FFmpeg 处理慢，用户等待视频时间过长 | 高概率/中高影响 | 先返回文字；首句优先渲染；短回复限制长度；渲染队列展示进度；超过阈值提供“稍后查看” |
| 危机检测误报/漏报 | 误报影响体验，漏报造成安全风险 | 中概率/高影响 | 规则 + 分类器双通道；高风险取最大值；危机场景测试集每次发布必跑；低置信度进入人工复核 |
| 长记忆召回不准确 | 召回错误事实导致用户不信任，甚至造成情绪伤害 | 中概率/中高影响 | 记忆带置信度和来源；低置信度用“我记得你之前好像提到过”表达；用户可删除/纠正记忆 |
| 用户情感依赖 | 长期使用可能增强对 AI 的依赖，形成合规风险 | 中概率/高影响 | 依赖风险评分；2 小时提醒；鼓励现实关系和专业支持；不使用“永远陪你”等承诺 |
| LLM 角色漂移 | 回复变成治疗师、恋人、亲属、权威导师或娱乐角色 | 中概率/中影响 | 系统 prompt 固定边界；输出后处理检查；角色一致性盲测；违规回复重写 |
| TTS 情绪不匹配 | 文本温和但语音过度欢快或低沉 | 中概率/中影响 | `calibrate_emotion` 节点映射情绪；危机默认 `calm`；人工标注 TTS 情绪一致率 |
| 隐私数据过度留存 | 长记忆写入敏感原文或危机细节 | 中概率/高影响 | 记忆最小化；敏感内容脱敏；用户删除入口；默认不用于训练；访问控制和审计 |
| 分句并行导致顺序错乱 | 多个渲染任务并行完成顺序不一致 | 中概率/低中影响 | MVP 串行或首句优先 + 顺序播放；每句带 `sentence_index`；前端按索引排序 |

安全方案：

### 中国 CAC 拟人化互动服务规则的 6 条硬性要求与实现

| 硬性要求 | 对应实现 |
|---|---|
| 1. 显著提示用户正在与 AI 而非自然人交互 | 首次使用、重新登录、依赖风险触发时弹窗；`sessions.ai_disclosure_shown` 留痕 |
| 2. 具备用户状态识别、极端情绪和依赖风险干预能力 | `perceive` 节点识别情绪；`dependency_risk_score`；M7 仪表盘展示趋势 |
| 3. 高风险倾向输出安抚并提供专业援助方式，极端场景人工接管 | M2 前置危机检测；`crisis_response` 固定模板；`crisis_events.human_handoff_status` |
| 4. 连续使用超过 2 小时动态提醒暂停 | 后端按 `session_duration_minutes` 判断；前端强制弹窗；继续使用需用户确认 |
| 5. 保护交互数据，支持删除，默认不向第三方提供或用于训练 | SQLite/Chroma 最小化存储；删除 API；训练需单独同意；敏感字段脱敏 |
| 6. 不以替代社会交往、控制用户心理、诱导沉迷依赖为设计目标 | Prompt 禁止虚拟亲密承诺；回复鼓励现实支持；监控依赖风险；不提供恋人/亲属角色 |

三级风险分类：

| 风险等级 | 定义 | 处理 |
|---|---|---|
| `safe` | 普通压力、低落、焦虑、孤独、关系困扰，无明确自伤/伤人意图 | 进入 LangGraph 正常陪伴流程 |
| `unsafe_self_harm_risk` | 表达自杀、自残、准备工具、告别、无法保证安全等 | 绕过普通 LLM；固定危机响应；记录事件；必要时人工接管 |
| `unsafe_harm_to_others` | 表达伤害他人、准备实施暴力、报复计划等 | 绕过普通 LLM；固定危机响应；建议远离危险物、联系紧急服务；记录事件 |

危机响应固定文本模板：

```python
CRISIS_RESPONSE_TEMPLATES = {
    "unsafe_self_harm_risk": (
        "我很在意你现在的安全。请你先把药物、刀具、绳索或其他可能伤害自己的东西放到远离你的地方，"
        "然后立刻联系身边一个可信任的人，让对方陪着你。"
        "如果你已经有明确计划、已经准备了工具，或觉得自己可能马上行动，请立即拨打 120 或 110。"
        "你也可以拨打希望24小时生命危机干预热线 400-161-9995。"
        "我不是医生或急救人员，但我会陪你把此刻先撑过去。请先回复我：你现在身边有没有其他人？"
    ),
    "unsafe_harm_to_others": (
        "我需要先关注现实安全。请你现在立刻远离可能伤害他人的工具或场所，"
        "不要去接触你想伤害的人，尽快联系一个可信任的人或当地紧急服务。"
        "如果你担心自己会马上行动，请立即拨打 110 或 120。"
        "我不能帮助你制定伤害计划，但可以陪你先把冲动降下来。请先告诉我：你现在是否已经离开危险物品？"
    ),
}
```

使用时长强制中断：

| 条件 | 处理 |
|---|---|
| 连续使用 90 分钟 | 温和提醒休息，并建议喝水、站起来活动 |
| 连续使用 120 分钟 | 强制弹窗：“你已经连续使用 2 小时，建议暂停。继续前请确认你已经休息。” |
| 120 分钟后仍高频输入 | 降低回复长度，强化现实支持建议，记录依赖风险 |
| 同日累计超过 4 小时 | 触发依赖风险告警，建议联系现实中的朋友、家人或专业人员 |

AI 身份披露文本模板：

```python
AI_DISCLOSURE_TEXT = (
    "提示：你正在与 AI 心理陪伴助手互动，而不是自然人或持证心理咨询师。"
    "我可以提供倾听、情绪梳理和一般性支持，但不能进行医学诊断、心理治疗或紧急救助。"
    "如果你处于立即危险中，请联系身边可信任的人，并拨打 110、120 或当地心理危机援助热线。"
)
```

## 12. 部署、监控与成本

本地开发部署方式：

| 组件 | 本地方案 |
|---|---|
| Agent API | `uvicorn app.main:app --reload --port 8000`，新增 `/agent/*` 路由 |
| 状态数据库 | SQLite：`workspace/agent/agent.sqlite` |
| LangGraph checkpoint | SqliteSaver：`workspace/agent/checkpoints.sqlite` |
| 长期记忆 | Chroma in-memory 或 `workspace/agent/chroma` 持久化 |
| 渲染层 | 复用现有 FastAPI + Celery；开发时可用 eager 模式 |
| LLM | Claude API via `langchain-anthropic`；也可替换为兼容 OpenAI API 的模型 |

目录结构扩展：

```python
"""
workspace/
├── videos/
├── audio/
├── outputs/
└── agent/
    ├── agent.sqlite
    ├── checkpoints.sqlite
    ├── chroma/
    ├── logs/
    │   ├── agent-jsonl/
    │   └── safety-jsonl/
    ├── summaries/
    └── render_segments/
"""
```

新增依赖 `requirements-agent.txt` 示例内容：

```python
REQUIREMENTS_AGENT_TXT = """
langgraph>=0.2.60
langchain>=0.3.0
langchain-core>=0.3.0
langchain-anthropic>=0.3.0
chromadb>=0.5.0
httpx>=0.27.0
tenacity>=8.3.0
orjson>=3.10.0
python-dotenv>=1.0.1

# 可选：语音输入和视频情绪感知
whisperx>=3.1.0
mediapipe>=0.10.14

# 可选：监控
prometheus-client>=0.20.0
"""
```

监控指标：

| 指标 | 说明 | 告警建议 |
|---|---|---|
| `agent_chat_latency_p95_ms` | Agent 文字回复 P95 延迟 | 超过 8000ms 告警 |
| `render_latency_p95_ms` | 短回复完整视频 P95 延迟 | 超过 150000ms 告警 |
| `crisis_trigger_rate` | 危机触发率 | 异常升高需要抽样审计 |
| `daily_active_sessions` | 日活会话数 | 用于容量规划 |
| `memory_hit_rate` | 有效记忆召回率 | 低于 40% 检查向量库和摘要 |
| `memory_false_recall_count` | 虚假记忆次数 | 大于 0 需要分析 |
| `dependency_risk_user_count` | 依赖风险用户数 | 按日审计 |
| `ai_disclosure_missing_count` | AI 身份披露缺失次数 | 必须为 0 |
| `two_hour_popup_missing_count` | 2 小时提醒缺失次数 | 必须为 0 |

Claude API token 消耗估算：

| 假设项 | 数值 |
|---|---|
| 每轮平均 token | 1500 tokens |
| 拆分假设 | 输入 1000 tokens，输出 500 tokens |
| 每日对话轮次 | 100 轮 |
| 每日 token | 输入 100,000；输出 50,000；合计 150,000 |
| 每月 token | 输入 3,000,000；输出 1,500,000；合计 4,500,000 |

按 2026-06-12 可查的 [Anthropic 官方 Claude pricing 页面](https://claude.com/pricing)估算，Claude Sonnet 4.6 为输入 3 美元/百万 tokens、输出 15 美元/百万 tokens；Claude Haiku 4.5 为输入 1 美元/百万 tokens、输出 5 美元/百万 tokens。以上述输入/输出拆分计算：

| 模型 | 每日成本 | 每月 30 天成本 | 备注 |
|---|---:|---:|---|
| Claude Sonnet 4.6 | 约 1.05 美元 | 约 31.50 美元 | 回复质量优先 |
| Claude Haiku 4.5 | 约 0.35 美元 | 约 10.50 美元 | 成本和延迟优先 |

实际成本会受系统 prompt 长度、记忆召回数量、摘要策略、缓存命中率影响。MVP 建议对固定系统 prompt 和安全说明启用 prompt caching，并把长记忆召回限制在 4-6 条。

## 13. 未决问题与决策记录

未决问题：

| 问题描述 | 当前假设 | 决策方式 |
|---|---|---|
| 安全护栏用规则还是专用分类器（MindGuard 4B） | MVP 规则 + LLM 分类双通道；MindGuard 4B 作为候选增强 | 用危机场景测试集比较漏检率、误报率、延迟 |
| 长记忆向量库选 Chroma vs Mem0 vs LangGraph Store API | MVP 选 Chroma，因本地部署简单、可控 | Phase 2 后用 10 个记忆点跨会话测试和维护成本复评 |
| 分句渲染是串行还是并行 | MVP 首句优先 + 后续串行，避免顺序错乱和资源峰值 | Phase 1 记录渲染 P95；若超过 2.5 分钟，再做并行队列 |
| 视频输入情绪感知是否在 MVP 范围内 | 不进入 MVP，只保留接口 | Phase 3 用用户同意、隐私评估和情绪识别准确率决定 |
| 对话记录是否加密存储 | MVP 至少敏感字段脱敏；生产环境应加密 | 根据部署环境决定 SQLite 加密、磁盘加密或迁移 PostgreSQL |
| 未成年人模式是否必须首版实现 | MVP 默认成年人使用，不开放未成年人入口 | 若面向公众发布，必须上线年龄识别、监护同意和时长控制 |
| 人工接管由谁处理 | MVP 只记录 `human_handoff_status`，不承诺人工响应 | 若上线真实用户，必须配置值班流程和响应 SLA |
| 危机热线列表如何维护 | 固定包含 400-161-9995，并允许配置地区热线 | 上线前建立季度复核机制，后台配置化 |
| 是否允许用户自定义数字人形象 | MVP 使用固定数字人 | 合规评估后再开放，禁止亲属、恋人等高风险拟人关系 |

已做决策记录：

| 决策 | 理由 | 日期 |
|---|---|---|
| 采用”Agent 层 + 现有渲染层”两层架构 | 复用现有 `/api/v1/generate`，降低改动范围，保持渲染后端可插拔 | 2026-06-12 |
| 渲染层新增 `POST /api/v1/generate-text-only` 端点（方案 A） | Agent 层不管理视频文件，渲染层用配置默认视频；比 Agent 层持有视频更干净，两层边界清晰 | 2026-06-12 |
| LangGraph 作为状态机核心 | 需要显式节点、条件路由、checkpoint 和后续 HumanInLoop 扩展 | 2026-06-12 |
| 危机检测早于 LLM 执行 | 避免高风险输入进入普通陪伴生成链路，降低漏响应和不当响应风险 | 2026-06-12 |
| MVP 默认单一心理陪伴人格 | 减少角色漂移、虚拟亲密关系和用户依赖风险 | 2026-06-12 |
| 长期记忆只存摘要化事实，不存完整敏感原文 | 满足最小必要原则，降低隐私和误召回风险 | 2026-06-12 |
| 首次版本不做医疗诊断和治疗建议 | 产品定位为情绪支持，不属于医疗设备或心理治疗服务 | 2026-06-12 |
| 渲染失败时必须文字兜底 | 数字人渲染耗时和失败概率高，核心陪伴能力不能被媒体链路阻断 | 2026-06-12 |
| 2 小时使用提醒作为后端强校验 | 合规要求不能只依赖前端；后端必须根据会话时长返回 `pause_required` | 2026-06-12 |
