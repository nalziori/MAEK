import {validLiveThermal,chooseThermalPipe} from './thermal-stream-view.mjs';
const bridge='http://127.0.0.1:8765';
window.MAEK_LIVE_THERMAL={enabled:true,connected:false,frame:null};
let image=null,frameId=null,blobUrl=null,lastFrameAt=0,count=0,candidate=null,candidateSince=0,displayMeta=null;
function legend(){
 const node=document.createElement('div');node.className='thermal-display-legend';node.style.cssText='padding:8px 12px;color:#c1d4dc;background:#10232e;font-size:12px;text-align:left';
 if(!displayMeta?.hasValidTemperature){node.textContent='유효 온도 없음 / 판독 보류';return node;}
 const measured=document.createElement('div');
 measured.textContent=Number.isFinite(displayMeta.observedMinC)&&Number.isFinite(displayMeta.observedMaxC)?`최저 ${displayMeta.observedMinC.toFixed(1)}°C · 최고 ${displayMeta.observedMaxC.toFixed(1)}°C · 온도 차 ${(displayMeta.observedMaxC-displayMeta.observedMinC).toFixed(1)}°C`:'RGB 윤곽 융합 · 원본 온도 유지';node.append(measured);
 if(Array.isArray(displayMeta.scaleColors)&&displayMeta.scaleColors.length>=2&&displayMeta.scaleColors.every(c=>/^#[0-9a-f]{6}$/.test(c))){
  const bar=document.createElement('div');bar.style.cssText='height:9px;margin:7px 0 4px;border-radius:2px';bar.style.background=`linear-gradient(to right,${displayMeta.scaleColors.join(',')})`;node.append(bar);
 }
 const range=document.createElement('div');range.style.cssText='display:flex;justify-content:space-between';
 for(const value of [displayMeta.rangeMinC,displayMeta.rangeMaxC]){const tick=document.createElement('span');tick.textContent=`${value.toFixed(1)}°C`;range.append(tick);}node.append(range);
 const note=document.createElement('div');note.style.cssText='margin-top:4px;opacity:.8';note.textContent='합성 온도 · 자동 표시 범위 · RGB 윤곽 강조';node.append(note);return node;
}
const modal=document.createElement('dialog');modal.className='thermal-modal';modal.setAttribute('aria-label','실시간 열화상 확대');
modal.innerHTML='<header><h2>실시간 열화상</h2><button type="button" aria-label="열화상 닫기">닫기</button></header><div class="thermal-frame"></div><div class="thermal-display-meta"></div>';
document.body.append(modal);modal.querySelector('button').onclick=()=>modal.close();
function modalImage(){modal.querySelector('.thermal-frame').replaceChildren(image.cloneNode());modal.querySelector('.thermal-display-meta').replaceChildren(...(displayMeta?[legend()]:[]));}
function mount(){
 if(!image)return;
 document.querySelectorAll('[data-thermal-pipe]').forEach(slot=>{
  if(slot.dataset.thermalFrame===frameId)return;
  const button=document.createElement('button');button.type='button';button.className='sensor-image';button.setAttribute('aria-label','현재 열화상 크게 보기');
  button.append(image);button.onclick=()=>{modalImage();modal.showModal();};
  slot.replaceChildren(button,...(displayMeta?[legend()]:[]));slot.dataset.thermalFrame=frameId;slot.dataset.frameCount=String(count);
  slot.dataset.sourceFrame=window.MAEK_LIVE_THERMAL.frame?.sourceFrameId||'';
 });
 if(modal.open)modalImage();
}
function follow(frame){
 if(document.body.dataset.tab!=='home')return;
 const known=new Set(pipes.map(p=>p.id));
 const next=chooseThermalPipe(frame,window.MAEK_LIVE_CAMERA?.activePipe,selected.id,known);
 if(!next||next===selected.id){candidate=null;return;}
 if(candidate!==next){candidate=next;candidateSince=Date.now();return;}
 if(Date.now()-candidateSince>=500){followUnityPipe(next);candidate=null;}
}
document.addEventListener('maek:render',mount);
async function poll(){
 let pendingUrl=null;
 try{
  const response=await fetch(bridge+'/api/thermal-stream/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});
  if(!response.ok)throw Error('thermal unavailable');
  const state=await response.json(),frame=state.frame;
  if(!state.connected||!validLiveThermal(frame))throw Error('thermal stale or invalid');
  window.MAEK_LIVE_THERMAL={enabled:true,connected:true,frame};
  if(frame.frameId!==frameId){
   const result=await fetch(bridge+(frame.displayUrl||frame.imageUrl),{cache:'no-store',signal:AbortSignal.timeout(2500)});
   if(!result.ok)throw Error('thermal frame unavailable');
   const bytes=await result.arrayBuffer(),digest=await crypto.subtle.digest('SHA-256',bytes);
   const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
   if(hash!==(frame.displaySha256||frame.imageSha256))throw Error('thermal pixels mismatch');
   const next=new Image();next.decoding='async';next.width=frame.display?.width||frame.width;next.height=frame.display?.height||frame.height;next.alt=frame.display?'현재 카메라의 RGB 윤곽 융합 열화상':'현재 카메라의 열화상';
   pendingUrl=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));next.src=pendingUrl;await next.decode();
   if(blobUrl)URL.revokeObjectURL(blobUrl);blobUrl=pendingUrl;pendingUrl=null;
   image=next;displayMeta=frame.display||null;frameId=frame.frameId;lastFrameAt=Date.now();count++;
  }
  follow(frame);mount();await refreshModelPanels();
 }catch{
  if(pendingUrl)URL.revokeObjectURL(pendingUrl);
  window.MAEK_LIVE_THERMAL={enabled:true,connected:false,frame:null};
  if(modal.open)modal.close();
  if(Date.now()-lastFrameAt>5000){image=null;document.querySelectorAll('[data-thermal-pipe]').forEach(slot=>{slot.dataset.thermalFrame='';slot.replaceChildren(Object.assign(document.createElement('div'),{className:'sensor-empty',textContent:'열화상 연결 대기'}));});}
 }
 setTimeout(poll,150);
}
poll();
