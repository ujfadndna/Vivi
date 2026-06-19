import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Mic,
  Play,
  Save,
  Send,
  Settings,
  Upload,
  UserRound,
  X
} from "lucide-react";
import {
  getHealth,
  getProfile,
  saveBackendConfig,
  saveLlmConfig,
  sendChat,
  uploadAvatar,
  uploadVoice
} from "./api";
import type { ChatMessage, HealthPayload, ProfilePayload, SubtitleSegment } from "./types";
import {
  isDigitalHumanReady,
  warmupFailureMessage,
  warmupProgressMessage
} from "./warmup";

const avatarUrl = "/api/v1/profile/avatar";

type SaveState = "idle" | "saving" | "ok" | "error";

export function App() {
  const [profile, setProfile] = useState<ProfilePayload | null>(null);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [status, setStatus] = useState("正在连接数字人服务...");
  const [subtitle, setSubtitle] = useState("正在连接数字人服务...");
  const [text, setText] = useState("");
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [isDrawerOpen, setDrawerOpen] = useState(false);
  const [isSending, setSending] = useState(false);
  const [videoUrl, setVideoUrl] = useState("");
  const [segments, setSegments] = useState<SubtitleSegment[]>([]);
  const [showPlayButton, setShowPlayButton] = useState(false);
  const [avatarStamp, setAvatarStamp] = useState(Date.now());
  const [avatarState, setAvatarState] = useState<SaveState>("idle");
  const [voiceState, setVoiceState] = useState<SaveState>("idle");
  const [llmState, setLlmState] = useState<SaveState>("idle");
  const [backendState, setBackendState] = useState<SaveState>("idle");
  const [voiceMessage, setVoiceMessage] = useState("未设置");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [deploymentMode, setDeploymentMode] = useState<"mock" | "remote" | "local">("mock");
  const [ttsBackend, setTtsBackend] = useState("");
  const [ttsApiUrl, setTtsApiUrl] = useState("");
  const [renderBackend, setRenderBackend] = useState("flashhead");
  const [renderApiUrl, setRenderApiUrl] = useState("");

  const playerRef = useRef<HTMLVideoElement | null>(null);
  const backgroundVideoRef = useRef<HTMLVideoElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const ready = isDigitalHumanReady(health);
  const warmupMessage = useMemo(() => {
    return warmupFailureMessage(health) || warmupProgressMessage(health);
  }, [health]);
  const avatarCacheUrl = `${avatarUrl}?t=${avatarStamp}`;

  const loadProfile = useCallback(async () => {
    try {
      const payload = await getProfile();
      setProfile(payload);
      setLlmBaseUrl(payload.llm?.base_url || "");
      setLlmModel(payload.llm?.model || "");
      setVoiceMessage(payload.voice?.voice_set ? "已设置" : "未设置");
      setDeploymentMode(payload.deployment_mode || "mock");
      setTtsBackend(payload.voice?.tts_backend || "");
      setTtsApiUrl(payload.voice?.tts_api_url || "");
      setRenderBackend(payload.avatar?.render_backend || "flashhead");
      setRenderApiUrl(payload.avatar?.render_api_url || "");
      setAvatarStamp(Date.now());
    } catch {
      setStatus("Profile 加载失败");
    }
  }, []);

  const pollHealth = useCallback(async () => {
    try {
      const payload = await getHealth();
      setHealth(payload);
      const failed = warmupFailureMessage(payload);
      const message = failed || warmupProgressMessage(payload);
      setStatus(message);
      if (!isSending && !videoUrl) setSubtitle(message);
    } catch {
      setHealth(null);
      setStatus("正在连接后端服务...");
      if (!isSending && !videoUrl) setSubtitle("正在连接后端服务...");
    }
  }, [isSending, videoUrl]);

  useEffect(() => {
    if (window.location.pathname === "/") {
      window.history.replaceState(null, "", "/chat");
    }
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    pollHealth();
    const timer = window.setInterval(pollHealth, ready ? 5000 : 1000);
    return () => window.clearInterval(timer);
  }, [pollHealth, ready]);

  useEffect(() => {
    if (ready && !isSending && !videoUrl) {
      setStatus("可以开始聊天");
      setSubtitle("可以开始聊天");
      inputRef.current?.focus();
    }
  }, [ready, isSending, videoUrl]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    const handleTime = () => {
      const current = segments.find(
        (segment) => player.currentTime >= Number(segment.start_sec) && player.currentTime < Number(segment.end_sec)
      );
      if (current) setSubtitle(current.text);
    };
    const handleEnded = () => {
      setVideoUrl("");
      setSegments([]);
      setShowPlayButton(false);
      setStatus("可以开始聊天");
      setSubtitle("可以开始聊天");
    };
    const handlePlaying = () => {
      setShowPlayButton(false);
      setStatus("播放中");
      backgroundVideoRef.current?.play().catch(() => undefined);
    };
    player.addEventListener("timeupdate", handleTime);
    player.addEventListener("ended", handleEnded);
    player.addEventListener("playing", handlePlaying);
    return () => {
      player.removeEventListener("timeupdate", handleTime);
      player.removeEventListener("ended", handleEnded);
      player.removeEventListener("playing", handlePlaying);
    };
  }, [segments]);

  const handleSend = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || isSending) return;
    if (!ready) {
      setStatus("数字人仍在初始化");
      setSubtitle(warmupMessage);
      return;
    }

    setSending(true);
    setText("");
    setVideoUrl("");
    setSegments([]);
    setShowPlayButton(false);
    setStatus("正在生成回复和视频...");
    setSubtitle("正在生成回复和视频...");

    try {
      const payload = await sendChat(trimmed, history);
      const reply = payload.reply || "视频待播放";
      const nextSegments = payload.subtitle_segments?.length
        ? payload.subtitle_segments
        : [{ text: reply, start_sec: 0, end_sec: payload.duration_sec || 3600 }];
      const newMessages: ChatMessage[] = [
        { role: "user", content: trimmed },
        { role: "assistant", content: reply }
      ];
      setHistory((current) => [...current, ...newMessages].slice(-16));
      setSegments(nextSegments);
      setSubtitle(nextSegments[0]?.text || reply);

      const firstVideo = payload.video_urls?.[0] || "";
      if (firstVideo) {
        setVideoUrl(firstVideo);
        setStatus("视频已生成，正在加载...");
        window.setTimeout(() => {
          playerRef.current?.play().catch(() => {
            setShowPlayButton(true);
            setStatus("视频已就绪，点击播放");
          });
        }, 0);
      } else {
        setStatus("视频生成失败");
        setSubtitle(reply);
      }
    } catch (error) {
      if (error instanceof Error && error.message === "DIGITAL_HUMAN_WARMING_UP") {
        await pollHealth();
        setStatus("数字人仍在预热");
        setSubtitle("数字人仍在预热，请稍候...");
      } else {
        setStatus(error instanceof Error ? error.message : "请求失败");
        setSubtitle("请求失败，请稍后重试");
      }
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  };

  const handleAvatarUpload = async (file?: File) => {
    if (!file) return;
    setAvatarState("saving");
    try {
      await uploadAvatar(file);
      setAvatarState("ok");
      setAvatarStamp(Date.now());
      await pollHealth();
    } catch {
      setAvatarState("error");
    }
  };

  const handleVoiceUpload = async (file?: File) => {
    if (!file) return;
    setVoiceState("saving");
    try {
      const payload = await uploadVoice(file);
      setVoiceState("ok");
      setVoiceMessage(`已设置 ${Number(payload.duration_sec || 0).toFixed(1)}s`);
    } catch {
      setVoiceState("error");
      setVoiceMessage("上传失败");
    }
  };

  const handleSaveLlm = async () => {
    setLlmState("saving");
    try {
      const payload = await saveLlmConfig({
        base_url: llmBaseUrl,
        model: llmModel,
        api_key: llmApiKey || undefined
      });
      setLlmApiKey("");
      setProfile((current) =>
        current
          ? {
              ...current,
              llm: { ...(current.llm || {}), base_url: llmBaseUrl, model: llmModel, api_key_set: payload.api_key_set }
            }
          : current
      );
      setLlmState("ok");
    } catch {
      setLlmState("error");
    }
  };

  const handleSaveBackends = async () => {
    setBackendState("saving");
    try {
      await saveBackendConfig({
        deployment_mode: deploymentMode,
        tts_backend: ttsBackend,
        tts_api_url: ttsApiUrl,
        render_backend: renderBackend,
        render_api_url: renderApiUrl
      });
      setBackendState("ok");
      await loadProfile();
    } catch {
      setBackendState("error");
    }
  };

  return (
    <main className="app-shell">
      {videoUrl ? (
        <video ref={backgroundVideoRef} className="backdrop-video" src={videoUrl} muted playsInline loop />
      ) : null}
      <div className="shade" />

      <header className="topbar">
        <div className="status-pill" title="GET /health">
          <span className={ready ? "pulse ok" : "pulse"} />
          <span>{status}</span>
        </div>
        <button className="icon-action" type="button" onClick={() => setDrawerOpen(true)} title="设置" aria-label="设置">
          <Settings size={18} />
        </button>
      </header>

      <section className="digital-human" aria-live="polite">
        <video
          ref={playerRef}
          className={videoUrl ? "main-video visible" : "main-video"}
          src={videoUrl}
          playsInline
          preload="metadata"
        />
        {!videoUrl ? (
          <div className="avatar-standin" style={{ backgroundImage: `url("${avatarCacheUrl}")` }}>
            <UserRound size={92} />
          </div>
        ) : null}
      </section>

      <div className="subtitle">{subtitle}</div>

      {showPlayButton ? (
        <button className="play-button" type="button" onClick={() => playerRef.current?.play().catch(() => undefined)}>
          <Play size={18} />
          播放视频
        </button>
      ) : null}

      {!ready ? (
        <div className="warmup-overlay" role="status" aria-live="polite">
          <Loader2 className="spin" size={54} />
          <span>{warmupMessage}</span>
        </div>
      ) : null}

      <form className="composer" onSubmit={handleSend}>
        <input
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="说点什么..."
          disabled={!ready || isSending}
          autoComplete="off"
        />
        <button type="submit" disabled={!ready || isSending || !text.trim()} title="发送">
          {isSending ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
          发送
        </button>
      </form>

      <aside className={isDrawerOpen ? "settings-drawer open" : "settings-drawer"} aria-label="设置">
        <div className="drawer-head">
          <h1>设置</h1>
          <button className="icon-action" type="button" onClick={() => setDrawerOpen(false)} title="关闭" aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        <section className="panel-section">
          <h2>数字人参考图</h2>
          <div className="avatar-preview" style={{ backgroundImage: `url("${avatarCacheUrl}")` }} />
          <label className="file-button">
            <Upload size={17} />
            上传头像
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => handleAvatarUpload(event.target.files?.[0])} />
          </label>
          <SaveHint state={avatarState} okText="已上传，正在重新预热" />
        </section>

        <section className="panel-section">
          <h2>声音参考音频</h2>
          <label className="file-button">
            <Mic size={17} />
            上传音频
            <input type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/flac" onChange={(event) => handleVoiceUpload(event.target.files?.[0])} />
          </label>
          <p className="field-note">{voiceMessage}</p>
          <SaveHint state={voiceState} okText="已上传" />
        </section>

        <section className="panel-section">
          <h2>大模型 API</h2>
          <label className="field">
            Base URL
            <input value={llmBaseUrl} onChange={(event) => setLlmBaseUrl(event.target.value)} />
          </label>
          <label className="field">
            Model
            <input value={llmModel} onChange={(event) => setLlmModel(event.target.value)} />
          </label>
          <label className="field">
            API Key
            <input
              value={llmApiKey}
              onChange={(event) => setLlmApiKey(event.target.value)}
              type="password"
              placeholder={profile?.llm?.api_key_set ? "已保存，输入新 key 可替换" : ""}
            />
          </label>
          <button className="secondary-command" type="button" onClick={handleSaveLlm}>
            <Save size={17} />
            保存
          </button>
          <SaveHint state={llmState} okText="已保存" />
        </section>

        <section className="panel-section">
          <h2>模型服务</h2>
          <label className="field">
            部署模式
            <select value={deploymentMode} onChange={(event) => setDeploymentMode(event.target.value as "mock" | "remote" | "local")}>
              <option value="mock">mock</option>
              <option value="remote">remote</option>
              <option value="local">local</option>
            </select>
          </label>
          <label className="field">
            TTS Backend
            <input value={ttsBackend} onChange={(event) => setTtsBackend(event.target.value)} />
          </label>
          <label className="field">
            TTS API URL
            <input value={ttsApiUrl} onChange={(event) => setTtsApiUrl(event.target.value)} />
          </label>
          <label className="field">
            Render Backend
            <input value={renderBackend} onChange={(event) => setRenderBackend(event.target.value)} />
          </label>
          <label className="field">
            Render API URL
            <input value={renderApiUrl} onChange={(event) => setRenderApiUrl(event.target.value)} />
          </label>
          <button className="secondary-command" type="button" onClick={handleSaveBackends}>
            <Save size={17} />
            保存
          </button>
          <SaveHint state={backendState} okText="已保存" />
        </section>
      </aside>
    </main>
  );
}

function SaveHint({ state, okText }: { state: SaveState; okText: string }) {
  if (state === "idle") return null;
  if (state === "saving") {
    return (
      <p className="save-hint">
        <Loader2 className="spin" size={15} />
        正在保存
      </p>
    );
  }
  if (state === "ok") {
    return (
      <p className="save-hint ok">
        <CheckCircle2 size={15} />
        {okText}
      </p>
    );
  }
  return <p className="save-hint error">操作失败</p>;
}
