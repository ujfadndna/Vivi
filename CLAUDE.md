# CLAUDE.md

本项目为 Her —— 可控 2D 数字人系统。详细协作规则见 [`AGENTS.md`](AGENTS.md)，本文件补充 Claude-specific 的速查信息。

## 项目速览

- **项目类型**：Python FastAPI 后端服务
- **核心技术栈**：FastAPI + Pydantic Settings + Celery + LangGraph + LangChain
- **模型后端**：可插拔（mock / local / indextts / qwen3 / cloud），通过 `app/services/base.py` 的 `@register()` 注册
- **95 个文件，~10,759 行 Python**

## 修改代码前

必须读 [`AGENTS.md`](AGENTS.md) 的「任务入口」章节列出的 6 个关键文件，尤其是：
- `docs/plan.md` — 当前里程碑状态和已知遗留问题
- `app/config.py` — 所有配置入口

## 禁止事项

- 不要顺手重构与任务无关的模块
- 不要格式化整个文件（只动改到的区域）
- 不要修改 `requirements-*.txt` 除非明确要求
- 不要把个人路径（如 `C:/Users/<you>/...`）写进 config 默认值
- 不要把 `.env`、模型权重、workspace 产物提交进 git
