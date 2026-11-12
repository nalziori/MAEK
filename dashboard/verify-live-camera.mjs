import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

let resolveDecode;
let response={connected:true,sessionId:'session',ageSeconds:.1,preview:{frameId:'f1',url:'/api/frame/f1',imageSha256:'0'.repeat(64)}};
const slot={dataset:{},content:'previous',replaceChildren(value){this.content=value;}};
const ctx=vm.createContext({window:{},Date,AbortSignal,Blob,URL:{createObjectURL:()=> 'blob:frame',revokeObjectURL(){}},crypto:{subtle:{digest:async()=>new Uint8Array(32).buffer}},setTimeout(){},
  fetch:async()=>({ok:true,json:async()=>response,arrayBuffer:async()=>new Uint8Array([1]).buffer}),
  refreshModelPanels:async()=>{},
  Image:class{decode(){return new Promise(resolve=>{resolveDecode=resolve;});}},
  document:{addEventListener(){},querySelector:()=>slot,createElement:()=>({append(image){this.image=image;}})}});
vm.runInContext(fs.readFileSync('dashboard/live-camera.js','utf8'),ctx);
let poll=vm.runInContext('pollLiveCamera()',ctx);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(slot.content,'previous','Keep existing frame while replacement decodes');
resolveDecode();await poll;
assert.equal(slot.dataset.frameId,'f1');
const displayed=slot.content;
response={...response,preview:{frameId:'f2',url:'/api/frame/f2',imageSha256:'0'.repeat(64)}};
poll=vm.runInContext('pollLiveCamera()',ctx);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(slot.content,displayed);
resolveDecode();await poll;
assert.equal(slot.dataset.frameId,'f2');
assert.equal(slot.dataset.frameCount,'2');
const current=slot.content;
response={connected:false};
await vm.runInContext('pollLiveCamera()',ctx);
assert.equal(slot.content,current,'Transient request failure must not blank the video');
assert.equal(ctx.window.MAEK_LIVE_CAMERA.connected,false);
console.log('Live camera: decode-before-swap, frame progression, bounded polling and transient-failure continuity passed');
