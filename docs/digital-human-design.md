# 可控实时 2D 数字人系统设计

## 项目定位

**目标用户**：求职展示 demo

**核心效果**：输入一段真实人物视频、目标文本和背景描述，系统自动生成该人物用新语言/新内容说话、背景替换后的视频。

**关键特性**：
- 嘴型与新语音精准同步（MuseTalk）
- 头部、表情、眨眼保留原视频自然动作
- 背景可被静态或动态内容替换
- 支持多语言、多情绪、可控语速
- 离线高清生成 + 可选的准实时预览
- 模型服务完全可插拔（本地 or 云端 or Mock）

---

## 架构决策：为什么是"视频驱动"

### 问题背景

数字人驱动有两个条件：身份信息（长什么样、怎么说话）和运动信息（头怎么动、眼睛怎么看、表情怎么变）。生成这两样的难度差很大。

### 设计选择

| 方案 | 身份来源 | 运动来源 | 复杂度 | 质量 | 适合场景 |
|---|---|---|---|---|---|
| **视频驱动**（v1） | 用户视频 | 用户视频 | 低 | 高（真实运动） | 有视频素材 |
| **图像驱动**（v2 future） | 用户图像 | AI 生成(LivePortrait) | 中 | 中（需融合调试） | 仅有图像 |

**我们选择视频驱动作为 MVP-0**，原因：

1. **输入中已经有视频**：你的需求就包含"人物视频"，已有完整的头动、眼动、自然表情。
2. **技术复杂度最低**：MuseTalk 只需改嘴部区域，无需融合多模型的输出。
3. **质量最可控**：头动和表情是真实的，不依赖 AI 生成的稳定性。
4. **单模型风险最小**：只需 MuseTalk + RVM 两个核心模型，其他都是工程。
5. **时间可承诺**：求职 demo 不需要全场景支持，聚焦"一条链路跑得好"就够。

**图像驱动延后到 v2**：如果未来需要支持用户仅上传一张图的场景，再加 LivePortrait + 融合逻辑。目前不做。

---

## 系统架构

### 数据流时序图

```
用户输入: [人物视频] + [文本+语言] + [背景描述]
                ↓
        ┌───────┴────────────────┐
        ↓                        ↓
  [视频处理]              [文本→语音]
  ├─ 抽帧                ├─ TTS (CosyVoice)
  ├─ 人脸检测 ✓          ├─ ASR+对齐 (WhisperX)
  └─ 清晰度检测          └─ → 音频 + 音素时间戳
        ↓                        ↓
        └───────────┬────────────┘
                    ↓
          [MuseTalk 嘴型生成]
          ├─ 输入：原视频帧序列 + 音频特征 + 音素时间戳
          ├─ 输出：改写嘴部区域的新帧序列
          └─ 保留：头动、表情、身份
                    ↓
          [RVM 人像分割]
          ├─ 输入：MuseTalk 输出帧
          ├─ 输出：人物 mask + Alpha
                    ↓
          [背景处理]
          ├─ 静态模式：替换背景图
          ├─ 动态模式：生成/替换背景视频
          └─ 色调匹配与边缘融合
                    ↓
          [FFmpeg 合成]
          ├─ 输入：前景帧 + 背景帧 + 音频
          ├─ 输出：MP4 / WebM
                    ↓
          最终输出: [数字人视频]
```

### 模块划分（纵向分层）

| 模块 | 职责 | v1 状态 | 技术栈 |
|---|---|---|---|
| **素材接入** | 视频验证、检测、元信息提取 | ✅ | OpenCV, MediaInfo |
| **文本与语音** | TTS + ASR 对齐 | ✅ | CosyVoice, WhisperX |
| **嘴型同步** | 根据音频生成对应嘴型 | ✅ | MuseTalk |
| **人像分割** | 抠图、Alpha 融合 | ✅ | RVM |
| **背景处理** | 静态替换 / 动态生成 | ⚠️ Mock | SDXL API or 预制素材 |
| **视频合成** | 音视频对齐、编码输出 | ✅ | FFmpeg, PyAV |
| **任务编排** | 异步流程、缓存、重试 | ✅ | Celery + Redis |
| **质量评估** | 口型同步误差、身份一致性 | ❌ v2 | 待定 |

---

## 模块详细设计

### 1. 素材接入

**输入**：用户上传的视频文件

