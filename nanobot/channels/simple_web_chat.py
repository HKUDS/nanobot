"""Simple web chat channel — FastAPI + embedded HTML/CSS/JS (single file)."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

try:
    import uvicorn
    from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from starlette.middleware.cors import CORSMiddleware
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Embedded UI
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{{TITLE}}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><text y='20' font-size='20'>🤖</text></svg>"/>
<!-- marked.js for Markdown -->
<script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
<!-- highlight.js for code blocks -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github-dark.min.css"/>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/highlight.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1117;--surface:#1a1d27;--surface2:#22263a;--border:#2e3352;
  --accent:#7c6af7;--accent2:#56cfb9;--user-bubble:#2d2f6b;--bot-bubble:#1e2235;
  --text:#e4e6f0;--text-dim:#8892b0;--text-dimmer:#515a7a;
  --danger:#e05c7a;--success:#56cfb9;--radius:14px;
  --font:'Inter',system-ui,sans-serif;
  --shadow:0 4px 24px rgba(0,0,0,.45);
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px}

/* ---- Layout ---- */
#app{display:flex;flex-direction:column;height:100vh;max-width:900px;margin:0 auto;}

/* ---- Header ---- */
#header{
  display:flex;align-items:center;gap:12px;
  padding:14px 20px;background:var(--surface);
  border-bottom:1px solid var(--border);
  box-shadow:0 2px 8px rgba(0,0,0,.3);
  user-select:none;
}
#header .avatar{
  width:40px;height:40px;border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  display:flex;align-items:center;justify-content:center;
  font-size:20px;flex-shrink:0;
}
#header .info{flex:1}
#header .info h1{font-size:16px;font-weight:600;letter-spacing:.3px}
#header .info .status{font-size:12px;color:var(--text-dim);display:flex;align-items:center;gap:5px;margin-top:2px}
#header .info .dot{width:7px;height:7px;border-radius:50%;background:var(--success);display:inline-block}
#header .info .dot.offline{background:var(--text-dimmer)}
#btn-clear{
  background:none;border:1px solid var(--border);color:var(--text-dim);
  border-radius:8px;padding:6px 12px;cursor:pointer;font-size:12px;
  transition:all .2s;
}
#btn-clear:hover{border-color:var(--danger);color:var(--danger)}

/* ---- Messages area ---- */
#messages{
  flex:1;overflow-y:auto;padding:24px 20px;
  display:flex;flex-direction:column;gap:18px;
}
#messages::-webkit-scrollbar{width:5px}
#messages::-webkit-scrollbar-track{background:transparent}
#messages::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ---- Message rows ---- */
.msg-row{display:flex;gap:10px;align-items:flex-end;animation:fadeUp .22s ease}
.msg-row.user{flex-direction:row-reverse}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

.msg-avatar{
  width:32px;height:32px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:15px;
  background:var(--surface2);margin-bottom:4px;
}
.msg-row.user .msg-avatar{background:linear-gradient(135deg,var(--accent),var(--accent2))}

.msg-wrap{display:flex;flex-direction:column;max-width:72%;gap:4px}
.msg-row.user .msg-wrap{align-items:flex-end}

.bubble{
  padding:10px 15px;border-radius:var(--radius);line-height:1.6;
  position:relative;word-break:break-word;
}
.msg-row.bot .bubble{background:var(--bot-bubble);border-bottom-left-radius:4px;border:1px solid var(--border)}
.msg-row.user .bubble{background:var(--user-bubble);border-bottom-right-radius:4px;border:1px solid #3d4080}

/* markdown inside bot bubble */
.bubble h1,.bubble h2,.bubble h3{margin:.5em 0 .25em;font-size:1em;font-weight:600}
.bubble p{margin:.3em 0}
.bubble ul,.bubble ol{padding-left:1.4em;margin:.3em 0}
.bubble li{margin:.15em 0}
.bubble code:not([class]){
  background:#0d1117;padding:2px 6px;border-radius:4px;font-size:.85em;
  font-family:'JetBrains Mono','Fira Code',monospace;color:#7ee8a2;
}
.bubble pre{
  margin:.5em 0;border-radius:8px;overflow:hidden;
  border:1px solid var(--border);
}
.bubble pre code{font-size:.82em;padding:12px 14px;display:block;overflow-x:auto}
.bubble a{color:var(--accent2);text-decoration:none}
.bubble a:hover{text-decoration:underline}
.bubble blockquote{
  border-left:3px solid var(--accent);padding-left:10px;
  color:var(--text-dim);margin:.3em 0;
}
.bubble table{border-collapse:collapse;width:100%;font-size:.85em;margin:.4em 0}
.bubble th,.bubble td{border:1px solid var(--border);padding:5px 9px}
.bubble th{background:var(--surface2)}
.bubble hr{border:none;border-top:1px solid var(--border);margin:.5em 0}

/* ---- Received reaction animation ---- */
@keyframes receivePulse{
  0%  {box-shadow:0 0 0 0 rgba(124,106,247,.7);border-color:#7c6af7}
  60% {box-shadow:0 0 0 8px rgba(124,106,247,0);border-color:#3d4080}
  100%{box-shadow:0 0 0 0 rgba(124,106,247,0);border-color:#3d4080}
}
.bubble.reacting{animation:receivePulse .6s ease-out 2}

.reaction-badge{
  font-size:13px;position:absolute;right:-6px;top:-16px;
  animation:badgePop .25s ease-out forwards, badgeFade 1s .8s ease-in forwards;
  pointer-events:none;user-select:none;
}
@keyframes badgePop{from{opacity:0;transform:scale(.4) translateY(4px)}to{opacity:1;transform:scale(1) translateY(0)}}
@keyframes badgeFade{from{opacity:1}to{opacity:0}}

/* media inside bubble */
.bubble img{max-width:100%;max-height:320px;border-radius:8px;margin-top:6px;display:block}
.bubble video{max-width:100%;max-height:320px;border-radius:8px;margin-top:6px;display:block;background:#000}
.bubble audio{width:100%;margin-top:6px;display:block;border-radius:8px}
.file-attachment{
  display:inline-flex;align-items:center;gap:8px;margin-top:6px;
  background:var(--surface2);border:1px solid var(--border);
  border-radius:8px;padding:8px 12px;font-size:13px;color:var(--text);
  text-decoration:none;transition:border-color .2s;
}
.file-attachment:hover{border-color:var(--accent);color:var(--text)}
.file-attachment .icon{font-size:18px}
.file-attachment .fname{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-attachment .fsize{color:var(--text-dim);font-size:11px;margin-left:auto}

/* timestamp */
.msg-time{font-size:10px;color:var(--text-dimmer);padding:0 4px}

/* image thumbnails sent by user */
.media-thumb{max-width:220px;border-radius:10px;cursor:pointer;display:block;margin-top:4px;transition:opacity .2s}
.media-thumb:hover{opacity:.85}

/* ---- Typing indicator ---- */
#typing{display:none;align-items:center;gap:10px;padding:4px 20px}
#typing .dots{display:flex;gap:5px}
#typing .dots span{
  width:7px;height:7px;border-radius:50%;background:var(--text-dimmer);
  animation:blink 1.2s infinite;
}
#typing .dots span:nth-child(2){animation-delay:.2s}
#typing .dots span:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
#typing .label{font-size:12px;color:var(--text-dimmer)}

/* ---- Attachment preview bar ---- */
#attach-bar{
  display:none;gap:8px;flex-wrap:wrap;
  padding:8px 20px 0;background:var(--surface);border-top:1px solid var(--border);
}
.attach-chip{
  display:flex;align-items:center;gap:6px;
  background:var(--surface2);border:1px solid var(--border);border-radius:20px;
  padding:4px 10px 4px 6px;font-size:12px;color:var(--text);
}
.attach-chip img{width:28px;height:28px;object-fit:cover;border-radius:4px}
.attach-chip .chip-name{max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.attach-chip button{
  background:none;border:none;color:var(--text-dim);cursor:pointer;
  font-size:14px;line-height:1;padding:0 0 0 2px;
}
.attach-chip button:hover{color:var(--danger)}

/* ---- Input area ---- */
#input-area{
  padding:12px 16px 16px;background:var(--surface);
  border-top:1px solid var(--border);
}
#input-row{
  display:flex;align-items:flex-end;gap:8px;
  background:var(--surface2);border:1.5px solid var(--border);
  border-radius:var(--radius);padding:6px 8px;
  transition:border-color .2s;
}
#input-row:focus-within{border-color:var(--accent)}
#file-btn{
  background:none;border:none;color:var(--text-dim);
  cursor:pointer;padding:6px;border-radius:8px;width:34px;height:34px;
  display:flex;align-items:center;justify-content:center;
  transition:color .2s,background .2s;flex-shrink:0;
}
#file-btn:hover{color:var(--accent);background:rgba(124,106,247,.1)}
#file-input{display:none}
#msg-input{
  flex:1;background:none;border:none;outline:none;
  color:var(--text);font-size:15px;font-family:var(--font);
  resize:none;min-height:34px;max-height:140px;line-height:1.5;
  padding:6px 4px;
}
#msg-input::placeholder{color:var(--text-dimmer)}
#send-btn{
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  border:none;border-radius:10px;color:#fff;cursor:pointer;
  width:36px;height:36px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:opacity .2s,transform .15s;font-size:16px;
}
#send-btn:hover{opacity:.9;transform:scale(1.06)}
#send-btn:active{transform:scale(.95)}
#send-btn:disabled{opacity:.4;cursor:default;transform:none}
#input-hint{font-size:11px;color:var(--text-dimmer);margin-top:6px;text-align:right}

/* Light-box for image preview */
#lightbox{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);
  z-index:1000;align-items:center;justify-content:center;cursor:zoom-out;
}
#lightbox.show{display:flex}
#lightbox img{max-width:90vw;max-height:90vh;border-radius:10px;box-shadow:var(--shadow)}

/* Connection banner */
#conn-banner{
  display:none;text-align:center;padding:8px;font-size:13px;
  background:#2a1a1a;color:var(--danger);border-bottom:1px solid #4d1a1a;
}

/* ---- Progress / internal process messages ---- */
.msg-row.progress .bubble{
  background:transparent;border:1px dashed var(--border);
  color:var(--text-dimmer);font-size:12.5px;font-style:italic;
  padding:5px 11px;
}
.msg-row.progress .msg-avatar{opacity:.35;font-size:12px;width:24px;height:24px}
.msg-row.progress .msg-time{display:none}
.msg-row.progress .msg-wrap{max-width:80%}
.progress-icon{
  display:inline-block;margin-right:5px;vertical-align:middle;
  font-style:normal;opacity:.7;
}
</style>
</head>
<body>
<div id="app">
  <div id="conn-banner">⚠ Disconnected — reconnecting…</div>

  <div id="header">
    <div class="avatar">🤖</div>
    <div class="info">
      <h1 id="chat-title">{{TITLE}}</h1>
      <div class="status"><span class="dot offline" id="status-dot"></span><span id="status-text">Connecting…</span></div>
    </div>
    <button id="btn-clear" title="Clear conversation">Clear</button>
  </div>

  <div id="messages">
    <!-- messages injected here -->
  </div>

  <div id="typing">
    <div class="msg-avatar">🤖</div>
    <div class="dots"><span></span><span></span><span></span></div>
    <span class="label">Thinking…</span>
  </div>

  <div id="attach-bar"></div>

  <div id="input-area">
    <div id="input-row">
      <button id="file-btn" title="Attach file / image" onclick="document.getElementById('file-input').click()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
        </svg>
      </button>
      <input id="file-input" type="file" multiple accept="image/*,video/*,audio/*,.pdf,.txt,.md,.csv,.json,.py,.js,.ts,.html,.css,.zip,.tar.gz"/>
      <textarea id="msg-input" rows="1" placeholder="Message…"></textarea>
      <button id="send-btn" id="send-btn" title="Send (Enter)">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
      </button>
    </div>
    <div id="input-hint">Enter to send &nbsp;·&nbsp; Shift+Enter for new line &nbsp;·&nbsp; Drop files anywhere</div>
  </div>
</div>

<div id="lightbox" onclick="this.classList.remove('show')"><img id="lb-img" src=""/></div>

<script>
(function(){
"use strict";
// ── marked config (v9+ renderer extension) ─────────────────────
marked.use({
  breaks:true,
  gfm:true,
  renderer:{
    code(code,lang){
      const validLang=lang&&typeof hljs!=='undefined'&&hljs.getLanguage(lang);
      const highlighted=validLang
        ?hljs.highlight(code,{language:lang,ignoreIllegals:true}).value
        :(typeof hljs!=='undefined'?hljs.highlightAuto(code).value:escHtml(code));
      const cls=validLang?` class="language-${lang}"`:'';
      return `<pre><code${cls}>${highlighted}</code></pre>`;
    }
  }
});

// ── State ──────────────────────────────────────────────────────
const MSG    = document.getElementById('messages');
const INPUT  = document.getElementById('msg-input');
const SEND   = document.getElementById('send-btn');
const TYPING = document.getElementById('typing');
const ABAR   = document.getElementById('attach-bar');
const BANNER = document.getElementById('conn-banner');
const SDOT   = document.getElementById('status-dot');
const STXT   = document.getElementById('status-text');

let ws=null, pendingFiles=[], reconnectTimer=null, reconnectDelay=1000;
const sessionId = (()=>{
  let s=sessionStorage.getItem('chat_session');
  if(!s){s=(crypto&&crypto.randomUUID?crypto.randomUUID():'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.random()*16|0;return(c==='x'?r:r&0x3|0x8).toString(16)}));sessionStorage.setItem('chat_session',s);}
  return s;
})();

// ── WebSocket ──────────────────────────────────────────────────
function connect(){
  const proto=location.protocol==='https:'?'wss':'ws';
  ws=new WebSocket(`${proto}://${location.host}/ws/${sessionId}`);

  ws.onopen=()=>{
    BANNER.style.display='none';
    SDOT.classList.remove('offline');
    STXT.textContent='Online';
    reconnectDelay=1000;
  };

  ws.onclose=()=>{
    BANNER.style.display='block';
    SDOT.classList.add('offline');
    STXT.textContent='Reconnecting…';
    TYPING.style.display='none';
    reconnectTimer=setTimeout(connect, reconnectDelay);
    reconnectDelay=Math.min(reconnectDelay*2, 30000);
  };

  ws.onerror=()=>ws.close();

  ws.onmessage=(ev)=>{
    const data=JSON.parse(ev.data);
    TYPING.style.display='none';
    if(data.type==='message'){
      if(data.is_progress_msg){
        const icon=data.is_tool_hint_msg?'🧰':'🤔';
        appendProgressMessage(data.content, data.media||[], icon);
      } else {
        appendBotMessage(data.content, data.media||[]);
      }
    } else if(data.type==='reaction'){
      // Animate the last user bubble to indicate backend received the message
      const userBubbles=MSG.querySelectorAll('.msg-row.user .bubble');
      const last=userBubbles[userBubbles.length-1];
      if(last){
        last.classList.remove('reacting');
        // force reflow so re-adding the class re-triggers the animation
        void last.offsetWidth;
        last.classList.add('reacting');
        last.addEventListener('animationend',()=>last.classList.remove('reacting'),{once:true});
        const badge=document.createElement('span');
        badge.className='reaction-badge';
        badge.textContent=data.emoji||'👍';
        last.style.position='relative';
        last.appendChild(badge);
        setTimeout(()=>badge.remove(),2000);
      }
    } else if(data.type==='typing'){
      TYPING.style.display='flex';
      MSG.scrollTop=MSG.scrollHeight;
    } else if(data.type==='error'){
      appendSystemMsg('⚠ '+data.content);
    }
  };
}

// ── Render helpers ─────────────────────────────────────────────
function fmtTime(){
  return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
}

function renderMarkdown(text){
  const dirty=marked.parse(text);
  // basic sanitize: strip script tags
  return dirty.replace(/<script[\s\S]*?<\/script>/gi,'');
}

function makeFileChip(file){
  const isImg=/^image\//.test(file.type);
  const chip=document.createElement('div');
  chip.className='attach-chip';
  chip.dataset.name=file.name;
  if(isImg){
    const img=document.createElement('img');
    img.src=URL.createObjectURL(file);
    chip.appendChild(img);
  } else {
    chip.innerHTML='<span class="icon">📄</span>';
  }
  chip.innerHTML+=`<span class="chip-name">${escHtml(file.name)}</span>`;
  const rm=document.createElement('button');
  rm.textContent='×';
  rm.title='Remove';
  rm.onclick=()=>{
    pendingFiles=pendingFiles.filter(f=>f!==file);
    chip.remove();
    if(!pendingFiles.length) ABAR.style.display='none';
  };
  chip.appendChild(rm);
  return chip;
}

function escHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtBytes(b){
  if(b<1024)return b+'B';
  if(b<1048576)return (b/1024).toFixed(1)+'K';
  return (b/1048576).toFixed(1)+'M';
}

function appendMsg(role,contentHtml,mediaItems){
  const isUser=role==='user';
  const row=document.createElement('div');
  row.className='msg-row '+(isUser?'user':'bot');

  const avatar=document.createElement('div');
  avatar.className='msg-avatar';
  avatar.textContent=isUser?'👤':'🤖';

  const wrap=document.createElement('div');
  wrap.className='msg-wrap';

  const bubble=document.createElement('div');
  bubble.className='bubble';
  bubble.innerHTML=contentHtml;

  // helpers shared by media-loop and markdown post-processing
  const imgExts=new Set(['jpg','jpeg','png','gif','webp','svg','bmp','avif','ico']);
  const vidExts=new Set(['mp4','webm','ogv','mov','avi','mkv','m4v']);
  const audExts=new Set(['mp3','wav','ogg','aac','flac','m4a','opus','weba']);

  function mediaExt(url){
    return url.split('?')[0].split('.').pop().toLowerCase();
  }
  function makeAttachLink(url){
    const fname=decodeURIComponent(url.split('/').pop().split('?')[0]);
    const a=document.createElement('a');
    a.className='file-attachment'; a.href=url; a.target='_blank'; a.download=fname;
    a.innerHTML=`<span class="icon">📎</span><span class="fname">${escHtml(fname)}</span>`;
    return a;
  }
  function makeImgThumb(url){
    const img=document.createElement('img');
    img.src=url; img.className='media-thumb';
    img.onclick=()=>openLightbox(url);
    // if the image fails to load (e.g. non-image file served), fall back to a download link
    img.onerror=()=>{ if(img.parentNode) img.parentNode.replaceChild(makeAttachLink(url),img); };
    return img;
  }

  // render media
  (mediaItems||[]).forEach(url=>{
    const ext=mediaExt(url);
    if(imgExts.has(ext)){
      bubble.appendChild(makeImgThumb(url));
    } else if(vidExts.has(ext)){
      const vid=document.createElement('video');
      vid.src=url; vid.controls=true; vid.preload='metadata';
      bubble.appendChild(vid);
    } else if(audExts.has(ext)){
      const aud=document.createElement('audio');
      aud.src=url; aud.controls=true; aud.preload='metadata';
      bubble.appendChild(aud);
    } else {
      bubble.appendChild(makeAttachLink(url));
    }
  });

  // post-process markdown-rendered <img> tags: replace non-image srcs with download links
  bubble.querySelectorAll('img').forEach(img=>{
    const src=img.src||img.getAttribute('src')||'';
    const ext=mediaExt(src);
    if(!imgExts.has(ext)){
      img.parentNode.replaceChild(makeAttachLink(src),img);
    } else {
      img.onerror=()=>{ if(img.parentNode) img.parentNode.replaceChild(makeAttachLink(src),img); };
    }
  });

  const time=document.createElement('div');
  time.className='msg-time'; time.textContent=fmtTime();

  wrap.appendChild(bubble);
  wrap.appendChild(time);

  if(isUser){row.appendChild(wrap);row.appendChild(avatar);}
  else{row.appendChild(avatar);row.appendChild(wrap);}

  MSG.appendChild(row);
  requestAnimationFrame(()=>{MSG.scrollTop=MSG.scrollHeight;});
  // highlight code blocks once bubble is in the DOM
  if(typeof hljs!=='undefined'){
    bubble.querySelectorAll('pre code').forEach(el=>hljs.highlightElement(el));
  }
  return bubble;
}

function appendUserMessage(text, mediaUrls){
  const html=`<span>${escHtml(text).replace(/\n/g,'<br>')}</span>`;
  appendMsg('user', html, mediaUrls);
}

function appendBotMessage(text, mediaUrls){
  appendMsg('bot', renderMarkdown(text), mediaUrls);
}

function appendProgressMessage(text, mediaUrls, icon){
  const row=document.createElement('div');
  row.className='msg-row bot progress';

  const avatar=document.createElement('div');
  avatar.className='msg-avatar';
  avatar.textContent='⚙';

  const wrap=document.createElement('div');
  wrap.className='msg-wrap';

  const bubble=document.createElement('div');
  bubble.className='bubble';
  const indicator=`<span class="progress-icon">${icon||'🤔'}</span>`;
  bubble.innerHTML=indicator+escHtml(text);

  (mediaUrls||[]).forEach(url=>{
    const a=document.createElement('a');
    a.href=url;a.target='_blank';a.textContent=url;
    bubble.appendChild(a);
  });

  wrap.appendChild(bubble);
  row.appendChild(avatar);
  row.appendChild(wrap);
  MSG.appendChild(row);
  requestAnimationFrame(()=>{MSG.scrollTop=MSG.scrollHeight;});
}

function appendSystemMsg(text){
  const d=document.createElement('div');
  d.style.cssText='text-align:center;font-size:12px;color:var(--text-dimmer);padding:4px 0';
  d.textContent=text;
  MSG.appendChild(d);
  MSG.scrollTop=MSG.scrollHeight;
}

function openLightbox(src){
  document.getElementById('lb-img').src=src;
  document.getElementById('lightbox').classList.add('show');
}

// ── Send ───────────────────────────────────────────────────────
async function send(){
  const text=INPUT.value.trim();
  if(!text && !pendingFiles.length) return;
  if(!ws||ws.readyState!==WebSocket.OPEN){
    appendSystemMsg('Not connected — please wait…');return;
  }

  SEND.disabled=true;
  const files=[...pendingFiles];
  pendingFiles=[];
  ABAR.innerHTML='';
  ABAR.style.display='none';
  INPUT.value='';
  INPUT.style.height='auto';

  // upload files first
  const uploadedUrls=[];
  for(const f of files){
    try{
      const fd=new FormData();
      fd.append('file',f);
      const res=await fetch('/upload',{method:'POST',body:fd});
      if(res.ok){
        const j=await res.json();
        uploadedUrls.push(j.url);
      } else {
        appendSystemMsg(`Upload failed: ${f.name}`);
      }
    }catch(e){
      appendSystemMsg(`Upload error: ${f.name}`);
    }
  }

  // show user bubble
  appendUserMessage(text||files.map(f=>f.name).join(', '), uploadedUrls);

  // show typing
  TYPING.style.display='flex';
  MSG.scrollTop=MSG.scrollHeight;

  // send via WS
  ws.send(JSON.stringify({type:'message', content:text, media:uploadedUrls}));
  SEND.disabled=false;
}

// ── Events ─────────────────────────────────────────────────────
SEND.addEventListener('click',send);
INPUT.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}
});
INPUT.addEventListener('input',()=>{
  INPUT.style.height='auto';
  INPUT.style.height=Math.min(INPUT.scrollHeight,140)+'px';
});

document.getElementById('file-input').addEventListener('change',e=>{
  addFiles([...e.target.files]);
  e.target.value='';
});

document.addEventListener('dragover',e=>{e.preventDefault();});
document.addEventListener('drop',e=>{
  e.preventDefault();
  const files=[...e.dataTransfer.files];
  if(files.length) addFiles(files);
});

function addFiles(files){
  files.forEach(f=>{
    pendingFiles.push(f);
    ABAR.appendChild(makeFileChip(f));
  });
  ABAR.style.display='flex';
}

document.getElementById('btn-clear').addEventListener('click',()=>{
  MSG.innerHTML='';
  appendSystemMsg('Conversation cleared');
});

// kick off
connect();
appendSystemMsg('Welcome! How can I help you today?');
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Config (inline to avoid circular imports; also registered in schema.py)
# ---------------------------------------------------------------------------

class SimpleWebChatConfig:
    """Minimal config object used when the pydantic schema is not available."""

    def __init__(self, **kw: Any) -> None:
        self.enabled: bool = kw.get("enabled", False)
        self.host: str = kw.get("host", "0.0.0.0")
        self.port: int = int(kw.get("port", 8088))
        self.title: str = kw.get("title", "Nanobot Chat")
        self.allow_from: list[str] = kw.get("allow_from", [])
        self.max_upload_size_mb: int = int(kw.get("max_upload_size_mb", 50))


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class SimpleWebChatChannel(BaseChannel):
    """
    A lightweight web-based chat channel powered by FastAPI.

    * Single-page reactive UI served from `/`
    * WebSocket endpoint at `/ws/{session_id}` for duplex messaging
    * File upload endpoint at `/upload` (returns a URL for the stored file)
    * Outbound messages (bot replies) are pushed to the matching websocket
    """

    name = "simple_web_chat"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        super().__init__(config, bus)
        # websocket connections keyed by session_id (== chat_id)
        self._connections: dict[str, WebSocket] = {}
        # pending outbound queue per session
        self._queues: dict[str, asyncio.Queue] = {}
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._upload_dir: Path = self._resolve_upload_dir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_upload_dir(self) -> Path:
        p = Path.home() / ".nanobot" / "media"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _get_html(self) -> str:
        title = getattr(self.config, "title", "Nanobot Chat")
        return _HTML.replace("{{TITLE}}", title)

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="SimpleWebChat", docs_url=None, redoc_url=None)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        html_content = self._get_html()
        max_bytes = getattr(
            self.config, "max_upload_size_mb", 50) * 1024 * 1024
        upload_dir = self._upload_dir
        channel_ref = self  # capture self for closures

        # ---- serve HTML ----
        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(html_content)

        # ---- file upload from web client will be handled here ----
        @app.post("/upload")
        async def upload(file: UploadFile = File(...)) -> JSONResponse:
            data = await file.read()
            if len(data) > max_bytes:
                return JSONResponse({"error": "File too large"}, status_code=413)
            dest = upload_dir / file.filename
            if dest.exists():
                logger.info(
                    "Upload filename collision: {}, will overwrite", dest)
            dest.write_bytes(data)
            logger.debug("Uploaded {} ({} bytes) -> {}",
                         file.filename, len(data), dest)
            return JSONResponse({"url": f"/uploads/{file.filename}", "name": file.filename})

        # ---- serve uploaded files ----
        _INLINE_MIME_PREFIXES = (
            "image/", "video/", "audio/", "text/html", "application/pdf")

        @app.get("/uploads/{fname}")
        async def serve_uploaded_file(fname: str) -> FileResponse:
            """Serve a previously uploaded file by filename.

            Media types that browsers can render natively (images, video, audio,
            HTML, PDF) are returned inline so they display directly in the chat
            bubble.  All other types (e.g. ZIP, CSV, Python scripts) get a
            ``Content-Disposition: attachment`` header to trigger a download
            instead of an unsafe inline render.
            """
            path = upload_dir / fname
            # Return 404 if the file doesn't exist in the upload directory
            if not path.exists():
                from fastapi import HTTPException
                raise HTTPException(404)

            # Detect MIME type from the file extension; fall back to a safe binary default
            mime, _ = mimetypes.guess_type(str(path))
            mime = mime or "application/octet-stream"

            # Serve renderable types inline; force-download everything else
            inline = any(mime.startswith(p) for p in _INLINE_MIME_PREFIXES)
            headers = {} if inline else {"Content-Disposition": f'attachment; filename="{fname}"'}
            return FileResponse(str(path), media_type=mime, headers=headers)

        # ---- websocket ----
        @app.websocket("/ws/{session_id}")
        async def ws_endpoint(websocket: WebSocket, session_id: str) -> None:
            await websocket.accept()
            channel_ref._connections[session_id] = websocket
            if session_id not in channel_ref._queues:
                channel_ref._queues[session_id] = asyncio.Queue()
            logger.info("WebChat session connected: {}", session_id)

            # forward queued outbound messages to client in the background
            async def _drain() -> None:
                q = channel_ref._queues[session_id]
                while True:
                    payload = await q.get()
                    try:
                        await websocket.send_text(payload)
                    except Exception:
                        break

            drain_task = asyncio.create_task(_drain())

            try:
                while True:
                    raw = await websocket.receive_text()
                    await channel_ref._on_ws_message(session_id, raw)
            except WebSocketDisconnect:
                logger.info("WebChat session disconnected: {}", session_id)
            except Exception as exc:
                logger.warning(
                    "WebChat WS error (session={}): {}", session_id, exc)
            finally:
                drain_task.cancel()
                channel_ref._connections.pop(session_id, None)

        return app

    async def _on_ws_message(self, session_id: str, raw: str) -> None:
        """Handle a raw JSON message received from the browser."""
        import json

        try:
            data = json.loads(raw)
        except Exception:
            return

        msg_type = data.get("type", "message")
        if msg_type != "message":
            return

        content: str = (data.get("content") or "").strip()
        media: list[str] = data.get("media") or []

        # Send reaction acknowledgement immediately so the client shows a "received" animation
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_text(json.dumps({"type": "reaction", "emoji": "👍"}))
            except Exception:
                pass

        # Resolve relative upload URLs to absolute paths so the agent can read them
        resolved_media: list[str] = []
        for url in media:
            if url.startswith("/uploads/"):
                fname = url[len("/uploads/"):]
                resolved_media.append(str(self._upload_dir / fname))
            else:
                resolved_media.append(url)

        await self._handle_message(
            sender_id=session_id,
            chat_id=session_id,
            content=content,
            media=resolved_media,
        )

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not _FASTAPI_AVAILABLE:
            logger.error(
                "simple_web_chat requires fastapi and uvicorn. "
                "Install with: pip install fastapi uvicorn[standard]"
            )
            return

        self._running = True
        self._app = self._build_app()

        host = getattr(self.config, "host", "0.0.0.0")
        port = int(getattr(self.config, "port", 8088))

        uv_config = uvicorn.Config(
            app=self._app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(uv_config)

        logger.info("SimpleWebChat listening on http://{}:{}", host, port)
        await self._server.serve()

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.should_exit = True

    async def send(self, msg: OutboundMessage) -> None:
        """Push a bot reply to the browser over WebSocket."""
        import json
        import shutil

        session_id = msg.chat_id

        # Resolve local file paths → /uploads/ URLs so the browser can fetch them
        media_urls: list[str] = []
        for item in (msg.media or []):
            if not item:
                continue
            if item.startswith(("http://", "https://", "/uploads/")):
                media_urls.append(item)
            else:
                # Treat as a local filesystem path
                src = Path(item)
                if src.exists() and src.is_file():
                    dest = self._upload_dir / src.name
                    shutil.copy2(str(src), str(dest))
                    logger.debug("WebChat: copied media {} → {}", src, dest)
                    media_urls.append(f"/uploads/{src.name}")
                else:
                    logger.warning(
                        "WebChat: media not found or not a file: {}", item)

        is_progress_msg = bool((msg.metadata or {}).get("_progress"))
        is_tool_hint_msg = bool((msg.metadata or {}).get("_tool_hint"))
        payload = json.dumps(
            {"type": "message", "content": msg.content, "media": media_urls,
                "is_progress_msg": is_progress_msg, "is_tool_hint_msg": is_tool_hint_msg}
        )

        # Try direct WS send first (connection still open)
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_text(payload)
                return
            except Exception:
                self._connections.pop(session_id, None)

        # Fall back: queue for reconnect / drain task
        q = self._queues.setdefault(session_id, asyncio.Queue())
        await q.put(payload)
        logger.debug("WebChat queued reply for session {}", session_id)
