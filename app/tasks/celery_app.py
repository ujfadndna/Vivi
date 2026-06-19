"""Celery 应用。无 Redis 时设 CELERY_TASK_ALWAYS_EAGER=true 同步执行。"""
from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "digital_human",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    result_extended=True,
)

# 确保任务被注册
celery_app.autodiscover_tasks(["app.tasks"])