**输出**：验证通过 + 元信息（分辨率、时长、FPS、关键帧）+ 抽取的人脸 crops

**功能**：
```python
# 伪代码
def ingest_video(file_path: str) -> VideoMetadata:
    # 格式校验 (mp4, mov, avi)
    validate_format(file_path)
    
    # 时长检查 (建议 10-60s)
    metadata = extract_metadata(file_path)  # → fps, duration, resolution
    assert 10 <= metadata.duration <= 60
    
    # 人脸检测与清晰度评估
    faces = detect_faces(file_path)  # 关键帧采样
    assert len(faces) >= 1, "No face detected"
    assert face_blur_score < THRESHOLD, "Face too blurry"
    
    # 抽帧存储
    frames_dir = extract_frames(file_path)  # → PNG 序列
    
    return VideoMetadata(
        video_id=uuid(),
        fps=metadata.fps,
        num_frames=metadata.num_frames,
        resolution=metadata.resolution,
        face_bbox=faces[0],  # 主人脸
        status="ready"
    )
```

**接口契约**：
```json
POST /api/v1/videos/ingest
Content-Type: multipart/form-data

Request:
{
  "video_file": <binary>,
  "max_duration": 60  // 秒
}

Response (200):
{
  "video_id": "vid_abc123",
  "fps": 25,
  "num_frames": 750,
  "resolution": [1920, 1080],
  "face_bbox": [100, 50, 500, 600],
  "status": "ready"
}

Response (400):
{
  "error": "No face detected" | "Video too blurry" | "Format not supported"
}
```

---

### 2. 文本与语音

**输入**：文本 + 语言代码 + 可选的情绪/语速控制

**输出**：音频文件 + 音素级时间戳（帧号）

**功能**：
```python
def text_to_speech_with_alignment(
    text: str,
    language: str,  # "zh", "en", "es", ...
    speaker_id: Optional[str] = None,  # 音色（CosyVoice支持多音色）
    emotion: str = "neutral",  # "happy", "sad", "angry"
    speed: float = 1.0  # 1.0 = normal, 0.8 = slower
) -> AudioWithTimestamps:
    # Step 1: 文本清洗
    text = clean_text(text, language)  # 数字→汉字，标点规范化
    
    # Step 2: TTS
    audio_wav = cosyvoice.synthesize(
        text=text,
        language=language,
        speaker=speaker_id or "default",
        emotion=emotion,
        speed=speed
    )
    
    # Step 3: ASR + 对齐（强制对齐 WhisperX）
    alignment = whisperx.align(
        audio=audio_wav,
        text=text,
        language=language
    )
    # alignment.phoneme_intervals = [(phoneme, start_frame, end_frame), ...]
    
    return AudioWithTimestamps(
        audio=audio_wav,
        phoneme_intervals=alignment.phoneme_intervals,
        sample_rate=alignment.sample_rate,
        duration_frames=len(audio_wav) // (sample_rate / fps)
    )
```

**接口契约**：
```json
POST /api/v1/audio/synthesize
{
  "text": "你好，我是数字人",
  "language": "zh",
  "emotion": "happy",
  "speed": 1.0
}

Response (200):
{
  "audio_id": "aud_xyz789",
  "audio_url": "/tmp/aud_xyz789.wav",
  "duration_sec": 2.5,
  "duration_frames": 62,  // @ 25fps
  "phoneme_intervals": [
    {"phoneme": "n", "start_frame": 0, "end_frame": 3},
    {"phoneme": "i", "start_frame": 3, "end_frame": 8},
    ...
  ]
}
```

---

### 3. 嘴型同步（MuseTalk）

**输入**：原始视频帧序列 + 音频特征 + 音素时间戳

**输出**：嘴部区域被重绘的新帧序列

**功能**：
```python
def musetalk_sync(
    video_id: str,  # 已抽帧
    audio_id: str,  # 含音素时间戳
    face_bbox: Bbox,  # 从 ingest 获取
    num_frames: int
) -> FrameSequence:
    # Step 1: 加载原始帧和音频
    original_frames = load_frames(video_id)  # → List[np.ndarray]
    audio_wav = load_audio(audio_id)
    phoneme_intervals = get_phoneme_intervals(audio_id)
    
    # Step 2: 调用 MuseTalk 核心模型
    mouth_redrawn_frames = musetalk_model.generate(
        frames=original_frames,
        audio=audio_wav,
        phoneme_intervals=phoneme_intervals,
        face_region=face_bbox,
        attention_control=0.5  # 可控嘴部变化幅度
    )
    
    # Step 3: Alpha 融合边缘（内置）
    # MuseTalk 输出的嘴部会自动羽化，无需额外处理
    
    return FrameSequence(
        frames=mouth_redrawn_frames,
        fps=25,
        num_frames=num_frames
    )
```

