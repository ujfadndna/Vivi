# 实施计划表

## 里程碑总览

| 阶段 | 目标 | 周期 | 状态 |
|---|---|---|---|
| MVP-0 | 完整链路跑通，可演示 | 4 周 | ✅ 完成 |
| MVP-1 | RVM 真实抠图 + 准实时首屏 | +2~3 周 | ✅ 完成（2026-06-13） |
| MVP-2 | 产品级对话闭环 + FlashHead 实时渲染 | +4~6 周 | ✅ 完成（2026-06-17） |
| MVP-3 | faster-qwen3-tts 延迟优化 + FlashHead 连续播放验证 | +1 周 | ✅ 云端链路可用，首句冷启动已前置 |
| MVP-3.1 | 一次性连续数字人输出：整段 TTS + 单次 FlashHead + 单个 MP4 | +0.5 周 | ✅ 云端真实链路已验证 |

---

## 云端环境（模板）

| 项目 | 值 |
|---|---|
| GPU | 推荐 24GB VRAM 级别 GPU（如 RTX 3090/4090 或同级云 GPU） |
| SSH | `ssh -p <port> <user>@<host>` |
| 公网 | 可用 HTTPS 反向代理，或 SSH 隧道：`ssh -L 8088:localhost:8100 -p <port> <user>@<host>` |
| 磁盘 | 建议至少 80GB，模型权重和缓存需定期清理 |
| TTS | IndexTTS2 HTTP 服务 :8200（clara 语音，`indextts_http` 后端） |
| FlashHead | Lite 14GB（pipeline 6.3s 加载，GPU 渲染） |
| Agent LLM | DeepSeek API（chat_page 直连 `api.deepseek.com/v1`） |
| 聊天前端 | `:8100/chat`（文字→LLM→真实语音→数字人视频） |
| 启动命令 | `cd /data/Her && bash restart.sh`（内部使用 `/data/venvs/venv_her/bin/python3` + 端口 8100） |
| 当前首屏策略 | `/chat` 轮询 `/health`，等待 TTS、FlashHead worker、头像 warmup、三段真实推理 warmup 全部完成后才开放输入 |

---

## 历史归档

### MVP-0
- 达成时间：未记录（`demo_output.mp4` 已生成）。
- 核心技术栈：IndexTTS2 + MuseTalk V1.5 + RVM + ffmpeg + 本地任务编排。
- 关键实测数据：RTX 4060 Laptop 8GB 端到端约 103s，满足 < 3 分钟目标。
- 遗留问题：推理慢、RVM/背景处理仍偏演示级，未形成实时对话体验。

### MVP-1
- 达成时间：2026-06-13。
- 核心技术栈：RVM 真实抠图 + MuseTalk 常驻 Worker + 分句流水线 + FunHPC RTX 4090。
- 关键实测数据：RTX 4090 首句 25.2s，短句端到端约 23s，连续 3 次推理成功。
- 遗留问题：MuseTalk 仍是主要瓶颈，首屏延迟和句间等待偏长。

### MVP-2
- 达成时间：2026-06-17。
- 核心技术栈：DeepSeek/OpenAI 兼容 Agent + SSE + chat.html + FlashHead Pro + IndexTTS2 情感驱动。
- 关键实测数据：FlashHead 单句热启动 2.6-3.6s，96fps 实时流式生成帧，完整 LLM→TTS→FlashHead→video_url 链路通过。
- 遗留问题：IndexTTS2 批处理 TTS 仍需 6-9s，TTS/FlashHead 串行导致句间停顿 5-10s；情感映射方向需修正。

### MVP-3
- 达成时间：2026-06-18。
- 核心技术栈：faster-qwen3-tts + FlashHead Pro + FastAPI。
- 关键实测数据：faster-qwen3-tts 单独测试首包 300-400ms，RTF 0.31-0.38；FlashHead 单句热启动 2.6-3.6s。
- 遗留问题：`render_scheduler` 逐句提交 + 阻塞轮询导致句间停顿 4-10s。根因是代码编排串行，不是 GPU 架构限制（代码中未使用 CUDA Graph）。
- 解决方案（MVP-3.1）：将 `/api/v1/generate-text-batch` 从逐句生成 + concat 改为整段文本一次 TTS、一次 FlashHead、一次合成，避免句子边界重启动作和口型时间轴。

---

## Agent 能力强化（待实现）

当前 Her 项目已有 RAG、LangGraph、多轮历史、工具框架的代码骨架，但均存在关键缺陷，需要修复后才能在面试中正常演示。

### 项目一：多轮对话持久化

