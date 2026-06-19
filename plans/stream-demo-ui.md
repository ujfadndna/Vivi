# Plan: 流式分句播放 Demo UI

## 目标
改造 demo.html，实现"输入文本 → 分句并发提交 → 首句视频就绪立即播放 → 后续句子无缝衔接"的真实流式体验。

## 实现方案

### 前端逻辑改造（demo.html 内 JS）

1. **分句**：用和后端相同的正则按中文句号/感叹号/问号切分文本
2. **并发提交**：对每句调用 `POST /api/v1/generate-text-only`（异步，立即返回 task_id）
3. **并行轮询**：所有 task_id 同时轮询 `GET /api/v1/generate/{task_id}`
4. **逐句播放**：
   - 第一句 completed → 立即 play
   - video `ended` 事件 → 检查下一句是否 ready → ready 则无缝切换 src 继续播放 → 未 ready 则显示"加载下一句..."等就绪后自动播
5. **进度展示**：将原来的单任务 4 阶段进度改为「句1 ✓ | 句2 渲染中 | 句3 等待」的分句进度条

### UI 变化

- 视频区域不变（复用现有 video 元素）
- 进度区域改为显示每句状态（而非 TTS/MuseTalk/RVM/合成 四阶段）
- 添加"当前播放：第 N 句"指示

### 不改动后端

完全复用现有的：
- `POST /api/v1/generate-text-only` — 提交单句
- `GET /api/v1/generate/{task_id}` — 轮询状态
- `GET /outputs/{file}` — 获取视频

前端自行切句、并发调用、排队播放。

## 步骤

1. 在 `handleSubmit` 中切句 → 并发提交所有句子 → 收集 task_id 列表
2. 启动并行轮询（每个 task_id 独立 setInterval）
3. 维护一个 `segments[]` 数组：`{sentence, taskId, status, videoUrl}`
4. 第一个 segment 变 completed → play video, 更新 UI
5. video ended → advance to next segment（ready 则 play，否则等）
6. 所有 segment 完成且播完 → 显示"全部完成"