**接口契约**：
```json
POST /api/v1/musetalk/generate
{
  "video_id": "vid_abc123",
  "audio_id": "aud_xyz789"
}

Response (202 Accepted - 异步任务):
{
  "task_id": "task_musetalk_001",
  "status": "processing"
}

GET /api/v1/tasks/task_musetalk_001
Response (200):
{
  "status": "completed",
  "output": {
    "output_frames_dir": "/tmp/musetalk_output_frames/",
    "num_frames": 750,
    "fps": 25
  }
}
```

**关键参数**：
- `face_bbox`：人脸区域，用于定位嘴部；来自素材接入模块
- `attention_control`：嘴部形状变化幅度（0~1），低值保留更多原始嘴型，高值完全跟音频

---

### 4. 人像分割（RVM）

**输入**：MuseTalk 输出帧序列

**输出**：前景人物 + Alpha 通道

**功能**：
```python
def segment_person(frames: FrameSequence) -> SegmentedFrames:
    rvm_model = load_rvm_model()
    
    masks = []
    for frame in frames:
        # RVM 输出 0~1 的 mask
        mask = rvm_model.predict(frame)  # → [H, W] float32
        
        # Dilation + Erosion + Gaussian Blur（边缘处理）
        mask = morphology(mask)
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        
        masks.append(mask)
    
    # 帧间平滑（防止闪烁）
    masks = smooth_temporal(masks, window=3)
    
    # 生成前景
    foregrounds = []
    for frame, mask in zip(frames, masks):
        fg = frame * mask[:, :, np.newaxis]  # 按 mask 权重提取
        foregrounds.append(fg)
    
    return SegmentedFrames(
        foregrounds=foregrounds,
        masks=masks
    )
```

**接口契约**：
```json
POST /api/v1/segment/person
{
  "frames_dir": "/tmp/musetalk_output_frames/"
}

Response (202):
{
  "task_id": "task_segment_001",
  "status": "processing"
}

GET /api/v1/tasks/task_segment_001
Response (200):
{
  "status": "completed",
  "output": {
    "foreground_frames_dir": "/tmp/segment_fg/",
    "mask_dir": "/tmp/segment_mask/",
    "num_frames": 750
  }
}
```

---

### 5. 背景处理

**输入**：背景描述文本（可选）/ 背景图片 / 背景视频

**输出**：与前景帧数、分辨率匹配的背景序列

**v1 实现** （简化版）：
```python
def prepare_background(
    mode: str,  # "static" | "dynamic_video" | "generated"
    description: Optional[str],  # 背景描述（仅 mode="generated" 需要）
    num_frames: int,
    resolution: Tuple[int, int],
    bg_image_path: Optional[str] = None
) -> BackgroundFrames:
    
    if mode == "static":
        # 仅用一张背景图，复制成视频长度
        bg = cv2.imread(bg_image_path)
        bg = cv2.resize(bg, resolution)
        backgrounds = [bg] * num_frames
    
    elif mode == "dynamic_video":
        # 用真实视频素材（预制或用户上传）
        backgrounds = load_and_tile_video(bg_video_path, num_frames, resolution)
    
    elif mode == "generated":
        # ⚠️ v1 中 Mock，调用云端 API 或返回纯色
        # backgrounds = call_sdxl_api(description, num_frames, resolution)
        backgrounds = [np.ones((*resolution, 3), dtype=np.uint8) * 200] * num_frames  # 灰色占位
    
    return BackgroundFrames(frames=backgrounds)
```

**接口契约**：
```json
POST /api/v1/background/prepare
{
  "mode": "static",  // "static" | "dynamic_video" | "generated"
  "num_frames": 750,
  "resolution": [1920, 1080],
  "bg_image_path": "/path/to/background.jpg"  // 仅 mode=static 需要
}

Response (200):
{
  "status": "ready",
  "background_frames_dir": "/tmp/bg_frames/",
  "num_frames": 750
}
```

**v1 限制**：
- 生成模式返回占位符（纯色），真实生成延后到 v2
- 动态视频需要用户上传或提前准备