**问题：** `_session_histories` 是进程内存字典，服务重启即丢失全部历史；`/chat` 和 `/chat/stream` 两个接口存的消息类型不一致，混存在同一个 list 里可能序列化报错。

**实现内容：**
- 废弃 `_session_histories`，改用已有的 `checkpoints.sqlite`（LangGraph checkpointer）统一持久化
- 两个接口统一通过 LangGraph graph 驱动，消息类型统一为 `HumanMessage`/`AIMessage`

**演示效果：** 重启服务后继续上次对话，"你还记得我上次说什么吗？"能正确回答。

---

### 项目二：RAG 知识库真正写入

**问题：** `store_memory()` 从未被对话流程调用，每次 `recall_memories` 召回空列表，跨会话记忆形同虚设。ChromaDB embedding 失败时静默吞掉异常，上层无任何感知。

**实现内容：**
- 对话结束后，用 LLM 从本轮对话中提炼关键信息（用户情绪、重要事件、用户偏好），调用 `store_memory()` 写入 ChromaDB
- 新增 `POST /agent/memory` API 端点，支持外部注入文档
- ChromaDB embedding 失败时改为 `logging.warning`，不再静默丢弃

**演示效果：** "上次你告诉我你在备考研究生"——数字人能记住，跨会话有效。

---

### 项目三：LangGraph 图真正执行

**问题：** `graph.py` 的 7 节点状态机编译后从未在生产路径中运行，两个接口都绕过了图直接写逻辑。`perceive`（情绪检测）和 `_detect_user_emotion` 是完全重复的两份代码。

**实现内容：**
- 删除 `_detect_user_emotion` 重复函数
- `/chat/stream` 接口改为通过 `graph.astream()` 驱动，让 perceive → safety_check → retrieve_memory → think → calibrate_emotion 真正串联执行
- checkpointer 统一管理多轮历史（与项目一合并实现）

**演示效果：** 可展示 LangGraph 节点执行日志，每轮对话经过情绪感知 → 安全检查 → 记忆召回 → 生成回复的完整链路。

---

### 项目四：工具调用（生活技能）

**问题：** LangChain Tool 框架存在但没有接入任何实际工具，数字人只会聊天，无法执行任何操作。

**实现内容：** 在 LangGraph 图中新增 `tool_call` 节点，用 LangChain Tool 装饰器注册以下工具：

| 工具 | API/实现方式 | 触发示例 |
|---|---|---|
| 查天气 | wttr.in（无需 key）或和风天气 API（免费）| "今天北京天气怎么样？" |
| 查时间/日期 | Python 系统调用，无需 API | "现在几点了？" / "今天星期几？" |
| 计算器 | Python eval 沙箱 | "帮我算一下 1200 除以 7" |
| 待办事项 | 本地 SQLite 读写 | "帮我记下明天要买牛奶" / "我今天有什么安排？" |
| 搜索新闻 | DuckDuckGo Search API | "最近有什么新鲜事？" |
| 查快递 | 快递100 API（免费额度）| "帮我查一下这个快递单号" |

LLM 输出包含 tool_call 时自动路由执行，结果注入回复。

**演示效果：**
- "今天上海天气怎么样？" → 实时返回气温+天气状况
- "帮我记一下明天下午三点要面试" → "好的，已记录" → "我今天有什么安排？" → 能列出
- 面试时现场演示工具调用链路（工具被调用的 log 可见）

---

### 优先级和工期

| 项目 | 优先级 | 预估工期 |
|---|---|---|
| RAG 写入修复 | P0 | 0.5天 |
| 工具调用（天气+时间+待办）| P0 | 1天 |
| 多轮对话持久化 | P1 | 1天 |
| LangGraph 图真正执行 | P1 | 1~2天 |

---

## MVP-3.1：一次性连续数字人输出

未通过成功标准前不得标记为完成。

### 目标

消除 MVP-3 中 FlashHead 视频分段播放的句间停顿，实现数字人整段回复只生成一个连续 MP4。

### 问题根因

旧 `/api/v1/generate-text-batch` 实际仍是逐句生成，句子边界会重新启动数字人动作/口型时间轴：

```
句子1 TTS → FlashHead → MP4
句子2 TTS → FlashHead → MP4
句子3 TTS → FlashHead → MP4
最后 ffmpeg concat → 1 个 MP4
```

即使 concat 成一个文件，每个句子内部的 FlashHead 推理仍会独立开始，导致动作和口型在句子边界不连续。

### 方案

```
完整回复文本 → 一次 TTS → 一次 FlashHead → 一次合成 → 一个 MP4
```

