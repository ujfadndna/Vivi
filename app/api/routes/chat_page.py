"""Simple browser digital-human chat page."""
from __future__ import annotations

import json
import re
from contextlib import ExitStack
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import profile_store
from app.config import settings
from app.warmup import is_digital_human_ready

router = APIRouter(tags=["chat"])

_MAX_HISTORY_MESSAGES = 16
_MAX_HISTORY_CONTENT_CHARS = 500
_MOCK_REPLY_PREFIX = "我听到了。我们先慢慢来。"

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Clara</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;width:100%;height:100%;overflow:hidden}
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#050607;color:#f2f2f0;letter-spacing:0}
button,input,select{font:inherit}
.stage{position:relative;width:100vw;height:100vh;min-height:100svh;overflow:hidden;background:radial-gradient(circle at 50% 32%,rgba(70,68,62,.34),rgba(5,6,7,.08) 35%,rgba(5,6,7,0) 58%),#050607}
.background,.bg-video{position:absolute;inset:-18px;width:calc(100% + 36px);height:calc(100% + 36px);object-fit:cover;filter:blur(26px);transform:scale(1.08);opacity:.62}
.background{background:center/cover no-repeat}
.bg-video{display:none}
.bg-video.visible{display:block}
.shade{position:absolute;inset:0;background:linear-gradient(90deg,rgba(0,0,0,.74),rgba(0,0,0,.12) 42%,rgba(0,0,0,.58)),linear-gradient(0deg,rgba(0,0,0,.82),rgba(0,0,0,0) 38%,rgba(0,0,0,.42))}
.main-video,.idle{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:clamp(14px,2.5vw,36px) clamp(10px,2vw,28px) clamp(136px,18vh,210px)}
.main-video video{width:100%;height:100%;object-fit:contain;display:none;filter:drop-shadow(0 18px 48px rgba(0,0,0,.5))}
.main-video video.visible{display:block}
.idle-video{width:100%;height:100%;object-fit:contain;display:none;filter:drop-shadow(0 18px 48px rgba(0,0,0,.5))}
.idle-video.visible{display:block}
.idle-avatar{width:min(84vw,calc((100vh - 170px)*.62));max-height:calc(100vh - 170px);aspect-ratio:3/4;background:center/contain no-repeat;filter:drop-shadow(0 18px 48px rgba(0,0,0,.55));animation:breathe 5.8s ease-in-out infinite;transform-origin:50% 74%}
.idle-avatar.hidden{display:none}
.idle::before{content:"";position:absolute;width:58vmin;height:58vmin;border-radius:50%;background:radial-gradient(circle,rgba(238,214,170,.18),rgba(255,255,255,0) 64%);top:18%;left:50%;transform:translateX(-50%);animation:glow 7s ease-in-out infinite}
.idle.hidden{display:none}
.status{position:absolute;top:max(16px,env(safe-area-inset-top));left:max(16px,env(safe-area-inset-left));display:flex;align-items:center;gap:9px;padding:8px 12px;border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(8,9,10,.42);backdrop-filter:blur(14px);font-size:13px;color:#ddd}
.settings-toggle{position:absolute;top:max(16px,env(safe-area-inset-top));right:max(16px,env(safe-area-inset-right));z-index:14;width:auto;height:38px;padding:0 14px;border:1px solid rgba(255,255,255,.16);background:rgba(8,9,10,.48);color:#f3f0e8;backdrop-filter:blur(14px)}
.settings-drawer{position:absolute;top:0;right:0;z-index:30;width:min(420px,100vw);height:100%;padding:18px;background:rgba(12,13,14,.94);border-left:1px solid rgba(255,255,255,.14);box-shadow:-18px 0 42px rgba(0,0,0,.42);transform:translateX(100%);transition:transform .22s ease;overflow:auto}
.settings-drawer.open{transform:translateX(0)}
.settings-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}
.settings-title{font-size:18px;font-weight:720}
.icon-button{width:38px;height:38px;padding:0;background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.14)}
.settings-section{padding:14px 0;border-top:1px solid rgba(255,255,255,.11)}
.settings-section h2{margin:0 0 10px;font-size:14px;font-weight:720;color:#f5efe2}
.settings-preview{width:92px;height:122px;border-radius:8px;background:center/cover no-repeat rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.13);margin-bottom:10px}
.field{display:flex;flex-direction:column;gap:6px;margin:9px 0;color:rgba(255,255,255,.74);font-size:12px}
.field input,.field select{height:38px;border:1px solid rgba(255,255,255,.13);border-radius:6px;background:rgba(255,255,255,.08);color:#fff;padding:0 10px;outline:0}
.field select option{color:#111}
.settings-row{display:flex;gap:8px;align-items:center}
.settings-row input{min-width:0}
.secondary-button{height:38px;background:rgba(215,183,106,.18);color:#f7e7bb;border:1px solid rgba(215,183,106,.35);padding:0 12px}
.settings-note{min-height:18px;font-size:12px;color:#cfc8bc}
details summary{cursor:pointer;color:#f5efe2;font-weight:720;font-size:14px}
.dot{width:8px;height:8px;border-radius:50%;background:#d7b76a;box-shadow:0 0 18px rgba(215,183,106,.75)}
.subtitle{position:absolute;left:50%;bottom:calc(92px + env(safe-area-inset-bottom));transform:translateX(-50%);width:min(820px,calc(100vw - 28px));min-height:48px;display:flex;align-items:center;justify-content:center;text-align:center;padding:11px 18px;border-radius:8px;background:rgba(0,0,0,.44);backdrop-filter:blur(14px);font-size:clamp(16px,2.2vw,24px);line-height:1.45;color:#fff;text-shadow:0 1px 4px rgba(0,0,0,.8)}
.subtitle:empty{display:none}
.play-button{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:12;width:auto;min-width:126px;padding:0 18px;border:1px solid rgba(255,255,255,.22);background:rgba(215,183,106,.92);box-shadow:0 12px 38px rgba(0,0,0,.35)}
.play-button.hidden{display:none}
.composer{position:absolute;left:50%;bottom:max(18px,env(safe-area-inset-bottom));transform:translateX(-50%);width:min(780px,calc(100vw - 24px));display:grid;grid-template-columns:1fr 86px;gap:10px;padding:10px;border:1px solid rgba(255,255,255,.13);border-radius:8px;background:rgba(10,11,12,.68);backdrop-filter:blur(18px)}
input{width:100%;height:48px;border:0;border-radius:6px;background:rgba(255,255,255,.1);color:#fff;padding:0 14px;outline:0}
input::placeholder{color:rgba(255,255,255,.58)}
input[type=file]{height:auto;padding:9px 10px}
button{height:48px;border:0;border-radius:6px;background:#d7b76a;color:#111;cursor:pointer;font-weight:650}
button:disabled,input:disabled{opacity:.58}
#startupOverlay{position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;background:rgba(4,5,6,.86);backdrop-filter:blur(18px)}
#startupOverlay.hidden{display:none}
.startup-box{display:flex;flex-direction:column;align-items:center;gap:18px;color:#f7f4ed;text-align:center;font-size:16px}
.spinner{width:54px;height:54px;border-radius:50%;border:4px solid rgba(255,255,255,.16);border-top-color:#d7b76a;animation:spin 1s linear infinite}
@keyframes breathe{0%,100%{transform:scale(1) translateY(0)}50%{transform:scale(1.012) translateY(-4px)}}
@keyframes glow{0%,100%{opacity:.5;transform:translateX(-50%) scale(.98)}50%{opacity:.82;transform:translateX(-50%) scale(1.04)}}
@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:640px){
  .main-video,.idle{padding:8px 4px 150px}
  .idle-avatar{width:min(94vw,calc((100vh - 160px)*.7));max-height:calc(100vh - 160px)}
  .subtitle{bottom:calc(94px + env(safe-area-inset-bottom));font-size:16px;min-height:44px;padding:9px 12px}
  .composer{grid-template-columns:1fr 70px}
}
</style>
</head>
<body>
<main class="stage">
  <div id="bg" class="background"></div>
  <video id="bgVideo" class="bg-video" muted playsinline loop preload="metadata"></video>
  <div class="shade"></div>
  <section id="idle" class="idle" aria-hidden="true">
    <video id="idleVideo" class="idle-video" muted playsinline loop preload="auto"></video>
    <div id="idleAvatar" class="idle-avatar"></div>
  </section>
  <section class="main-video"><video id="v" playsinline preload="metadata"></video></section>
  <div class="status"><span class="dot"></span><span id="statusText">正在初始化...</span></div>
  <button id="settingsToggle" class="settings-toggle" type="button">设置</button>
  <div id="subtitle" class="subtitle">正在连接数字人服务...</div>
  <button id="playButton" class="play-button hidden" type="button">播放视频</button>
  <form id="composer" class="composer">
    <input id="t" placeholder="说点什么..." autocomplete="off" autofocus>
    <button id="b" type="submit">发送</button>
  </form>
  <div id="startupOverlay" role="status" aria-live="polite">
    <div class="startup-box"><div class="spinner"></div><div id="startupText">正在启动数字人...</div></div>
  </div>
  <aside id="settingsDrawer" class="settings-drawer" aria-label="设置">
    <div class="settings-head">
      <div class="settings-title">设置</div>
      <button id="settingsClose" class="icon-button" type="button" aria-label="关闭">×</button>
    </div>
    <section class="settings-section">
      <h2>数字人参考图</h2>
      <div id="avatarPreview" class="settings-preview"></div>
      <div class="settings-row">
        <input id="avatarFile" type="file" accept="image/png,image/jpeg,image/webp">
        <button id="avatarUpload" class="secondary-button" type="button">上传</button>
      </div>
      <div id="avatarStatus" class="settings-note"></div>
    </section>
    <section class="settings-section">
      <h2>声音参考音频</h2>
      <div class="settings-row">
        <input id="voiceFile" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/flac">
        <button id="voiceUpload" class="secondary-button" type="button">上传</button>
      </div>
      <div id="voiceStatus" class="settings-note">未设置</div>
    </section>
    <section class="settings-section">
      <h2>大模型 API</h2>
      <label class="field">Base URL<input id="llmBaseUrl" autocomplete="off"></label>
      <label class="field">Model<input id="llmModel" autocomplete="off"></label>
      <label class="field">API Key<input id="llmApiKey" type="password" autocomplete="off"></label>
      <button id="llmSave" class="secondary-button" type="button">保存</button>
      <div id="llmStatus" class="settings-note"></div>
    </section>
    <section class="settings-section">
      <details id="backendDetails">
        <summary>高级模型服务</summary>
        <label class="field">部署模式<select id="deploymentMode"><option value="mock">mock</option><option value="remote">remote</option><option value="local">local</option></select></label>
        <label class="field">TTS Backend<input id="ttsBackend" autocomplete="off"></label>
        <label class="field">TTS API URL<input id="ttsApiUrl" autocomplete="off"></label>
        <label class="field">Render Backend<input id="renderBackend" autocomplete="off"></label>
        <label class="field">Render API URL<input id="renderApiUrl" autocomplete="off"></label>
        <button id="backendSave" class="secondary-button" type="button">保存</button>
        <div id="backendStatus" class="settings-note"></div>
      </details>
    </section>
  </aside>
</main>
<script>
const avatarUrl="/chat/avatar";
const idleVideoUrl="/chat/idle-video";
const bg=document.getElementById("bg");
const bgVideo=document.getElementById("bgVideo");
const idle=document.getElementById("idle");
const idleVideo=document.getElementById("idleVideo");
const idleAvatar=document.getElementById("idleAvatar");
const player=document.getElementById("v");
const subtitle=document.getElementById("subtitle");
const statusText=document.getElementById("statusText");
const playButton=document.getElementById("playButton");
const form=document.getElementById("composer");
const input=document.getElementById("t");
const btn=document.getElementById("b");
const startupOverlay=document.getElementById("startupOverlay");
const startupText=document.getElementById("startupText");
const settingsToggle=document.getElementById("settingsToggle");
const settingsDrawer=document.getElementById("settingsDrawer");
const settingsClose=document.getElementById("settingsClose");
const avatarPreview=document.getElementById("avatarPreview");
const avatarFile=document.getElementById("avatarFile");
const avatarUpload=document.getElementById("avatarUpload");
const avatarStatus=document.getElementById("avatarStatus");
const voiceFile=document.getElementById("voiceFile");
const voiceUpload=document.getElementById("voiceUpload");
const voiceStatus=document.getElementById("voiceStatus");
const llmBaseUrl=document.getElementById("llmBaseUrl");
const llmModel=document.getElementById("llmModel");
const llmApiKey=document.getElementById("llmApiKey");
const llmSave=document.getElementById("llmSave");
const llmStatus=document.getElementById("llmStatus");
const deploymentMode=document.getElementById("deploymentMode");
const ttsBackend=document.getElementById("ttsBackend");
const ttsApiUrl=document.getElementById("ttsApiUrl");
const renderBackend=document.getElementById("renderBackend");
const renderApiUrl=document.getElementById("renderApiUrl");
const backendSave=document.getElementById("backendSave");
const backendStatus=document.getElementById("backendStatus");
let subtitleSegments=[];
let currentSubtitleText="视频待播放";
let idleVideoReady=false;
let conversationHistory=[];
let digitalHumanReady=false;
let warmupPollTimer=null;
const warmupStartedAt=Date.now();
function setVisualSource(url){
  const css=`url("${url}")`;
  idleAvatar.style.backgroundImage=css;
  avatarPreview.style.backgroundImage=css;
}
function showIdleVisual(){
  idleVideo.classList.remove("visible");
  idleVideo.pause();
  idleAvatar.classList.remove("hidden");
}
function setIdle(message){
  idle.classList.remove("hidden");
  player.classList.remove("visible");
  bgVideo.classList.remove("visible");
  bgVideo.pause();
  showIdleVisual();
  if(message)subtitle.textContent=message;
}
function setStatus(message){
  statusText.textContent=message;
  if(message && !player.classList.contains("visible"))subtitle.textContent=message;
}
function setComposerEnabled(enabled){
  input.disabled=!enabled;
  btn.disabled=!enabled;
}
function showWarmupOverlay(message){
  startupText.textContent=message;
  startupOverlay.classList.remove("hidden");
  setComposerEnabled(false);
}
function hideWarmupOverlay(){
  startupOverlay.classList.add("hidden");
  setComposerEnabled(true);
  input.focus();
}
function healthReady(payload){
  const warmup=(payload&&payload.warmup)||{};
  const tts=warmup.tts||{};
  const profile=(payload&&payload.profile)||{};
  const mode=profile.deployment_mode||"mock";
  if(mode==="mock")return tts.status==="ok";
  if(mode==="remote"&&profile.render_api_url)return tts.status==="ok";
  const flashhead=warmup.flashhead||{};
  const inference=flashhead.inference_warmup||{};
  return tts.status==="ok" && flashhead.worker_ready===true && flashhead.status==="ok" && inference.status==="ok";
}
function warmupFailureMessage(payload){
  const warmup=(payload&&payload.warmup)||{};
  const tts=warmup.tts||{};
  const flashhead=warmup.flashhead||{};
  const inference=flashhead.inference_warmup||{};
  if(tts.status==="failed")return "语音服务初始化失败，请刷新重试";
  if(flashhead.status==="failed")return "数字人头像初始化失败，请刷新重试";
  if(inference.status==="failed")return "数字人推理初始化失败，请刷新重试";
  return "";
}
function warmupProgressMessage(payload){
  if(!payload)return "正在连接后端服务...";
  const warmup=payload.warmup||{};
  const tts=warmup.tts||{};
  const profile=(payload&&payload.profile)||{};
  const mode=profile.deployment_mode||"mock";
  const flashhead=((payload&&payload.warmup)||{}).flashhead||{};
  const inference=flashhead.inference_warmup||{};
  if(tts.status!=="ok"){
    if(tts.status==="started")return "正在预热语音服务...";
    return "正在检查语音服务...";
  }
  if(mode==="mock")return "可以开始聊天";
  if(mode==="remote"&&profile.render_api_url)return "可以开始聊天";
  if(flashhead.worker_ready!==true)return "正在启动数字人渲染进程...";
  if(flashhead.status!=="ok"){
    if(flashhead.status==="started")return "正在准备数字人头像...";
    return "正在检查数字人头像...";
  }
  if(inference.status!=="ok"){
    if(inference.status==="started")return "正在预热数字人推理，首次启动约需 1 分钟...";
    return "正在等待数字人推理预热...";
  }
  return "可以开始聊天";
}
async function pollWarmup(){
  if(warmupPollTimer){
    clearTimeout(warmupPollTimer);
    warmupPollTimer=null;
  }
  try{
    const response=await fetch("/health",{cache:"no-store"});
    const payload=await response.json();
    if(healthReady(payload)){
      digitalHumanReady=true;
      hideWarmupOverlay();
      setStatus("可以开始聊天");
      setIdle("可以开始聊天");
      showIdleVisual();
      return;
    }
    const failure=warmupFailureMessage(payload);
    if(failure){
      showWarmupOverlay(failure);
      setStatus("初始化失败");
      return;
    }
    showWarmupOverlay(warmupProgressMessage(payload));
    setStatus(warmupProgressMessage(payload));
    warmupPollTimer=setTimeout(pollWarmup,1000);
    return;
  }catch(error){}
  const elapsed=Date.now()-warmupStartedAt;
  showWarmupOverlay(elapsed>180000?"初始化仍在进行，请稍候或刷新":"正在连接后端服务...");
  setStatus(elapsed>180000?"初始化仍在进行":"正在连接后端服务...");
  warmupPollTimer=setTimeout(pollWarmup,1000);
}
async function loadProfile(){
  try{
    const response=await fetch("/api/v1/profile",{cache:"no-store"});
    if(!response.ok)return;
    const profile=await response.json();
    const avatar=profile.avatar||{};
    const voice=profile.voice||{};
    const llm=profile.llm||{};
    const cacheUrl=`/api/v1/profile/avatar?t=${Date.now()}`;
    setVisualSource(cacheUrl);
    llmBaseUrl.value=llm.base_url||"";
    llmModel.value=llm.model||"";
    llmApiKey.placeholder=llm.api_key_set?"已保存，输入新 key 可替换":"";
    voiceStatus.textContent=voice.voice_set?"已设置":"未设置";
    deploymentMode.value=profile.deployment_mode||"mock";
    ttsBackend.value=voice.tts_backend||"";
    ttsApiUrl.value=voice.tts_api_url||"";
    renderBackend.value=avatar.render_backend||"flashhead";
    renderApiUrl.value=avatar.render_api_url||"";
  }catch(error){}
}
settingsToggle.addEventListener("click",()=>settingsDrawer.classList.add("open"));
settingsClose.addEventListener("click",()=>settingsDrawer.classList.remove("open"));
avatarUpload.addEventListener("click",async()=>{
  if(!avatarFile.files.length)return;
  avatarUpload.disabled=true;
  avatarStatus.textContent="正在上传";
  const formData=new FormData();
  formData.append("file",avatarFile.files[0]);
  try{
    const response=await fetch("/api/v1/profile/avatar",{method:"POST",body:formData});
    if(!response.ok)throw new Error(`上传失败 ${response.status}`);
    digitalHumanReady=false;
    avatarStatus.textContent="正在准备数字人头像";
    const cacheUrl=`/api/v1/profile/avatar?t=${Date.now()}`;
    setVisualSource(cacheUrl);
    showWarmupOverlay("正在准备数字人头像...");
    pollWarmup();
  }catch(error){
    avatarStatus.textContent="上传失败";
  }finally{
    avatarUpload.disabled=false;
  }
});
voiceUpload.addEventListener("click",async()=>{
  if(!voiceFile.files.length)return;
  voiceUpload.disabled=true;
  voiceStatus.textContent="正在上传";
  const formData=new FormData();
  formData.append("file",voiceFile.files[0]);
  try{
    const response=await fetch("/api/v1/profile/voice",{method:"POST",body:formData});
    if(!response.ok)throw new Error(`上传失败 ${response.status}`);
    const payload=await response.json();
    voiceStatus.textContent=`已设置 ${Number(payload.duration_sec||0).toFixed(1)}s`;
  }catch(error){
    voiceStatus.textContent="上传失败";
  }finally{
    voiceUpload.disabled=false;
  }
});
llmSave.addEventListener("click",async()=>{
  llmSave.disabled=true;
  llmStatus.textContent="正在保存";
  try{
    const response=await fetch("/api/v1/profile/llm",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({base_url:llmBaseUrl.value,model:llmModel.value,api_key:llmApiKey.value})
    });
    if(!response.ok)throw new Error(`保存失败 ${response.status}`);
    const payload=await response.json();
    llmApiKey.value="";
    llmApiKey.placeholder=payload.api_key_set?"已保存，输入新 key 可替换":"";
    llmStatus.textContent="已保存";
  }catch(error){
    llmStatus.textContent="保存失败";
  }finally{
    llmSave.disabled=false;
  }
});
backendSave.addEventListener("click",async()=>{
  backendSave.disabled=true;
  backendStatus.textContent="正在保存";
  try{
    const response=await fetch("/api/v1/profile/backends",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        deployment_mode:deploymentMode.value,
        tts_backend:ttsBackend.value,
        tts_api_url:ttsApiUrl.value,
        render_backend:renderBackend.value,
        render_api_url:renderApiUrl.value
      })
    });
    if(!response.ok)throw new Error(`保存失败 ${response.status}`);
    backendStatus.textContent="已保存";
  }catch(error){
    backendStatus.textContent="保存失败";
  }finally{
    backendSave.disabled=false;
  }
});
function setAwaitingPlayback(){
  statusText.textContent="视频已就绪，点击播放";
  subtitle.textContent=firstSubtitleText();
  playButton.classList.remove("hidden");
}
function activeSubtitle(time){
  return subtitleSegments.find(s=>time>=Number(s.start_sec)&&time<Number(s.end_sec));
}
function updateSubtitle(){
  const current=activeSubtitle(player.currentTime);
  subtitle.textContent=current?current.text:firstSubtitleText();
}
function firstSubtitleText(){
  return currentSubtitleText || (subtitleSegments[0]&&subtitleSegments[0].text) || "视频待播放";
}
setVisualSource(avatarUrl);
loadProfile();
idleVideoReady=false;
setIdle("正在连接数字人服务...");
setComposerEnabled(false);
showWarmupOverlay("正在启动数字人...");
pollWarmup();
player.addEventListener("timeupdate",updateSubtitle);
player.addEventListener("waiting",()=>setStatus("缓冲中..."));
player.addEventListener("canplay",()=>{
  if(player.paused){
    setAwaitingPlayback();
  }else{
    setStatus("播放中");
    playButton.classList.add("hidden");
    updateSubtitle();
  }
});
player.addEventListener("playing",()=>{
  playButton.classList.add("hidden");
  idle.classList.add("hidden");
  idleVideo.pause();
  player.classList.add("visible");
  bgVideo.classList.add("visible");
  bgVideo.play().catch(()=>{});
  setStatus("播放中");
  updateSubtitle();
});
player.addEventListener("ended",()=>{
  playButton.classList.add("hidden");
  subtitleSegments=[];
  currentSubtitleText="可以开始聊天";
  setVisualSource(avatarUrl);
  setStatus("可以开始聊天");
  setIdle("可以开始聊天");
});
player.addEventListener("error",()=>{
  playButton.classList.add("hidden");
  subtitleSegments=[];
  currentSubtitleText="视频加载失败";
  setStatus("视频加载失败");
  setIdle("视频加载失败");
});
playButton.addEventListener("click",()=>{
  player.play().catch(()=>{});
});
form.addEventListener("submit",async(event)=>{
  event.preventDefault();
  if(!digitalHumanReady){
    showWarmupOverlay("数字人仍在初始化，请稍候...");
    pollWarmup();
    return;
  }
  const text=input.value.trim();
  if(!text)return;
  btn.disabled=true;
  input.disabled=true;
  input.value="";
  subtitleSegments=[];
  currentSubtitleText="正在生成回复和视频...";
  playButton.classList.add("hidden");
  player.pause();
  player.removeAttribute("src");
  player.load();
  setVisualSource(avatarUrl);
  setStatus("正在生成回复和视频...");
  setIdle("正在生成回复和视频...");
  try{
    const formData=new FormData();
    formData.append("text",text);
    formData.append("history",JSON.stringify(conversationHistory.slice(-16)));
    const response=await fetch("/chat/simple",{method:"POST",body:formData});
    if(response.status===503){
      digitalHumanReady=false;
      showWarmupOverlay("数字人仍在预热，请稍候...");
      setStatus("数字人仍在预热");
      setIdle("数字人仍在预热，请稍候...");
      pollWarmup();
      return;
    }
    if(response.status===400){
      const payload=await response.json().catch(()=>({detail:"请求失败"}));
      setStatus(payload.detail||"LLM 配置缺失");
      setIdle(payload.detail||"LLM 配置缺失");
      return;
    }
    if(!response.ok)throw new Error(`请求失败 ${response.status}`);
    const data=await response.json();
    subtitleSegments=Array.isArray(data.subtitle_segments)?data.subtitle_segments:[];
    currentSubtitleText=(subtitleSegments[0]&&subtitleSegments[0].text)||data.reply||"视频待播放";
    if(!subtitleSegments.length&&data.reply){
      subtitleSegments=[{text:data.reply,start_sec:0,end_sec:Number(data.duration_sec)||3600}];
    }
    if(data.reply){
      conversationHistory.push({role:"user",content:text});
      conversationHistory.push({role:"assistant",content:data.reply});
      conversationHistory=conversationHistory.slice(-16);
    }
    if(data.video_urls&&data.video_urls.length){
      const videoUrl=data.video_urls[0];
      setStatus("视频已生成，正在加载...");
      bgVideo.src=videoUrl;
      player.src=videoUrl;
      bgVideo.load();
      player.load();
      try{
        await player.play();
      }catch(error){
        setAwaitingPlayback();
      }
    }else{
      setStatus("视频生成失败，请稍后重试");
      setIdle("视频生成失败，请稍后重试");
    }
  }catch(error){
    setStatus("请求失败，请稍后重试");
    setIdle("请求失败，请稍后重试");
  }finally{
    setComposerEnabled(digitalHumanReady);
    if(digitalHumanReady)input.focus();
  }
});
</script>
</body>
</html>"""


@router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return HTML


@router.get("/chat/avatar")
async def chat_avatar():
    avatar_path = profile_store.resolve_avatar_image()
    if avatar_path.is_file():
        return FileResponse(avatar_path)
    raise HTTPException(status_code=404, detail=f"Default avatar image not found: {avatar_path}")


@router.get("/chat/idle-video")
async def chat_idle_video():
    idle_path = settings.default_idle_video.expanduser().resolve()
    if idle_path.is_file():
        return FileResponse(idle_path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail=f"Default idle video not found: {idle_path}")


@router.post("/chat/simple")
async def chat_simple(text: str = Form(...), history: str | None = Form(None)):
    deployment_mode = profile_store.resolve_deployment_mode()
    render_api_url = profile_store.resolve_render_api_url()
    tts_api_url = profile_store.resolve_tts_api_url()
    use_remote_render = deployment_mode == "remote" and bool(render_api_url)

    if deployment_mode != "mock" and not use_remote_render and not is_digital_human_ready():
        raise HTTPException(status_code=503, detail="Digital human is warming up")

    if deployment_mode == "mock":
        llm_reply = _mock_reply(text)
    else:
        llm_config = profile_store.resolve_llm_config()
        api_key = llm_config.get("api_key") or ""
        if not api_key:
            raise HTTPException(status_code=400, detail="LLM API key is not configured")

        llm_reply = ""
        history_messages = _parse_history(history)
        try:
            async with httpx.AsyncClient(timeout=30) as cl:
                resp = await cl.post(
                    f"{str(llm_config['base_url']).rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": llm_config["model"],
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Clara, keep replies short (40-80 chars). Friendly. "
                                    "Use the provided conversation history when answering."
                                ),
                            },
                            *history_messages,
                            {"role": "user", "content": text},
                        ],
                    },
                )
                if resp.status_code == 200:
                    llm_reply = resp.json()["choices"][0]["message"]["content"]
        except Exception:
            llm_reply = "Sorry, please try again."
        if not llm_reply.strip():
            llm_reply = "Sorry, please try again."

    sents = re.split(r"(?<=[。！？.!?])", llm_reply)
    sents = [s.strip() for s in sents if s.strip()] or [llm_reply]
    videos: list[str] = []
    subtitle_segments: list[dict] = []
    duration_sec: float | None = None
    try:
        async with httpx.AsyncClient(timeout=300) as cl:
            render_data = {
                "sentences": "\n".join(sents),
                "language": "zh",
                "emotion": "calm",
                "speed": "1.0",
            }
            if use_remote_render and tts_api_url:
                render_data["tts_api_url"] = tts_api_url

            render_files = None
            with ExitStack() as stack:
                if use_remote_render:
                    avatar_path = profile_store.resolve_avatar_image()
                    if avatar_path.is_file():
                        render_files = {
                            "avatar_file": (
                                avatar_path.name,
                                stack.enter_context(avatar_path.open("rb")),
                                _avatar_mime_type(avatar_path),
                            )
                        }
                r = await cl.post(
                    _render_batch_url(render_api_url if use_remote_render else None),
                    data=render_data,
                    files=render_files,
                )
            if r.is_success:
                payload = r.json()
                videos = _normalize_video_urls(
                    payload.get("video_urls", []),
                    render_api_url if use_remote_render else None,
                )
                subtitle_segments = payload.get("subtitle_segments", [])
                duration_sec = payload.get("duration_sec")
    except Exception:
        pass

    return JSONResponse(
        {
            "reply": llm_reply,
            "video_urls": videos,
            "subtitle_segments": subtitle_segments,
            "duration_sec": duration_sec,
        }
    )


def _mock_reply(text: str) -> str:
    user_text = text.strip()
    if not user_text:
        return _MOCK_REPLY_PREFIX
    return f"你刚才说：{user_text}。我在这里听你说。"


def _render_batch_url(remote_base_url: str | None = None) -> str:
    if remote_base_url:
        return f"{remote_base_url.rstrip('/')}/api/v1/generate-text-batch"
    return f"http://127.0.0.1:{settings.api_port}/api/v1/generate-text-batch"


def _normalize_video_urls(video_urls: list[str], remote_base_url: str | None = None) -> list[str]:
    normalized: list[str] = []
    for item in video_urls:
        url = str(item or "").strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"}:
            normalized.append(url)
        elif remote_base_url:
            normalized.append(f"{remote_base_url.rstrip('/')}/{url.lstrip('/')}")
        else:
            normalized.append(url)
    return normalized


def _avatar_mime_type(path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _parse_history(raw_history: str | None) -> list[dict[str, str]]:
    if not raw_history:
        return []

    try:
        parsed = json.loads(raw_history)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    messages: list[dict[str, str]] = []
    for item in parsed[-_MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        messages.append(
            {
                "role": role,
                "content": content[:_MAX_HISTORY_CONTENT_CHARS],
            }
        )

    return messages