---

### 6. 视频合成（FFmpeg）

**输入**：前景帧 + 背景帧 + 音频 + 帧率

**输出**：MP4 或 WebM 视频文件

**功能**：
```python
def composite_video(
    foreground_dir: str,  # PNG 序列 + alpha
    background_dir: str,  # PNG 序列
    audio_file: str,
    fps: int = 25,
    resolution: Tuple[int, int] = (1920, 1080),
    output_format: str = "mp4"
) -> str:
    
    import subprocess
    
    # Step 1: 生成帧列表文件
    frame_list = generate_concat_demux(foreground_dir, background_dir, fps)
    
    # Step 2: FFmpeg 合成
    # 伪代码，实际使用 PyAV 或直接调 ffmpeg 命令
    cmd = [
        "ffmpeg",
        "-r", str(fps),
        "-i", f"{foreground_dir}/%08d.png",  # 前景
        "-i", f"{background_dir}/%08d.png",  # 背景
        "-filter_complex", "[0][1]overlay=0:0",  # 前景覆盖背景
        "-i", audio_file,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        f"output.{output_format}"
    ]
    
    subprocess.run(cmd, check=True)
    
    return "output.mp4"
```

**接口契约**：
```json
POST /api/v1/composite/render
{
  "foreground_dir": "/tmp/segment_fg/",
  "background_dir": "/tmp/bg_frames/",
  "audio_file": "/tmp/aud_xyz789.wav",
  "fps": 25,
  "output_format": "mp4"
}

Response (202):
{
  "task_id": "task_composite_001",
  "status": "processing"
}

GET /api/v1/tasks/task_composite_001
Response (200):
{
  "status": "completed",
  "output": {
    "video_url": "/tmp/output_final.mp4",
    "size_mb": 245.3,
    "duration_sec": 30.0
  }
}
```

---

### 7. 任务编排（Celery + Redis）

**目的**：管理长流程、支持异步、缓存中间结果、失败重试

**任务拓扑**（DAG）：
```
ingest_video
    ↓
synthesize_audio
    ↓
musetalk_sync ──┐
                ├─→ segment_person
                │       ↓
prepare_background──→ composite_video
                      ↓
                   final_video
```

**实现框架**：
```python
from celery import Celery, chain, group

app = Celery("digital_human", broker="redis://localhost:6379")

@app.task
def task_ingest_video(video_path):
    result = ingest_video(video_path)
    return result

@app.task
def task_synthesize_audio(text, language):
    result = text_to_speech_with_alignment(text, language)
    return result

@app.task
def task_musetalk_sync(video_id, audio_id):
    result = musetalk_sync(video_id, audio_id)
    return result

# ... 其他任务定义

# 编排：并行 audio+video 处理，再串联
def orchestrate_generation(video_path, text, language, bg_mode):
    workflow = chain(
        group(
            task_ingest_video.s(video_path),
            task_synthesize_audio.s(text, language)
        ),
        task_musetalk_sync.s(),
        task_segment_person.s(),
        group(
            task_prepare_background.s(bg_mode),
            task_musetalk_sync.s()  # 前面的结果传入
        ),
        task_composite_video.s()
    )
    result = workflow.apply_async()
    return result.id
```

**接口契约**：
```json
POST /api/v1/generate
{
  "video_file": <binary>,
  "text": "你好世界",
  "language": "zh",
  "background_mode": "static",
  "background_image": <binary>  // optional
}

Response (202 Accepted):
{
  "task_id": "gen_2024_001",
  "status": "queued"
}

GET /api/v1/generate/gen_2024_001
Response (200):
{
  "status": "processing",  // "queued" | "processing" | "completed" | "failed"
  "progress": {
    "ingest": "completed",
    "audio_synthesis": "completed",
    "musetalk": "50%",
    "segmentation": "pending",
    "composite": "pending"
  }
}

GET /api/v1/generate/gen_2024_001 (最终)
Response (200):
{
  "status": "completed",
  "result": {
    "video_url": "http://localhost:8000/outputs/gen_2024_001.mp4",
    "created_at": "2024-06-11T12:30:45Z"
  }
}
```

---

### 8. 质量评估（v2，暂不实现）

**规划**（不在 MVP-0 中实现）：
- 嘴型同步误差（比对音素边界和实际嘴部运动）
- 身份一致性（脸部识别距离）
- 视频闪烁率
- 背景边缘质量