关键改动：
1. `/api/v1/generate-text-batch` 保持 API 不变，继续接收 `sentences` 并返回 `video_urls`。
2. 内部解析 JSON 数组或换行文本，清理空句后按顺序合并为完整 `full_text`。
3. 中文句子缺少 `。！？.!?` 结尾时补 `。`，避免 TTS 粘句。
4. 只调用一次 `run_tts_only()`，并透传 `language`、`emotion`、`speed`。
5. 只调用一次 `run_generation_from_audio()`，不再把 `_concat_videos()` 作为 batch 主路径。
6. `render_response_batch()` 将单个返回 URL 映射到所有 segment，前端仍播放 `video_urls[0]`。

### 成功标准

| # | 标准 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | 3 句话 Agent 回复只生成一个 MP4 | 单元测试断言 `video_urls` 长度为 1 | ✅ 本地通过 |
| 2 | batch 主路径只调用一次 TTS | 单元测试断言 `run_tts_only()` 调用 1 次，文本为完整合并文本 | ✅ 本地通过 |
| 3 | batch 主路径只调用一次 FlashHead 渲染链路 | 单元测试断言 `run_generation_from_audio()` 调用 1 次 | ✅ 本地通过 |
| 4 | batch 主路径不调用 concat | 单元测试将 `_concat_videos()` monkeypatch 为失败函数 | ✅ 本地通过 |
| 5 | legacy concat helper 仍可用 | OpenCV 生成测试 MP4，ffmpeg concat 后首帧可解码 | ✅ 本地通过 |
| 6 | 云端真实 IndexTTS2 + FlashHead 输出连续动作/口型 | 部署后调用远端 `/chat/simple` / `/api/v1/generate-text-batch`，输出单个 MP4 | ✅ 云端通过 |
| 7 | 云端日志出现整段生成标记 | 检查 server log 包含 `[BATCH] full_text`、`TTS full`、`render full`、`completed` | ✅ 云端通过 |

### 涉及文件

| 文件 | 改动 |
|---|---|
| `app/api/routes/generate.py` | batch 端点改为整段 TTS + 单次渲染；保留 `_concat_videos()` 为 legacy helper |
| `app/tasks/pipeline.py` | `run_tts_only()` 增加 `language`、`emotion`、`speed` 参数 |
| `app/agent/render_scheduler.py` | 单个 batch URL 映射到全部 segment，兼容新返回形态 |
| `tests/test_generate_batch.py` | 覆盖整段 batch 主路径和 legacy concat helper |
| `tests/test_render_scheduler.py` | 覆盖单 URL 映射到多 segment |

---

## 3090 部署 E2E 验证（2026-06-19）

> 部署目标：云端 GPU 容器，建议 24GB VRAM、Ubuntu 22.04、CUDA 12.x。

### 已验证

| 项目 | 实测值 | 文档目标 | 判定 |
|---|---|---|---|
| FlashHead 模型加载 | **14.5s**（冷启动到 pipeline ready） | — | ✅ 可用 |
| FlashHead PyTorch fallback | flash_attn 编译失败，降级为 PyTorch attention | — | ⚠️ 可用但慢 |
| Backend /health | 正常响应 | — | ✅ |
| GPU 空闲显存 | 4674 MiB（FlashHead 加载后） | — | ✅ 24GB 充裕 |
| 磁盘 | 46GB/60GB（77%）| — | ✅ |

### 阻塞项

| 问题 | 详情 | 影响 |
|---|---|---|
| **transformers 版本冲突** | IndexTTS2 需要 ≤4.51.x，FlashHead 需要 ≥4.57.x，同一 venv 不能共存 | 全链路不可用 — 解决方案：独立 venv |
| **IndexTTS2 RTF 偏高** | RTF 稳态 ~2.1x（vs 期望 0.14），瓶颈在 GPT 自回归生成（10-17s），非 BigVGAN | TTS 延迟不可接受，FP16 可能未生效 |
| **BigVGAN CPU fallback** | Ninja 已装但 CUDA 开发头缺失，kernel 编译仍失败 | 次要瓶颈（BigVGAN 仅 0.3s），不急修 |

### IndexTTS2 实测性能（RTX 3090 24GB，venv_tts + transformers 4.51.0）

二轮验证（python3.10-dev + BigVGAN CUDA kernel 编译成功）：

| 句子 | 文本 | TTS | 音频 | RTF |
|---|---|---|---|---|
| "你好" | 2 字 | 4.1s | 2.1s | **2.0** |
| "你好我是你的数字人助手很高兴见到你" | 17 字 | 6.1s | 5.3s | **1.1** |
| "我的核心创新是..." | 23 字 | 9.7s | 8.9s | **1.1** |

模型加载：150s（冷启动 + HF mirror 下载子模型）
稳态 RTF：**1.1x**（较首轮 2.1x 改善 48%）

