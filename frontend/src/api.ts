import type { ChatMessage, ChatResponse, HealthPayload, ProfilePayload } from "./types";

async function parseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = String(payload.detail || detail);
    } catch {
      // keep fallback detail
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function getHealth(): Promise<HealthPayload> {
  const response = await fetch("/health", { cache: "no-store" });
  return parseJson<HealthPayload>(response);
}

export async function getProfile(): Promise<ProfilePayload> {
  const response = await fetch("/api/v1/profile", { cache: "no-store" });
  return parseJson<ProfilePayload>(response);
}

export async function uploadAvatar(file: File): Promise<ProfilePayload> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/v1/profile/avatar", { method: "POST", body });
  return parseJson<ProfilePayload>(response);
}

export async function uploadVoice(file: File): Promise<{ duration_sec?: number; sample_rate?: number }> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch("/api/v1/profile/voice", { method: "POST", body });
  return parseJson(response);
}

export async function saveLlmConfig(payload: {
  base_url: string;
  model: string;
  api_key?: string;
}): Promise<{ api_key_set?: boolean }> {
  const response = await fetch("/api/v1/profile/llm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseJson(response);
}

export async function saveBackendConfig(payload: {
  deployment_mode: "mock" | "remote" | "local";
  tts_backend: string;
  tts_api_url?: string;
  render_backend: string;
  render_api_url?: string;
}): Promise<unknown> {
  const response = await fetch("/api/v1/profile/backends", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return parseJson(response);
}

export async function sendChat(text: string, history: ChatMessage[]): Promise<ChatResponse> {
  const body = new FormData();
  body.append("text", text);
  body.append("history", JSON.stringify(history.slice(-16)));
  const response = await fetch("/chat/simple", { method: "POST", body });
  if (response.status === 503) {
    throw new Error("DIGITAL_HUMAN_WARMING_UP");
  }
  return parseJson<ChatResponse>(response);
}
