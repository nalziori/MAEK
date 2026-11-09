const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const asset='THERMAL-DEMO-01',stages={Launching:'모의 이륙 중',Approaching:'배관 접근 중',Settling:'정지 · 표면 가시성 확인',Analysing:'온도 영상 분석 중',Complete:'분석 완료',Interrupted:'검사 중단 · 결과 미확정',Deferred:'촬영·분석 보류'};
export function validThermal(o,expectedAsset=asset){
 if(!o||o.assetId!==expectedAsset||!Object.hasOwn(stages,o.stage)||!/^\w{32}$/.test(o.requestId))return false;
 const r=o.result;if(!r)return o.stage!=='Complete';
 if(!['rgbSha256','geometrySha256','temperatureSha256','thermalSha256'].every(k=>typeof r[k]==='string'&&/^[a-f0-9]{64}$/.test(r[k])))return false;
 if(r.status==='anomaly_observed'&&(!r.quality?.canInfer||!r.findings?.length)||r.status!=='anomaly_observed'&&r.findings?.length||r.status==='indeterminate'&&r.quality?.canInfer)return false;
 return o.stage==='Complete'&&r.requestId===o.requestId&&r.assetId===expectedAsset&&r.runId===o.runId&&r.sessionId===o.sessionId&&r.synthetic===true&&r.workPermissionStatus==='not_assessed'&&r.width===320&&r.height===256&&['indeterminate','anomaly_observed','no_anomaly_observed'].includes(r.status)&&[r.minC,r.maxC,r.meanC,r.referenceC,r.deltaC].every(Number.isFinite)&&r.roiPixels>=500&&r.quality&&typeof r.quality.canInfer==='boolean'&&Array.isArray(r.findings)&&r.findings.every(f=>Array.isArray(f.bbox)&&f.bbox.length===4&&f.bbox.every(Number.isFinite)&&f.bbox[0]>=0&&f.bbox[1]>=0&&f.bbox[2]<=320&&f.bbox[3]<=256&&f.bbox[2]>f.bbox[0]&&f.bbox[3]>f.bbox[1]);
}
export function thermalHtml(o,connection,expectedAsset=asset,compact=false){
 const intro='<header class="thermal-title"><div><h2>열화상 · '+esc(expectedAsset)+'</h2><p>선택 배관의 촬영 관측 · 현장 실측 아님</p></div><span>합성 열화상 · 현장 실측 아님</span></header>';
 if(connection!=='connected')return intro+'<div class="thermal-message" role="status">열화상 연결 확인/실패 · 현재 영상·판정 표시 안 함</div>';
 if(!o)return intro+'<div class="thermal-message">촬영 기록 없음 · Unity에서 열화상 검사를 시작하세요.</div>';
 if(!validThermal(o,expectedAsset))return intro+'<div class="thermal-message">촬영 정보 불일치 · 판정 보류</div>';
 const r=o.result;
 if(!r)return intro+`<div class="thermal-message" role="status"><strong>${esc(stages[o.stage])}</strong><p>촬영 ID ${esc(o.requestId)}</p><p>분석 완료 전에는 이전 촬영 영상과 판정을 표시하지 않습니다.</p></div>`;
 const prefix='/api/thermal/file/'+r.requestId+'/';
 const boxes=r.findings.map(f=>`<rect x="${f.bbox[0]}" y="${f.bbox[1]}" width="${f.bbox[2]-f.bbox[0]}" height="${f.bbox[3]-f.bbox[1]}"/>`).join('');
 const label=r.status==='indeterminate'?'판독 불가 · 재확인 필요':r.status==='anomaly_observed'?'표면 온도 이상 후보 · 후속 검토 필요':'이번 합성 관측에서 이상 후보 미검출';
 const frame=(kind,title,overlay)=>`<figure><figcaption>${title}<button type="button" data-thermal-expand="${kind}" aria-label="${title} 크게 보기">확대 ↗</button></figcaption><div class="thermal-frame"><img src="${prefix+kind+'.png'}" width="320" height="256" alt="${esc(expectedAsset)} 동일 촬영 ${title}">${overlay?`<svg viewBox="0 0 320 256" aria-hidden="true">${boxes}</svg>`:''}</div></figure>`;
 return intro+`<div class="thermal-verdict" role="status"><strong>${label}</strong><span>${esc(r.quality.message)}</span></div><div class="thermal-images">${compact?'':frame('rgb','Unity 촬영 RGB',false)}${frame('thermal','합성 열화상',true)}</div><div class="thermal-legend"><span>10°C</span><i></i><span>100°C</span><small>고정 색상 범위 · 범위 밖 온도는 색상 포화</small></div><dl class="thermal-stats"><div><dt>배관 최대</dt><dd>${r.maxC.toFixed(1)}<small> °C</small></dd></div><div><dt>배관 평균</dt><dd>${r.meanC.toFixed(1)}<small> °C</small></dd></div><div><dt>비교 영역 대비 ΔT</dt><dd>${r.deltaC.toFixed(1)}<small> °C</small></dd></div><div><dt>관심영역</dt><dd>${r.roiPixels.toLocaleString()}<small> px</small></dd></div></dl><p class="thermal-scope">${r.profile?`가정 유체 온도 ${Number(r.profile.fluidC).toFixed(1)}°C · `:''}${esc(r.scope||'합성 온도 가정')} · CUI 확정·작업허가가 아닙니다.</p><details class="thermal-details"><summary>촬영 근거·원본 온도 자료</summary><dl><dt>촬영 ID</dt><dd>${esc(r.requestId)}</dd><dt>촬영 시각</dt><dd>${esc(r.capturedAt)}</dd><dt>RGB SHA256</dt><dd>${esc(r.rgbSha256)}</dd><dt>기하 SHA256</dt><dd>${esc(r.geometrySha256)}</dd><dt>온도 SHA256</dt><dd>${esc(r.temperatureSha256)}</dd></dl><p>Unity 카메라 첫 표면 교차로 구한 배관 관심영역 · 배경은 15°C로 가정합니다.</p><a href="${prefix}rgb.png" download>같은 촬영의 RGB</a> · <a href="${prefix}temperature.npy" download>원본 온도 배열</a> · <a href="${prefix}temperature16.png" download>16비트 온도 PNG</a> · <a href="${prefix}capture.json" download>촬영 자세·가정</a></details>`;
}

export function thermalPhotoHtml(o,connection,pipe){
 const empty=message=>`<div class="sensor-empty"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v16H4zM8 15l3-3 3 2 3-5"/></svg><strong>${esc(message)}</strong></div>`;
 if(connection!=='connected')return empty('열화상 연결 확인 중');
 if(!o)return empty('열화상 사진 미연결');
 if(!validThermal(o,pipe))return empty('촬영 정보 불일치');
 if(!o.result)return empty(stages[o.stage]);
 return `<button type="button" class="sensor-image" data-thermal-expand="thermal" aria-label="${esc(pipe)} 열화상 사진 크게 보기"><img src="/api/thermal/file/${o.requestId}/thermal.png" width="320" height="256" alt="${esc(pipe)} 합성 열화상 사진"><span class="image-expand"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m0-5 6 6M16 3h5v5m0-5-6 6M3 16v5h5m-5 0 6-6m7 6h5v-5m0 5-6-6"/></svg></span></button>`;
}
