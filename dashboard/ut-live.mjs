import {renderUt,validRow,waveformSvg,stamp} from './ut-view.mjs';
let state={pipes:{}},connection='connecting',lastModalId=null,returnFocus=null;
const dialog=document.createElement('dialog');dialog.className='ut-modal';dialog.setAttribute('aria-label','초음파 A-scan 상세');
dialog.innerHTML='<header><h2>초음파 A-scan</h2><button type="button" aria-label="초음파 파형 닫기">닫기</button></header><div class="ut-modal-content"></div>';
document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();
dialog.addEventListener('close',()=>{lastModalId=null;if(returnFocus?.isConnected)returnFocus.focus();returnFocus=null;});
function mount(){
 const mode=document.querySelector('.data-mode');if(mode)mode.textContent=connection==='connected'?'RGB 저장 자료 · UT 기록 연동':connection==='connecting'?'RGB 저장 자료 · UT 연결 확인 중':'RGB 저장 자료 · UT 연결 끊김';
 document.querySelectorAll('[data-ut-pipe]').forEach(slot=>{
  const row=state.pipes?.[slot.dataset.utPipe],safe=validRow(row,slot.dataset.utPipe)?row:null;
  const version=JSON.stringify([safe,connection,!!row&&!safe]);if(slot.utVersion===version)return;
  const detailsOpen=slot.querySelector('details')?.open,focused=slot.contains(document.activeElement);
  slot.innerHTML=renderUt(safe,row&&!safe?'invalid':connection);slot.utVersion=version;
  if(detailsOpen&&slot.querySelector('details'))slot.querySelector('details').open=true;
  slot.closest('.ndt-panel')?.classList.toggle('has-ut',!!safe&&connection==='connected');
  if(focused)slot.querySelector('button,summary')?.focus({preventScroll:true});
 });
 if(dialog.open){const row=state.pipes?.[dialog.dataset.pipe];if(connection!=='connected'||!validRow(row,dialog.dataset.pipe)||row.result?.requestId!==lastModalId)dialog.close();}
}
document.addEventListener('maek:render',mount);
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-ut-expand]');if(!button)return;
 const pipe=button.dataset.utExpand,row=state.pipes?.[pipe];if(!validRow(row,pipe)||!row.result||connection!=='connected')return;
 const r=row.result;dialog.dataset.pipe=pipe;lastModalId=r.requestId;returnFocus=button;
 dialog.querySelector('.ut-modal-content').innerHTML=`${waveformSvg(r.wave)}<p>합성 A-scan · 예제 ${r.sample} · ${stamp(r.recordedAt)}</p><p>정규화 진폭 / 샘플 인덱스 · 실제 배관 측정 아님</p>`;
 dialog.showModal();dialog.querySelector('button').focus();
});
async function poll(){
 try{
  const response=await fetch('/api/ut',{cache:'no-store',signal:AbortSignal.timeout(3500)});
  if(!response.ok)throw Error('unavailable');const next=await response.json();
  if(next.schemaVersion!==1||next.error||!next.pipes||typeof next.pipes!=='object')throw Error('invalid data');
  state=next;connection='connected';
 }catch{state={pipes:{}};connection='disconnected';}
 mount();setTimeout(poll,2000);
}
mount();poll();
