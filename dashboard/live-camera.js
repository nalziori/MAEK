"use strict";
window.MAEK_LIVE_CAMERA = {connected: false};
let liveImage = null, liveFrameId = null, liveSession = null, displayedFrames = 0;
let lastFrameAt = 0;
let liveBlobUrl = null;
const cameraBridge = 'http://127.0.0.1:8765';

function mountLivePosition() {
  if (typeof project !== 'function' || typeof document.querySelectorAll !== 'function') return;
  const state = window.MAEK_LIVE_CAMERA, pose = state?.position;
  document.querySelectorAll('.drone-mark').forEach(marker => {
    const group = marker.parentElement;
    if (!state?.connected || !pose || ![pose.x,pose.y,pose.z].every(Number.isFinite)) {
      if (group.dataset.livePosition) group.style.display = 'none';
      return;
    }
    const point = project([pose.x,pose.z,pose.y]);
    const originalX = Number(marker.getAttribute('cx')), originalY = Number(marker.getAttribute('cy'));
    group.style.display = '';
    group.setAttribute('transform',`translate(${point[0]-originalX} ${point[1]-originalY})`);
    group.setAttribute('aria-label','현재 드론 위치 · 실시간 가상 모델 좌표');
    group.dataset.livePosition = 'true';
    group.dataset.sourceFrame = state.preview?.frameId || '';
    group.dataset.worldX = String(pose.x);group.dataset.worldY = String(pose.y);group.dataset.worldZ = String(pose.z);
  });
}
function mountLiveFrame() {
  mountLivePosition();
  const slot = document.querySelector('[data-rgb-photo]');
  if (!slot || !liveImage) return;
  slot.dataset.live = 'true';
  if (slot.dataset.frameId === liveFrameId) return;
  const holder = document.createElement('div');
  holder.className = 'sensor-image';
  const image = liveImage;
  image.alt = '실시간 카메라 영상';
  holder.append(image);
  slot.replaceChildren(holder);
  slot.dataset.frameId = liveFrameId;
  slot.dataset.sessionId = liveSession;
  slot.dataset.frameCount = String(++displayedFrames);
}

document.addEventListener('maek:render', mountLiveFrame);
async function pollLiveCamera() {
  let pendingUrl = null;
  try {
    const response = await fetch(cameraBridge+'/api/camera', {cache:'no-store', signal:AbortSignal.timeout(2500)});
    if (!response.ok) throw Error('camera unavailable');
    const state = await response.json();
    if (!state.connected || !state.preview || state.ageSeconds > 3) throw Error('camera stale');
    const url = state.preview.url;
    if (!/^\/api\/frame\/[A-Za-z0-9_.~-]+$/.test(url)) throw Error('invalid frame');
    window.MAEK_LIVE_CAMERA = state;
    if (liveSession !== state.sessionId) { liveFrameId = null; liveImage = null; }
    if (state.preview.frameId !== liveFrameId) {
      const image = new Image();
      image.decoding = 'async';
      const frame = await fetch(cameraBridge+url, {cache:'no-store',signal:AbortSignal.timeout(2500)});
      if (!frame.ok) throw Error('frame unavailable');
      const bytes = await frame.arrayBuffer();
      const digest = await crypto.subtle.digest('SHA-256', bytes);
      const hash = Array.from(new Uint8Array(digest), b=>b.toString(16).padStart(2,'0')).join('');
      if (hash !== state.preview.imageSha256) throw Error('frame hash mismatch');
      pendingUrl = URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
      image.src = pendingUrl;
      // Keep the displayed frame until its replacement has decoded; never queue frames.
      await image.decode();
      if (liveBlobUrl) URL.revokeObjectURL(liveBlobUrl);
      liveBlobUrl = pendingUrl; pendingUrl = null;
      liveSession = state.sessionId; liveFrameId = state.preview.frameId; liveImage = image;
      lastFrameAt = Date.now();
      mountLiveFrame();
      await refreshModelPanels();
    }
  } catch {
    if (pendingUrl) URL.revokeObjectURL(pendingUrl);
    window.MAEK_LIVE_CAMERA = {connected:false};
    mountLivePosition();
    const slot = document.querySelector('[data-rgb-photo]');
    if (slot?.dataset.live === 'true' && Date.now()-lastFrameAt > 5000) {
      slot.dataset.live = 'false';
      slot.replaceChildren(Object.assign(document.createElement('div'), {className:'sensor-empty', textContent:'영상 연결 대기'}));
    }
  }
  setTimeout(pollLiveCamera, 150);
}
document.addEventListener('DOMContentLoaded', pollLiveCamera);