---

## 里程碑与优先级

### MVP-0：最小可演示（**v1，目标 4 周**）

**目标**：一条完整链路能跑通，输出可播放的视频，展示效果。

**包含模块**：
- ✅ 素材接入
- ✅ 文本+语音 (TTS+ASR)
- ✅ MuseTalk 嘴型同步
- ✅ RVM 人像分割
- ⚠️ 背景处理 (仅静态，生成 Mock)
- ✅ 视频合成
- ✅ 任务编排 (基础 Celery)

**交付物**：
- FastAPI 服务 + Celery 后端
- 完整的数据流 (素材→音频→嘴型→抠图→合成)
- 一个可跑的端到端脚本：`python gen_video.py --video input.mp4 --text "你好"`
- Web 前端：上传、提交、查看进度、下载视频

**成功标准**：
```
输入：一段 30s 人物视频 + 文本
输出：能播放、口型和语音对齐、背景替换、清晰度 720p+
      推理时间 < 3 分钟（RTF < 6）
```

---

### MVP-1：功能完善（**v2，后续迭代**）

**新增**：
- 动态背景生成（接入云端 API 或本地 SDXL）
- 多语言、多情绪、语速控制
- 分句流式生成（准实时预览）
- WebRTC 实时预览流
- 图像驱动支持（LivePortrait 融合）

**时间**：2~3 周

---

### MVP-2：产品级（**v3，如有时间**）

**新增**：
- 质量评估闭环（自动检测口型偏差、身份丢失、闪烁）
- 并发调度优化（多 GPU 分担）
- 缓存策略（同样的音频/视频不重复计算）
- 成本统计（每个生成消耗多少计算资源）

---

## 数据流设计

### 文件组织

```
/workspace
├── videos/              # 用户上传的原始视频
│   └── vid_abc123/
│       ├── original.mp4
│       ├── metadata.json
│       └── frames/      # 抽取的帧序列
├── audio/               # TTS 生成的音频
│   └── aud_xyz789/
│       ├── tts.wav
│       └── phonemes.json  # 音素时间戳
├── processing/          # 中间处理结果
│   ├── musetalk/        # MuseTalk 输出帧
│   ├── segmentation/    # RVM 输出前景+mask
│   └── background/      # 背景帧
├── outputs/             # 最终输出视频
│   └── gen_2024_001.mp4
└── cache/               # Celery 任务结果缓存
```

### 数据库 Schema（PostgreSQL）

```sql
-- 任务表
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    user_id VARCHAR(64),
    input_video_id VARCHAR(64),
    status VARCHAR(32),  -- queued, processing, completed, failed
    progress_json JSONB,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- 生成结果表
CREATE TABLE generations (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id),
    video_path VARCHAR(256),
    output_video_path VARCHAR(256),
    duration_sec FLOAT,
    quality_metrics JSONB,  -- {sync_error, identity_consistency, ...}
    created_at TIMESTAMP
);

-- 缓存表（可选，用于去重）
CREATE TABLE media_cache (
    key VARCHAR(256) PRIMARY KEY,
    type VARCHAR(32),  -- "audio", "video_frames", "musetalk_output"
    path VARCHAR(256),
    size_bytes BIGINT,
    created_at TIMESTAMP,
    ttl_days INT  -- 过期时间
);
```

---

## 技术栈（最终确认）

| 功能 | 技术 |
|---|---|
| **文本转语音** | CosyVoice |
| **语音识别+对齐** | WhisperX |
| **嘴型同步** | MuseTalk (官方或开源版本) |
| **人像分割** | RVM |
| **背景处理** | OpenCV, PIL (静态) + SDXL API (动态，v2) |
| **视频处理** | FFmpeg, OpenCV, MediaInfo |
| **后端 API** | FastAPI |
| **异步任务** | Celery + Redis |
| **数据库** | PostgreSQL |
| **文件存储** | 本地文件系统 (minio 可选) |
| **前端** | React / Next.js (简单版本) |
| **部署** | Docker Compose |

---

## 硬件要求

### 开发 / 求职 Demo

| 配置 | 最低 | 推荐 |
|---|---|---|
| GPU | RTX 4060 12GB | RTX 4090 24GB |
| 内存 | 32GB | 64GB |
| SSD | 500GB | 1TB |