**结论：3090 + IndexTTS2 稳态 RTF ~1.1x。FP16 生效后预期降至 0.5-0.7x。**

### 已解决的问题

1. IndexTTS2 独立 venv（`venv_tts`，transformers 4.51.0）✅
2. FlashHead 独立 venv（`venv_her`，transformers 4.57.3）✅
3. 依赖冲突方案：两个模型通过 HTTP 通信，不共享进程 ✅
4. **⚠️ CUDA 并发推理互斥**：实测发现同一 IndexTTS2 进程内多个并发 /synthesize 请求会触发 CUDA `indexSelectSmallIndex` assertion crash。根因：GPU 推理不支持多线程并发调用同一模型。解决：TTS 服务加 `threading.Lock()` 互斥锁（`tts_server.py` 已实现）
5. 修 BigVGAN CUDA kernel 编译（需 `python3.10-dev` + `ninja-build`）

### 已解决问题（续）

6. chat_page 聊天前端 — 输入文字→LLM回复→真实语音+数字人视频 ✅
7. batch 端点 TTS 并发 + FlashHead 顺序渲染，句间无间隙 ✅
8. GPU 13.2GB 运行：IndexTTS2 + FlashHead 共存 ✅

### 待完成

1. IndexTTS2 HTTP 服务支持音素时间戳输出（当前返回均匀时间戳）
2. 外网端口映射（当前需 SSH 隧道访问 `:8100/chat`）
3. 确认 FP16 生效（当前 RTF 1.1x，预期 FP16 可达 0.5-0.7x）

### 2026-06-19 修复记录

9. **ffmpeg concat 绝对路径修复** — `_concat_videos` 使用相对路径导致多句视频合并失败（rc=1），改为 `.resolve()` 绝对路径后 21 句 → 1 个合并视频（27.6s）✅
10. **前端多视频回退** — `chat_page.py` 改为返回 `video_urls` 数组，JS 遍历全部播放 ✅
11. **聊天页面视频通话风格** — 重新设计 HTML：单个视频框 + 字幕 + 输入框，模拟视频通话体验 ✅
12. **restart.sh 修复** — 端口 8000→8100，Python 路径修正为 venv ✅
13. **旧产物清理** — 清理 78 个 gen_*.mp4，释放磁盘空间 ✅

### 2026-06-20 修复记录

14. **FlashHead 真实推理 warmup 前置** — 服务启动时在 `workspace/processing/musetalk/warmup_inference` 运行低能量 PCM 的真实 `streaming_job`，`/health` 新增 `warmup.flashhead.inference_warmup`。页面在 `tts.status=ok`、`flashhead.worker_ready=true`、头像 warmup ok、inference warmup ok 前禁用输入，`/chat/simple` 未 ready 时返回 503。✅
15. **多形态 warmup 覆盖** — 单段 2.0s warmup 只能覆盖 `audio_embed(57f)`，首句 2.6-2.8s 音频仍会触发 `audio_embed(81f)` 的 `chunk_0 ~20s` 编译。已改为启动时连续 warmup `2.0s / 3.2s / 5.0s`，云端启动 warmup 总耗时约 80s。✅
16. **首句冷启动验证** — 修复前首句日志出现 `[FTIMING] chunk_0(33f): 20.26s`；修复后同类 `audio_embed(81f)` 首句请求为 `[FTIMING] chunk_0(33f): 0.53s`，一次 `/chat/simple` 实测总耗时 8.919s。✅
17. **/chat 状态文案细化** — 加载遮罩按阶段显示“正在预热语音服务”“正在启动数字人渲染进程”“正在准备数字人头像”“正在预热数字人推理，首次启动约需 1 分钟”，ready 后显示“可以开始聊天”。✅
18. **取消全局点击播放** — 移除 `idle/mainVideo/player` 区域点击即播放的监听，只在自动播放被浏览器阻止时显示显式“播放视频”按钮，避免用户每次点击页面都重新触发视频播放。✅

### 实测性能（RTX 3090 24GB，2026-06-19）

| 指标 | 实测值 |
|---|---|
| FlashHead 冷启动 | 6.3s |
| FlashHead 三段真实 warmup | ~80s（2.0s / 3.2s / 5.0s 低能量 PCM） |
| FlashHead 首句 `chunk_0`（warmup 后） | 0.53s（此前未覆盖形态约 20.26s） |
| IndexTTS2 模型加载 | ~80s |
| TTS 单次推理 (clara) | 2.7s (755ms 音频) |
| TTS RTF（稳态） | 1.1x |
| FlashHead 渲染 | ~3s/句 |
| GPU 空闲 / 满载 | 6.2GB / 13.2GB |
