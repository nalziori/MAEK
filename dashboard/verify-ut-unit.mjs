import assert from 'node:assert/strict';
import {renderUt,renderUtResult,waveformSvg,validRow} from './ut-view.mjs';
const result={requestId:'r1',pipeId:'BF1-Q005',sample:0,synthetic:true,workPermissionStatus:'not_assessed',sourceSha256:'be4be1f82633378c803ff3112d43738ad89b928778c1ba69033c738a624d1e6d',pitScore:.7,threshold:.5,pitAlarm:true,wallValid:true,mainWallMm:5.1,wave:Array(4096).fill(.1),recordedAt:'2026-11-09T12:00:10Z',model:'frozen pitting MLP ensemble D',source:'UT/examples/ascan.npz'};
const row={pipeId:'BF1-Q005',stage:'Complete',updatedAt:result.recordedAt,steps:['REFERENCE_START','WALK','SURFACE_PREPARATION','COUPLANT','CONTACT','ANALYSE','RESULT'],result,resultStatus:'verified'};
assert(validRow(row,'BF1-Q005'));
assert(renderUtResult(row,'connected','BF1-Q005').includes('피팅 의심'));
assert(renderUtResult(row,'connected','BF1-Q005').includes('5.10'));
assert.equal(renderUtResult(row,'connected','BF1-G004'),'');
assert.equal(renderUtResult(row,'disconnected','BF1-Q005'),'');
assert.equal(renderUtResult(null,'connected','BF1-Q005'),'');
assert.equal(renderUtResult({...row,resultStatus:'unverified_or_pending'},'connected','BF1-Q005'),'');
assert.equal(renderUtResult({...row,result:null},'connected','BF1-Q005'),'');
for(const stage of ['Waiting','ReferenceCheck','Walking','SurfacePreparation','Couplant','Contact','Analysing','Deferred','Interrupted']){
 assert.equal(renderUtResult({...row,stage,result:null,previous:result},'connected','BF1-Q005'),'');
}
assert(!validRow({...row,steps:['REFERENCE_START','RESULT']},'BF1-Q005'));
assert(!validRow({...row,steps:[...row.steps].reverse()},'BF1-Q005'));
assert(!validRow(row,'BF1-G004'));
assert(!validRow({...row,result:{...result,wave:[NaN]}},'BF1-Q005'));
assert(!validRow({...row,result:{...result,synthetic:false}},'BF1-Q005'));
assert(!validRow({...row,result:{...result,pitAlarm:false}},'BF1-Q005'));
const complete=renderUt(row,'connected');
assert(complete.includes('5.10'));assert(complete.includes('피팅 의심'));assert(complete.includes('<svg'));
assert(!complete.includes('안전 판정 완료'));
for(const stage of ['ReferenceCheck','Analysing','Deferred','Interrupted']){
 const html=renderUt({...row,stage,result:null,previous:result},'connected');
 assert(!html.includes('data-ut-wave'));assert(!html.includes('5.10'));
 assert(html.includes('이전 완료 검사'));
}
assert(renderUt(null,'disconnected').includes('연결 끊김'));
assert(renderUt(null,'invalid').includes('판정 보류'));
assert(renderUt(null,'connected').includes('미검사'));
const spike=Array(4096).fill(0);spike[123]=10;
assert(waveformSvg(spike).includes('샘플 인덱스'));assert(waveformSvg(spike).includes(',28.00'));assert(!waveformSvg(spike).includes('NaN'));
console.log('UT view: identity, malformed input, stage isolation, previous-result label, waveform peak checks passed');
