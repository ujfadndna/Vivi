export type WarmupStatus = {
  tts?: {
    status?: string;
    backend?: string;
    error?: string | null;
  };
  flashhead?: {
    status?: string;
    worker_ready?: boolean;
    avatar_image_path?: string;
    error?: string | null;
    inference_warmup?: {
      status?: string;
      elapsed_sec?: number;
      error?: string | null;
    };
  };
};

export type HealthPayload = {
  status: string;
  warmup?: WarmupStatus;
  profile?: {
    deployment_mode?: "mock" | "remote" | "local";
    render_api_url?: string | null;
  };
};

export type ProfilePayload = {
  profile_id: string;
  name?: string;
  deployment_mode?: "mock" | "remote" | "local";
  avatar?: {
    avatar_url?: string;
    image_set?: boolean;
    render_backend?: string;
    render_api_url?: string;
  };
  voice?: {
    voice_set?: boolean;
    tts_backend?: string;
    tts_api_url?: string;
  };
  llm?: {
    base_url?: string;
    model?: string;
    api_key_set?: boolean;
  };
  warmup?: WarmupStatus;
};

export type SubtitleSegment = {
  text: string;
  start_sec: number;
  end_sec: number;
};

export type ChatResponse = {
  reply?: string;
  video_urls?: string[];
  subtitle_segments?: SubtitleSegment[];
  duration_sec?: number;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};
