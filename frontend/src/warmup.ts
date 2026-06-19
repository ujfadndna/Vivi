import type { HealthPayload } from "./types";

export function isDigitalHumanReady(payload?: HealthPayload | null): boolean {
  const warmup = payload?.warmup || {};
  const tts = warmup.tts || {};
  const profile = payload?.profile || {};
  const mode = profile.deployment_mode || "mock";
  if (mode === "mock") return tts.status === "ok";
  if (mode === "remote" && profile.render_api_url) return tts.status === "ok";

  const flashhead = warmup.flashhead || {};
  const inference = flashhead.inference_warmup || {};
  return (
    tts.status === "ok" &&
    flashhead.worker_ready === true &&
    flashhead.status === "ok" &&
    inference.status === "ok"
  );
}

export function warmupFailureMessage(payload?: HealthPayload | null): string {
  const warmup = payload?.warmup || {};
  const tts = warmup.tts || {};
  const flashhead = warmup.flashhead || {};
  const inference = flashhead.inference_warmup || {};
  if (tts.status === "failed") return "语音服务初始化失败，请刷新重试";
  if (flashhead.status === "failed") return "数字人头像初始化失败，请刷新重试";
  if (inference.status === "failed") return "数字人推理初始化失败，请刷新重试";
  return "";
}

export function warmupProgressMessage(payload?: HealthPayload | null): string {
  if (!payload) return "正在连接后端服务...";
  const warmup = payload.warmup || {};
  const tts = warmup.tts || {};
  const profile = payload.profile || {};
  const mode = profile.deployment_mode || "mock";
  const flashhead = warmup.flashhead || {};
  const inference = flashhead.inference_warmup || {};

  if (tts.status !== "ok") {
    return tts.status === "started" ? "正在预热语音服务..." : "正在检查语音服务...";
  }
  if (mode === "mock") return "可以开始聊天";
  if (mode === "remote" && profile.render_api_url) return "可以开始聊天";
  if (flashhead.worker_ready !== true) return "正在启动数字人渲染进程...";
  if (flashhead.status !== "ok") {
    return flashhead.status === "started" ? "正在准备数字人头像..." : "正在检查数字人头像...";
  }
  if (inference.status !== "ok") {
    return inference.status === "started"
      ? "正在预热数字人推理，首次启动约需 1 分钟..."
      : "正在等待数字人推理预热...";
  }
  return "可以开始聊天";
}
