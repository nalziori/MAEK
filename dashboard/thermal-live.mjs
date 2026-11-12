import {thermalPhotoHtml,validThermal,thermalModelInputUrl} from './thermal-view.mjs';
let state={pipes:{}},connection='connecting',modalId=null,modalPipe=null,trigger=null;
const modal=document.createElement('dialog');modal.className='thermal-modal';modal.setAttribute('aria-label','열화상 촬영 영상 확대');modal.innerHTML='<header><h2>동일 촬영 영상</h2><button aria-label="열화상 영상 닫기">닫기</button></header><div></div>';document.body.append(modal);modal.querySelector('button').onclick=()=>modal.close();modal.addEventListener('close',()=>{modalId=null;modalPipe=null;if(trigger?.isConnected)trigger.focus();trigger=null;});
function selectedObservation(pipe){return state.pipes?.[pipe]??(state.observation?.assetId===pipe?state.observation:null);}
function mount(){
 if(window.MAEK_LIVE_THERMAL?.enabled)return;
 document.querySelectorAll('[data-thermal-pipe]').forEach(slot=>{
  const pipe=slot.dataset.thermalPipe,o=selectedObservation(pipe),model=window.MAEK_EVIDENCE?.byPipe?.[pipe]?.thermal,inputUrl=thermalModelInputUrl(o,model),key=JSON.stringify([connection,o,inputUrl]);
  if(slot.thermalKey!==key){const open=slot.querySelector('details')?.open;slot.innerHTML=thermalPhotoHtml(o,connection,pipe,false,inputUrl);slot.thermalKey=key;const panel=slot.closest('.sensor-panel');panel?.setAttribute('data-connected',String(connection==='connected'&&validThermal(o,pipe)&&!!o.result));if(open&&slot.querySelector('details'))slot.querySelector('details').open=true;}
 });
 if(modal.open){const o=selectedObservation(modalPipe);if(connection!=='connected'||!document.querySelector(`[data-thermal-pipe="${modalPipe}"]`)||!validThermal(o,modalPipe)||o.result?.requestId!==modalId)modal.close();}
}
document.addEventListener('maek:render',mount);
document.addEventListener('click',e=>{const button=e.target.closest('[data-thermal-expand]'),slot=button?.closest('[data-thermal-pipe]');if(!slot||connection!=='connected')return;const pipe=slot.dataset.thermalPipe,o=selectedObservation(pipe);if(!validThermal(o,pipe)||!o.result)return;const figure=document.createElement('figure'),caption=document.createElement('figcaption'),frame=document.createElement('div');caption.textContent=pipe+' · 합성 열화상 · 현장 실측 아님'+(o.result.quality.canInfer?'':' · 판독 보류');frame.className='thermal-frame';frame.append(button.querySelector('img').cloneNode(true));figure.append(caption,frame);modal.querySelector('div').replaceChildren(figure);modalId=o.requestId;modalPipe=pipe;trigger=button;modal.showModal();modal.querySelector('button').focus();});
async function poll(){if(window.MAEK_LIVE_THERMAL?.enabled||!document.querySelector('[data-thermal-pipe]')&&!modal.open){setTimeout(poll,1500);return;}try{const r=await fetch('/api/thermal',{cache:'no-store',signal:AbortSignal.timeout(3500)});if(!r.ok)throw Error();const data=await r.json();if(data.schemaVersion!==1||!data.pipes)throw Error();state=data;connection='connected';}catch{state={pipes:{}};connection='disconnected';}mount();setTimeout(poll,1500);}
mount();poll();
