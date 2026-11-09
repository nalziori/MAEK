import assert from 'node:assert/strict';
import {validThermal,thermalHtml} from './thermal-view.mjs';
const id='a'.repeat(32),hash='b'.repeat(64);
const r={requestId:id,runId:id,sessionId:'c'.repeat(32),assetId:'THERMAL-DEMO-01',synthetic:true,workPermissionStatus:'not_assessed',width:320,height:256,status:'anomaly_observed',minC:25,maxC:50,meanC:30,referenceC:26,deltaC:24,roiPixels:2000,quality:{canInfer:true,message:'품질 통과'},findings:[{bbox:[80,90,130,150]}],rgbSha256:hash,geometrySha256:hash,temperatureSha256:hash,thermalSha256:hash,capturedAt:'2026-11-09T12:00:00Z'};
const o={requestId:id,runId:id,sessionId:r.sessionId,assetId:r.assetId,stage:'Complete',result:r};
assert(validThermal(o));assert(thermalHtml(o,'connected').includes('50.0'));
assert(thermalHtml(o,'connected').includes('CUI 확정'));
for(const changes of [{assetId:'BF1-Q005'},{requestId:'x'},{synthetic:false},{geometrySha256:'bad'},{maxC:NaN},{status:'no_anomaly_observed'},{findings:[{bbox:[-1,0,320,256]}]}])assert(!validThermal({...o,result:{...r,...changes}}));
for(const stage of ['Launching','Approaching','Settling','Analysing','Interrupted','Deferred']){
 const html=thermalHtml({...o,stage,result:null},'connected');assert(!html.includes('<img'));assert(!html.includes('50.0'));
}
assert(!thermalHtml(o,'disconnected').includes('<img'));
assert(thermalHtml(null,'connected').includes('촬영 기록 없음'));
console.log('Thermal UI: ID/hash/domain, malformed result, phase separation and unavailable-image checks passed');

const pipe='BF1-Q005',actual={...o,assetId:pipe,result:{...r,assetId:pipe}};
assert(validThermal(actual,pipe));assert(!validThermal(actual,'BF1-G004'));
const compact=thermalHtml(actual,'connected',pipe,true);assert(compact.includes('BF1-Q005'));assert(!compact.includes('Unity 촬영 RGB 크게 보기'));assert(compact.includes('합성 열화상 크게 보기'));
assert(!thermalHtml(o,'connected',pipe,true).includes('<img'));
