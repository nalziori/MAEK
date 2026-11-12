export function validLiveThermal(frame){
 if(!frame||frame.schemaVersion!==1||!/^[a-f0-9]{32}$/.test(frame.frameId)||typeof frame.sessionId!=='string'||!Number.isInteger(frame.sequence)||frame.sequence<0||frame.sourceFrameId!==`${frame.sessionId}-preview-${frame.sequence}`)return false;
 if(frame.synthetic!==true||frame.workPermissionStatus!=='not_assessed'||typeof frame.canInfer!=='boolean'||!Number.isInteger(frame.width)||!Number.isInteger(frame.height)||frame.width<16||frame.width>320||frame.height<9||frame.height>180||Math.abs(frame.width/frame.height-16/9)>.001)return false;
 if(frame.imageUrl!==`/api/thermal-stream/frame/${frame.frameId}/model-input.png`||!['imageSha256','rgbSha256','temperatureSha256'].every(k=>/^[a-f0-9]{64}$/.test(frame[k])))return false;
 if(frame.displayUrl!=null&&(frame.displayUrl!==`/api/thermal-stream/frame/${frame.frameId}/display.png`||!/^[a-f0-9]{64}$/.test(frame.displaySha256)||frame.display?.mode!=='rgb_contour_fusion'||!Number.isInteger(frame.display.width)||!Number.isInteger(frame.display.height)||frame.display.width<16||frame.display.width>960||frame.display.height<9||frame.display.height>540||typeof frame.display.hasValidTemperature!=='boolean'||frame.display.hasValidTemperature&&(!Number.isFinite(frame.display.rangeMinC)||!Number.isFinite(frame.display.rangeMaxC)||frame.display.rangeMaxC<=frame.display.rangeMinC)))return false;
 return Array.isArray(frame.visiblePipes)&&new Set(frame.visiblePipes.map(p=>p.pipeId)).size===frame.visiblePipes.length&&frame.visiblePipes.every(p=>typeof p.pipeId==='string'&&typeof p.service==='string'&&Number.isInteger(p.pixels)&&p.pixels>0&&Number.isInteger(p.validPixels)&&p.validPixels>=0&&p.validPixels<=p.pixels&&typeof p.canInfer==='boolean'&&[p.minC,p.maxC,p.meanC].every(Number.isFinite)&&p.minC<=p.meanC&&p.meanC<=p.maxC);
}
export function chooseThermalPipe(frame,active,current,known){
 const rows=frame.visiblePipes.filter(p=>known.has(p.pipeId)&&p.pixels>0);
 if(rows.some(p=>p.pipeId===active))return active;
 if(rows.some(p=>p.pipeId===current))return current;
 return [...rows].sort((a,b)=>b.pixels-a.pixels)[0]?.pipeId||null;
}