**可实现内容**：
- 本地跑 MuseTalk + RVM + FFmpeg
- TTS 用云端 API（CosyVoice Free or 付费）
- 背景生成先 Mock 或用预制图
- 单路推理，无需多卡

---

## 已知风险与缓解

### 风险 1: MuseTalk 帧间稳定性（嘴部抖动）

**现象**：重绘的嘴部逐帧有细微差异，形成"颤抖"。

**缓解**：
- MuseTalk 模型内置了帧间一致性约束，通常不严重
- 如有问题，可在 RVM 后加帧间平滑（时间滤波 mask）
- 参考：`smooth_temporal(masks, window=3)`

---

### 风险 2: 原始视频质量不足（模糊、遮挡、光线差）

**现象**：输入视频本身清晰度低或人脸被遮挡，导致 RVM 分割失败。

**缓解**：
- 在素材接入阶段严格检测：清晰度评分 > 阈值、人脸无遮挡
- 提供用户指引：录制时保持正面、光线充足、无配饰遮挡
- 失败时给出明确错误提示

---

### 风险 3: 不同语言、口音的音素对齐偏差

**现象**：某些语言（如英文）的音素边界可能不准，导致口型"错位"。

**缓解**：
- WhisperX 对主流语言（中英日韩西法）有较好支持，小语种精度较低
- v1 限制支持语言：中文、英文、日文、韩文
- 如有偏差，可在后处理中微调音素边界

---

### 风险 4: 实时性承诺无法达成

**现象**："实时"意指直播流式（<500ms 端到端延迟），但实际系统是批处理。

**缓解**：
- 明确两个目标档次：**离线高清**（主）+ **准实时预览**（辅）
- 离线高清：单个 30s 片段约 2~3 分钟生成时间，可接受
- 准实时预览：按句生成，单句 < 5s，分句播放造成伪连续效果

---

### 风险 5: 背景替换边缘质量（毛发、半透明区域）

**现象**：头发丝、肩膀边缘被切割，背景和前景色调不搭。

**缓解**：
- RVM 的 Alpha mask 本身有边缘羽化，大多数场景效果尚可
- SAM2（可选）用于复杂边缘，但推理成本高（v2 考虑）
- 色调匹配：背景生成或选择时考虑光线、饱和度与原视频一致

---

### 风险 6: GPU 显存溅射（OOM）

**现象**：MuseTalk 等模型加载失败或显存不足。

**缓解**：
- MuseTalk 官方版本 ~6GB 显存，量化版本可降至 4GB
- 分帧批处理：不全帧一次性加载，改为分 batch（如 8 帧一个）
- 显存监控与重试机制：Celery 任务失败自动重试

---

## 部署与运行

### 开发环境启动

```bash
# 1. 克隆代码
git clone <repo> && cd digital-human

# 2. 环境准备
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 下载模型
python scripts/download_models.py  # MuseTalk, RTS, RVM

# 4. 启动 Redis
docker run -d -p 6379:6379 redis:latest

# 5. 启动 Celery Worker
celery -A app.tasks worker --loglevel=info

# 6. 启动 FastAPI 服务
uvicorn app.main:app --reload --port 8000

# 7. Web 前端（可选）
cd frontend && npm install && npm run dev
```

### 生成视频（CLI）

```bash
python scripts/generate.py \
  --video input.mp4 \
  --text "你好，我是数字人" \
  --language zh \
  --background static \
  --bg_image bg.jpg \
  --output output.mp4
```

---

## 参考资源

- **MuseTalk**: https://github.com/Zunelőször/MuseTalk
- **WhisperX**: https://github.com/m-bain/whisperx
- **RVM**: https://github.com/PeterL1n/RobustVideoMatting
- **CosyVoice**: https://github.com/microsoft/CosyVoice (or huggingface)
- **FastAPI**: https://fastapi.tiangolo.com
- **Celery**: https://docs.celeryproject.io

---

## 总结

这是一个**系统工程 + 模型集成**的求职项目。核心亮点：

1. **聚焦**：视频驱动路线，砍掉不必要的图像驱动复杂性
2. **可交付**：清晰的 MVP 分层，每阶段都能演示
3. **可维护**：模块化接口，模型可插拔（本地/云端/Mock）
4. **可靠**：任务编排 + 缓存 + 重试，生产级别的容错
5. **对标**：对标业界 EchoMimic / HeyGen 的最小功能集，体现系统设计能力

关键是**先跑通 MVP-0，再考虑 v2 优化**。
