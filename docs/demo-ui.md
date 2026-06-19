# 数字人 Demo UI

本文档说明 `app/static/demo.html` 的启动方式、接口对应关系和已知限制。该页面是单文件实现，不依赖外部 CDN，使用原生 HTML、CSS 和 JavaScript 调用本地 FastAPI 服务。

## 启动方式

先启动后端服务：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

推荐把页面作为后端同源静态资源访问，避免浏览器 CORS 限制。示例做法是在 FastAPI 中挂载 `app/static` 后访问：

```python
from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="app/static"), name="static")
```

然后打开：

```text
http://localhost:8000/static/demo.html
```

也可以使用独立静态文件服务：

```powershell
cd app/static
python -m http.server 5173
```

然后打开：

```text
http://localhost:5173/demo.html
```

页面默认调用 `http://localhost:8000`。如果后端端口不同，可以在页面的 API 输入框中修改，也可以通过 URL 参数指定：

```text
http://localhost:5173/demo.html?api=http://localhost:8000
```

使用 `python -m http.server` 时，页面来源是 `localhost:5173`，后端是 `localhost:8000`。如果后端未开启 CORS，浏览器会拦截跨域请求；此时请改用同源静态挂载方式，或在 FastAPI 中配置允许本地演示来源的 CORS。

## API 对应关系

页面启动后会先检查服务健康状态：

```text
GET /health
```

点击“提交生成”后，页面会提交文本生成任务：

```http
POST /tasks
Content-Type: application/json

{
  "text": "你好，这是一段测试文字",
  "background_type": "static"
}
```

期望响应：

```json
{
  "task_id": "xxx"
}
```

拿到 `task_id` 后，页面会定时轮询任务状态：

```text
GET /tasks/{task_id}
```

期望响应：

```json
{
  "task_id": "xxx",
  "status": "processing",
  "progress": 0.45,
  "stages": {
    "tts": 1,
    "musetalk": 0.4,
    "rvm": 0,
    "compose": 0
  },
  "output_url": "/outputs/xxx.mp4"
}
```

页面会展示总进度和四个阶段：

```text
TTS / MuseTalk / RVM / 合成
```

阶段字段支持数字进度，也兼容常见状态字符串，例如 `pending`、`processing`、`completed`、`failed`。如果后端暂时没有返回 `stages`，页面会根据总进度粗略推导阶段展示。

当任务状态为 `completed` 时，页面会把视频地址设置到 `video` 标签：

```text
GET /outputs/{filename}
```

如果 `output_url` 是 `/outputs/xxx.mp4`，页面会自动拼接为：

```text
http://localhost:8000/outputs/xxx.mp4
```

当任务状态为 `failed`，或轮询接口返回错误时，页面会停止轮询并显示错误信息。

## 已知限制

- 页面只做展示层，不包含任务取消、历史任务列表、用户登录和权限控制。
- 生成过程通常耗时较长，页面采用轮询方式更新状态，不支持实时流式视频预览。
- 自动播放受浏览器策略影响；如果浏览器阻止自动播放，视频仍会加载到播放器中，需要手动点击播放。
- 页面默认按 `/tasks` 和 `/tasks/{task_id}` 调用接口；如果后端实际路径不同，需要调整 `demo.html` 中的接口路径或增加后端适配路由。
- 独立静态服务和后端服务分属不同 origin，可能需要后端启用 CORS。
- `stages` 字段没有统一细粒度规范时，页面只能根据返回值做近似展示。
