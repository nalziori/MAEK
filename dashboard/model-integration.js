"use strict";
const autoOriginals = new Map();
let autoVersion = '';
let liveModelRGB = null;
let liveModelThermal = null;
window.MAEK_LIVE_THERMAL={enabled:true,connected:false,frame:null};
async function pollUnityModels() {
  let data = {pipes: {}, connected: {}};
  try {
    const response = await fetch('/api/model-results?summary=1', {cache: 'no-store', signal: AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error('unavailable');
    data = await response.json();
  } catch {}
  const version = JSON.stringify(data);
  liveModelRGB = data.liveRGB || null;
  liveModelThermal = data.liveThermal || null;
  if (version !== autoVersion) {
    autoVersion = version;
    for (const [key, old] of autoOriginals) {
      const [pipe, kind] = key.split('/');
      if (!data.connected[kind] || !data.pipes?.[pipe]?.[kind]) {
        window.MAEK_EVIDENCE.byPipe[pipe][kind] = old;
        autoOriginals.delete(key);
      }
    }
    for (const [pipe, sensors] of Object.entries(data.pipes || {})) {
      if (!pipes.some(p => p.id === pipe)) continue;
      for (const [kind, evidence] of Object.entries(sensors)) {
        if (!data.connected[kind]) continue;
        const key = `${pipe}/${kind}`;
        window.MAEK_EVIDENCE.byPipe[pipe] ||= {};
        if (!autoOriginals.has(key)) autoOriginals.set(key, window.MAEK_EVIDENCE.byPipe[pipe][kind]);
        window.MAEK_EVIDENCE.byPipe[pipe][kind] = evidence;
      }
    }
    if (typeof refreshModelPanels === 'function') await refreshModelPanels();
    else render();
  }
  setTimeout(pollUnityModels, 500);
}
document.addEventListener('DOMContentLoaded', pollUnityModels);
function modelVerdict(kind, evidence) {
  let pending='영상 수신 대기';
  if (kind === 'rgb' && window.MAEK_LIVE_CAMERA?.connected) {
    evidence = liveModelRGB?.sessionId === window.MAEK_LIVE_CAMERA.sessionId && Date.now()/1000-liveModelRGB.analysedAt < 5 ? liveModelRGB : null;
  }
  if(kind==='thermal'&&window.MAEK_LIVE_THERMAL?.enabled){
    const state=window.MAEK_LIVE_THERMAL,frame=state.frame;
    const target=typeof selected!=='undefined'?selected.id:null;
    const pipe=frame?.visiblePipes?.find(p=>p.pipeId===target);
    pending=!state.connected?'열화상 연결 대기':!frame?.visiblePipes?.length?(frame?.unprofiledPipeIds?.length?'현재 배관 온도 정보 없음':'관측 가능한 배관 없음'):!frame.canInfer||!pipe?.canInfer?'해당 배관 판독 보류':'새 프레임 분석 중';
    evidence=state.connected&&frame?.canInfer&&pipe?.canInfer&&liveModelThermal?.sessionId===frame?.sessionId&&Date.now()/1000-liveModelThermal.analysedAt<5&&liveModelThermal.visiblePipeIds?.includes(target)?liveModelThermal:null;
    if(evidence){const regions=evidence.regions.filter(r=>r.pipeId===target);evidence={...evidence,regions,analysis_summary:regions.length?`열점 후보 ${regions.length}건`:'열점 후보 미검출'};}
  }
  const inferred = evidence?.source === 'unity_auto_model';
  return `<div class="sensor-analysis model-verdict" role="status" data-request-id="${inferred ? escapeHTML(evidence.requestId) : ''}" data-input-sha="${inferred ? escapeHTML(evidence.sha256 || '') : ''}"><span>${kind === 'rgb' ? '부식 모델' : '열화상 모델'} · ${inferred ? '판정' : '대기'}</span><strong>${escapeHTML(inferred ? evidence.analysis_summary.replace(/^RGB/, '부식') : pending)}</strong>${inferred ? `<details><summary>모델·판독 범위</summary><p>${escapeHTML(evidence.model)}</p><p>${escapeHTML(evidence.quality_status || '후속 확인 필요')}</p></details>` : ''}</div>`;
}
