/* Inject after dashboard scripts: <script src="/api/existing-dashboard-adapter.js" defer></script>.
 * Serve this file and sibling existing-dashboard-adapter.css on the same origin as /api/state.
 * No existing globals, saved evidence, localStorage, or source files are changed.
 */
(() => {
 'use strict';
 const scriptUrl = document.currentScript?.src || new URL('/api/existing-dashboard-adapter.js',location.href).href;
 function boot() {
  const screen = document.getElementById('screen');
  if(!screen || document.getElementById('maek-bridge')) return;
  const cssUrl = new URL('existing-dashboard-adapter.css',scriptUrl).href;
  if(![...document.querySelectorAll('link[rel="stylesheet"]')].some(link => link.href === cssUrl)){const css = document.createElement('link');css.rel = 'stylesheet';css.href = cssUrl;document.head.append(css);}
  const make = (tag,text = '',cls = '') => {const node = document.createElement(tag);node.textContent = text;if(cls) node.className = cls;return node;};
  const set = (node,value) => {const text = value === null || value === undefined || value === '' ? '—' : String(value);if(node.textContent !== text) node.textContent = text;};
  const list = value => Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const show = value => value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—');
  const frameUrl = value => typeof value === 'string' && /^\/api\/frame\/[A-Za-z0-9_.~-]+$/.test(value) ? value : null;
  const resultKey = a => [a?.sessionId,a?.requestId,a?.imageSha256].join('|');
  const ids = window.MAEK_OPERATIONS?.pipes || [];
  let mode = 'live',state = null,online = false,session = null,pending = null,sending = false,lastGood = 0;
  let liveId = null,liveToken = 0,selected = null,selection = '',followLatest = true,analysisToken = 0,analysisController = null,objectUrl = null,verified = false;
  let lastLayout = null,storedTitle = '';
  const buttons = new Map();
  const labels = {pause:'일시 정지',resume:'재개',stop:'중지',record_toggle:'녹화 켜기',view_toggle:'Unity 시점 전환'};
  const root = make('section','','maek-bridge');root.id = 'maek-bridge';root.setAttribute('aria-label','Unity 실시간 연결');
  const modeRow = make('div','','maek-bridge-row'),savedButton = make('button','저장 자료'),liveButton = make('button','실시간 RGB');
  const connection = make('span','로컬 브리지 연결 대기','maek-bridge-status');connection.setAttribute('role','status');
  modeRow.append(savedButton,liveButton,connection);root.append(modeRow);
  const controls = make('div','','maek-bridge-row');
  for(const command of ['pause','resume','stop']) {const button = make('button',labels[command]);button.type = 'button';button.onclick = () => send(command);buttons.set(command,button);controls.append(button);}
  root.append(controls);
  const more = make('details'),moreTitle = make('summary','녹화 · Unity 화면');more.append(moreTitle);const extra = make('div','','maek-bridge-row');
  for(const command of ['record_toggle','view_toggle']) {const button = make('button',labels[command]);button.type = 'button';button.onclick = () => send(command);buttons.set(command,button);extra.append(button);}more.append(extra);
  const capability = make('p','현재 검출: RGB 부식 색상 후보 · HSV 기준선','maek-bridge-help'),viewStatus = make('p','Unity 화면 시점: 미수신','maek-bridge-help');more.append(capability,viewStatus);root.append(more);
  const commandStatus = make('p','명령 없음 · 실제 Unity 응답으로 적용 여부를 확인합니다.','maek-bridge-command');commandStatus.setAttribute('role','status');root.append(commandStatus);screen.before(root);
  const flow = make('section','','inspection-flow maek-live-flow');flow.setAttribute('aria-label','실시간 가상 드론 관측, 저장 자료와 별도');
  const context = make('div','','pipe-context'),contextBody = make('div'),pipeTitle = make('h2','실시간 대상 대기'),flight = make('p','Unity 가상 드론 · 저장 배관 선택과 별도');contextBody.append(pipeTitle,flight);context.append(contextBody);flow.append(context);
  const coverageBox = make('div','','maek-live-coverage'),coverageSummary = make('strong','실시간 검사 범위 미수신'),coveragePlan = make('p'),coverageInspection = make('p');coverageBox.append(coverageSummary,coveragePlan,coverageInspection);contextBody.append(coverageBox);
  const evidence = make('div','','drone-evidence');
  function sensor(title,note,alt) {
   const panel = make('section','','sensor-panel'),heading = make('div','','sensor-heading');heading.append(make('h3',title),make('span',note));
   const frame = make('div','','sensor-image'),image = make('img');image.alt = alt;image.hidden = true;
   const empty = make('div','','sensor-empty');empty.append(make('strong','영상 수신 대기'),make('span','Unity 원본 영상이 수신되면 표시됩니다.'));frame.append(image,empty);
   const caption = make('div','','sensor-analysis'),summary = make('strong','미측정'),detail = make('span','');caption.append(summary,detail);panel.append(heading,frame,caption);evidence.append(panel);return {frame,image,empty,summary,detail};
  }
  const live = sensor('RGB · 실시간 원본','FPV 원본 · Unity 표시 시점과 별도','Unity 가상 드론의 실시간 FPV RGB 원본');
  const still = sensor('RGB · 분석 근거','해시 검증 정지 영상','선택한 분석 요청의 원본 정지 영상');
  const canvas = make('canvas');canvas.hidden = true;canvas.setAttribute('aria-hidden','true');still.frame.append(canvas);flow.append(evidence);
  const recordsPanel = make('section','','ndt-panel'),scope = make('p','열화상·UT 실시간 미연결 · 작업 허가 미판정. 저장 NDT는 “저장 자료”에서 별도로 검토합니다.');recordsPanel.append(scope);
  const guidance = make('p','','maek-live-warning');guidance.hidden = true;recordsPanel.append(guidance);
  const provenance = make('p','','maek-live-meta');recordsPanel.append(provenance);
  function section(title) {
   const details = make('details'),summary = make('summary',title),body = make('div','','maek-live-records');details.append(summary,body);recordsPanel.append(details);
   const panel = {details,summary,body,signature:'',bodyAt:null,timer:null};
   details.addEventListener('toggle',() => {if(panel.timer !== null) clearTimeout(panel.timer);panel.timer = null;panel.bodyAt = null;paint();});
   return panel;
  }
  function renderBody(panel,data,build) {
   if(!panel.details.open || document.body.dataset.maekView !== 'live') return;
   const elapsed = panel.bodyAt === null ? Infinity : Date.now()-panel.bodyAt;
   if(online && elapsed < 1000) {
    if(panel.timer === null) panel.timer = setTimeout(() => {panel.timer = null;if(panel.details.open && document.body.dataset.maekView === 'live') paint();},1000-elapsed);
    return;
   }
   const signature = JSON.stringify(data);if(signature === panel.signature) return;
   panel.signature = signature;panel.bodyAt = Date.now();build();
  }
  const access = section('촬영 접근·관측 상태 · 미수신'),records = section('실시간 RGB 분석 기록 · 0건'),mappings = section('실시간 배관 매핑 · 0건');access.body.tabIndex = 0;access.body.setAttribute('role','region');access.body.setAttribute('aria-label','전체 배관의 접근 계획과 실제 관측, 가로·세로 스크롤 가능');flow.append(recordsPanel);
  const locationPanel = make('div','','drone-location maek-live-location'),locationText = make('p'),follow = make('button','현재 배관의 저장 자료 보기');locationPanel.append(locationText,follow);
  follow.onclick = () => {const id = online ? state?.telemetry?.activePipe : null;if(!ids.some(p => p.id === id)) return;switchMode('saved');if(typeof navigate === 'function') navigate('home',id);};
  function isHome() {return document.body.dataset.tab === 'home';}
  function switchMode(value) {mode = value;paint();}
  savedButton.onclick = () => switchMode('saved');liveButton.onclick = () => switchMode('live');
  function enabled(command) {
   const t = state?.telemetry || {};if(!buttons.has(command) || !online || sending || pending) return false;
   if(['pause','resume','record_toggle','view_toggle'].includes(command) && t.active !== true) return false;
   if(command === 'pause' && t.paused === true || command === 'resume' && t.paused !== true) return false;
   return true;
  }
  function enableControls() {buttons.forEach((button,command) => button.disabled = !enabled(command));}
  function mount() {
   const layout = screen.querySelector('.unified-layout');
   if(layout !== lastLayout) {lastLayout = layout;storedTitle = document.getElementById('page-title')?.textContent || '';}
   if(layout && !layout.contains(flow)) layout.append(flow);
   const mapPanel = layout?.querySelector('.map-panel');if(mapPanel && !mapPanel.contains(locationPanel)) mapPanel.append(locationPanel);
   document.querySelectorAll('[data-map] .drone-mark').forEach(mark => {if(!mark.closest('.maek-live-marker')) mark.parentElement.classList.add('maek-stored-marker');});
  }
  const observer = new MutationObserver(() => paint());
  function paint() {
   observer.disconnect();
   try {
    mount();const liveMode = mode === 'live' && isHome();document.body.dataset.maekView = liveMode ? 'live' : 'saved';
    savedButton.setAttribute('aria-pressed',String(mode === 'saved'));liveButton.setAttribute('aria-pressed',String(mode === 'live'));
    controls.hidden = !liveMode;more.hidden = !liveMode;
    const modeLabel = document.querySelector('.data-mode');if(modeLabel) set(modeLabel,liveMode ? 'Unity 가상 드론 · '+(online ? '실시간 RGB' : '연결 없음') : '저장 자료 · 실시간 결과와 별도');
    const rail = document.querySelector('.side-nav .connection');if(rail) set(rail,online ? 'Unity 연결됨 · RGB' : '실시간 드론 미연결');
    if(isHome()) {const title = document.getElementById('page-title');if(title) set(title,liveMode ? 'Unity 가상 드론 검사' : storedTitle);}
    renderTelemetry();renderCoverage();renderRecords();renderMappings();renderSelected();renderLive();renderMap();enableControls();
   } finally {observer.observe(screen,{childList:true,subtree:true});const media = document.getElementById('media-content');if(media) observer.observe(media,{childList:true,subtree:true});}
  }
  function renderTelemetry() {
   const t = online ? state.telemetry || {} : {};
   set(connection,online ? 'Unity 연결됨 · '+state.ageSeconds.toFixed(1)+'초 전 수신' : 'Unity 연결 없음 · 실시간 상태 미수신');
   set(pipeTitle,online ? '실시간 대상 · '+(t.activePipe || '미지정') : '실시간 대상 미수신');
   const stopped = t.phase === 'scenario_stopped';
   const unfinished = finite(t.coverage?.totalPipes) && finite(t.coverage?.observedPipes) ? Math.max(0,t.coverage.totalPipes-t.coverage.observedPipes) : null;
   const finished = unfinished === null ? '경로 실행 종료 · 관측 완료는 별도 확인' : unfinished > 0 ? '경로 실행 종료 · 검사 미완료 '+unfinished+'개 배관' : '필수 영상 관측 완료 · 건전성 보증 아님';
   const status = !online ? '연결 끊김 · 과거 분석은 기록으로 유지' : stopped ? '수동 중지 · 미완료' : t.complete ? finished : t.paused ? '일시 정지' : t.active ? '실행 중' : '실행 대기';
   set(flight,status+' · '+(online ? t.status || t.phase || '상태 수신' : '저장 배관을 현재 대상으로 사용하지 않습니다.'));
   const coords = ['x','y','z'].map(axis => finite(t.position?.[axis]) ? t.position[axis].toFixed(2) : '—').join(' / ');
   const known = online && ids.some(p => p.id === t.activePipe);
   set(locationText,(online ? '실시간 대상 '+(t.activePipe || '미지정') : '실시간 위치 미수신')+' · Unity X/Y/Z '+coords+' · 분석 '+(t.analysedPipes ?? '—')+'/'+(t.plannedPipes ?? '—')+' · 촬영 '+(t.captures ?? '—')+'/'+(t.expectedCaptures ?? '—')+' · 충돌 단계 '+(t.collisionSteps ?? '—')+(online && !known ? ' · 현재 배관은 저장 지도 247개 목록에 없습니다.' : ''));
   follow.hidden = !known;
   const advice = online && typeof t.guidance === 'string' ? t.guidance : '';set(guidance,advice);guidance.hidden = !advice;
   set(buttons.get('record_toggle'),t.recording ? '녹화 끄기' : '녹화 켜기');buttons.get('record_toggle').setAttribute('aria-pressed',String(t.recording === true));
   set(buttons.get('view_toggle'),'Unity 시점 전환');buttons.get('view_toggle').setAttribute('aria-pressed',String(t.droneView === 'fpv'));
   set(viewStatus,'Unity 화면 시점: '+(t.droneView === 'fpv' ? 'FPV' : t.droneView === 'chase' ? '드론 추적' : '미수신')+' · 전송 영상은 항상 FPV 원본');
  }
  function empty(sensor,title,detail) {set(sensor.empty.children[0],title);set(sensor.empty.children[1],detail);sensor.empty.hidden = false;sensor.image.hidden = true;}
  function renderLive() {
   const preview = state?.preview,url = online && state?.telemetry?.cameraAvailable !== false ? frameUrl(preview?.url) : null;
   set(live.summary,online ? 'FPV 원본 · '+(state.telemetry?.activePipe || '대상 미지정') : '실시간 영상 없음');
   set(live.detail,url ? '프레임 '+preview.frameId+' · '+(preview.imageSha256 || '해시 미제공') : '카메라 미수신을 정상 판정으로 사용하지 않습니다.');
   if(!url) {liveToken++;liveId = null;live.image.removeAttribute('src');empty(live,online ? 'Unity 카메라 영상 없음' : '실시간 연결 대기','카메라 활성화와 로컬 브리지 연결을 확인하세요.');return;}
   if(liveId === preview.frameId) return;liveId = preview.frameId;const token = ++liveToken;
   empty(live,'새 프레임 수신 중','실제 Unity 렌더 원본입니다.');
   live.image.onload = () => {if(token !== liveToken || !online) return;live.image.hidden = false;live.empty.hidden = true;};
   live.image.onerror = () => {if(token === liveToken) empty(live,'프레임 조회 실패','프레임 만료 또는 카메라 전송 상태를 확인하세요.');};live.image.src = url;
  }
  function outcome(a) {
   if(!online || a.sessionId !== session) return '과거 분석 · 현재 관측 아님';
   const o = list(state?.telemetry?.outcomes).find(o => o.requestId === a.requestId && o.pipeId === a.pipeId);
   const statuses = {not_visible:'대상 미관측 · 정상 판정 없음',quality_recheck:'품질 재확인 · 정상 판정 없음',error:'분석 오류',offline:'분석 통신 오류',analysis_error:'분석 오류'};
   return o ? (statuses[o.status] || show(o.status))+' · 대상 샘플 '+(o.visibleTargetSamples ?? '—') : '대상 관측·배관 매핑 미확인';
  }
  function rgb(a) {
   if(a.quality?.canInfer === false || a.quality?.code === 'low_light') return '저조도 · 판독 불가';
   if(a.status !== 'ok' || !Array.isArray(a.components)) return '분석 오류·미완료 · 판정 없음';
   return a.components.length ? '이미지 색상 후보 '+a.components.length+'개 (배관 매핑과 별도)' : '이미지 색상 후보 미검출 · 건전성 보증 아님';
  }
  function table(container,headers,rows) {
   const table = make('table'),head = make('thead'),heading = make('tr');headers.forEach(label => {const th = make('th',label);th.scope = 'col';heading.append(th);});head.append(heading);table.append(head);const body = make('tbody');rows.forEach(cells => {const row = make('tr');cells.forEach(value => {const td = make('td');if(value instanceof Node) td.append(value);else set(td,value);row.append(td);});body.append(row);});table.append(body);container.replaceChildren(table);
  }
  function renderCoverage() {
   const t = online ? state?.telemetry || {} : {},c = t.coverage;
   const rows = Array.isArray(t.access) ? list(t.access) : null;
   if(!rows || !c || typeof c !== 'object') {
    set(coverageSummary,'실시간 검사 범위 미수신 · 미관측은 정상 판정이 아닙니다.');coverageSummary.className = 'maek-live-warning';
    set(coveragePlan,'접근 가능한 촬영 계획과 실제 관측 완료를 별도로 확인합니다.');set(coverageInspection,'회색 파선은 미관측 배관이며 건전성을 뜻하지 않습니다.');set(access.summary,'촬영 접근·관측 상태 · 미수신');
    renderBody(access,[online,rows,c],() => access.body.replaceChildren(make('p','연결된 access·coverage 자료가 없습니다. 저장 배관 기록으로 대신 채우지 않습니다.')));return;
   }
   const unobserved = rows.filter(r => r.observationStatus === 'unobserved').length;
   const partial = rows.filter(r => r.observationStatus === 'partial').length;
   set(coverageSummary,'필수 관측 완료 '+show(c.observedPipes)+' / '+show(c.totalPipes)+'개 배관 · 미관측 '+unobserved+' · 부분 관측 '+partial);
   coverageSummary.className = unobserved || partial ? 'maek-live-warning' : '';
   set(coveragePlan,'촬영 접근 계획: '+show(c.scheduledPipes)+'개 배관 · 필수 '+show(c.requiredCaptures)+'회 중 계획 '+show(c.scheduledCaptures)+'회 / 접근 유예 '+show(c.deferredCaptures)+'회');
   set(coverageInspection,'검사 유예 '+show(c.deferredPipes)+'개 · 부분 검사 '+show(c.partialPipes)+'개 · 경로 종료와 검사 완료는 별도입니다. 회색 파선: 미관측');
   set(access.summary,'촬영 접근·관측 상태 · '+rows.length+'개 배관');
   renderBody(access,[online,rows,c],() => {
   if(!rows.length){access.body.replaceChildren(make('p','전송된 검사 대상이 없습니다.'));return;}
   const geometry = {accessible:'접근 계획 가능',partial:'일부 촬영점 접근 가능',deferred:'촬영 접근 유예'};
   const observation = {unobserved:'미관측',partial:'부분 관측',observed:'필수 영상 관측 완료'};
   const inspection = {deferred:'검사 유예 · 미완료',partial:'부분 검사 · 보완 필요',completed:'필수 영상 처리 완료'};
   const statuses = {inspection_deferred:'검사 유예 · 판정 없음',inspection_partial:'부분 검사 · 판정 보류',candidate_incomplete:'RGB 후보 있음 · 검사 미완료',candidate:'RGB 후보',no_rgb_candidate:'새 RGB 후보 없음 · 건전성 미확인'};
   table(access.body,['배관','촬영 접근 계획','실제 관측 / 검사','촬영 수 · 필수 / 계획 / 유예 / 분석','상태 / 접근 사유'],rows.map(r => [show(r.pipeId),geometry[r.accessStatus] || show(r.accessStatus),(observation[r.observationStatus] || show(r.observationStatus))+' / '+(inspection[r.inspectionStatus] || show(r.inspectionStatus)),[r.plannedImages,r.scheduledImages,r.deferredImages,r.analysedImages].map(show).join(' / '),(statuses[r.status] || show(r.status))+' · '+(Array.isArray(r.accessReasons) && r.accessReasons.length ? r.accessReasons.map(show).join(' / ') : '접근 유예 사유 없음 · 관측 상태는 별도')]));
   });
  }
  function renderRecords() {
   const data = list(state?.analyses);
   const latest = data.find(a => a.sessionId === session);if(latest && (followLatest || !selected)) choose(latest);
   set(records.summary,'실시간 RGB 분석 기록 · '+data.length+'건');
   renderBody(records,[data,online,state?.telemetry?.outcomes],() => {
   if(!data.length){records.body.replaceChildren(make('p','아직 수신한 실시간 분석이 없습니다. 저장 RGB 247개 자료는 이 목록에 포함하지 않습니다.'));return;}
   table(records.body,['근거 영상 / 촬영 요청 대상','이미지 관측 / 대상 관측','모델 / 품질 / 해시'],data.map(a => {
    const button = make('button',(a.pipeId || '대상 미지정')+' · '+a.requestId);button.type = 'button';button.onclick = () => {followLatest = resultKey(a) === resultKey(data[0]);choose(a);renderSelected();};
    return [button,rgb(a)+' · '+outcome(a),(a.model || '모델 미제공')+' · '+(a.quality?.code || '품질 미제공')+' · '+(finite(a.quality?.meanLuminance) ? '평균 휘도 '+a.quality.meanLuminance.toFixed(1)+' · ' : '')+(a.imageSha256 || '해시 미제공')];
   }));
   });
  }
  function renderMappings() {
   const data = online ? list(state?.telemetry?.mappedFindings) : [];set(mappings.summary,'실시간 배관 매핑 · '+data.length+'건');
   renderBody(mappings,[online,data],() => {
   if(!data.length){mappings.body.replaceChildren(make('p',online ? '실제 배관에 매핑된 후보가 아직 없습니다.' : '연결 없음 · 실시간 매핑 상태를 표시하지 않습니다.'));return;}
   table(mappings.body,['매핑 배관 / 가상 X·Y·Z','후보 / 후속 권고','요청 ID / 원본 해시'],data.map(m => [show(m.pipeId)+' · '+['x','y','z'].map(axis => finite(m.position?.[axis]) ? m.position[axis].toFixed(2) : '—').join('/'),(m.kind === 'surface_corrosion_candidate' ? '표면 부식 색상 후보' : show(m.kind))+' · '+show(m.recommendation),show(m.requestId)+' · '+show(m.imageSha256)]));
   });
  }
  function choose(a) {
   selected = a;const key = resultKey(a)+'|'+frameUrl(a.frameUrl);if(selection === key) return;selection = key;verified = false;canvas.hidden = true;analysisToken++;analysisController?.abort();const controller = new AbortController();analysisController = controller;
   if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl = null;}still.image.removeAttribute('src');empty(still,'분석 원본 확인 중','원본 해시와 이미지 크기를 검증합니다.');
   const token = analysisToken,url = frameUrl(a.frameUrl);if(!url){empty(still,'분석 원본 주소 없음','이 결과에는 조회 가능한 원본 프레임이 없습니다.');return;}
   const timer = setTimeout(() => controller.abort(),5000);
   (async () => {try {
    const response = await fetch(url,{signal:controller.signal,cache:'no-store'});if(!response.ok) throw new Error(response.status === 404 ? '원본 프레임 만료 (404)' : '원본 조회 실패 (HTTP '+response.status+')');
    const bytes = await response.arrayBuffer();if(token !== analysisToken) return;
    if(!window.crypto?.subtle || !/^[a-f0-9]{64}$/i.test(a.imageSha256 || '')) throw new Error('원본 SHA-256 검증 정보 없음');
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b => b.toString(16).padStart(2,'0')).join('');
    if(token !== analysisToken) return;if(digest !== a.imageSha256.toLowerCase()) throw new Error('원본 해시 불일치 · 상자를 표시하지 않습니다.');
    objectUrl = URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
    still.image.onload = () => {if(token !== analysisToken) return;verified = still.image.naturalWidth === a.width && still.image.naturalHeight === a.height;still.image.hidden = false;still.empty.hidden = true;draw();if(!verified) set(still.detail,'원본 크기 불일치 · 상자 미표시');};
    still.image.onerror = () => {if(token === analysisToken) empty(still,'원본 이미지 해독 실패','다른 분석 기록을 선택하세요.');};still.image.src = objectUrl;
   } catch(error) {if(token === analysisToken){verified = false;canvas.hidden = true;empty(still,error.message || '분석 원본 조회 실패','다른 분석 기록을 선택하거나 연결 상태를 확인하세요.');}}
   finally{clearTimeout(timer);}})();
  }
  function renderSelected() {
   if(!selected) {set(still.summary,'분석 결과 대기');set(still.detail,'색상 후보와 배관 매핑은 별도입니다.');set(provenance,'선택한 실시간 분석 요청 없음');return;}
   const a = selected;set(still.summary,rgb(a));set(still.detail,'촬영 요청 대상 '+show(a.pipeId)+' · '+outcome(a));
   set(provenance,(online && a.sessionId === session ? '' : '과거 세션 기록 · ')+'요청 '+show(a.requestId)+' · 샘플 '+show(a.sampleId)+' · SHA-256 '+show(a.imageSha256));draw();
  }
  function draw() {
   canvas.hidden = true;const a = selected;if(!a || !verified || a.status !== 'ok' || a.quality?.canInfer === false || a.quality?.code === 'low_light' || !finite(a.width) || !finite(a.height) || a.width <= 0 || a.height <= 0) return;
   const box = still.frame.getBoundingClientRect();if(!box.width || !box.height) return;canvas.width = Math.round(box.width);canvas.height = Math.round(box.height);const ctx = canvas.getContext('2d');if(!ctx) return;
   const scale = Math.min(canvas.width/a.width,canvas.height/a.height),ox = (canvas.width-a.width*scale)/2,oy = (canvas.height-a.height*scale)/2;ctx.strokeStyle = '#ffcf58';ctx.lineWidth = 2;
   list(a.components).forEach(c => {const b = c.bbox;if(!Array.isArray(b) || b.length !== 4 || !b.every(finite)) return;const x1 = Math.max(0,Math.min(a.width,b[0])),y1 = Math.max(0,Math.min(a.height,b[1])),x2 = Math.max(0,Math.min(a.width,b[2])),y2 = Math.max(0,Math.min(a.height,b[3]));if(x2 > x1 && y2 > y1) ctx.strokeRect(ox+x1*scale,oy+y1*scale,(x2-x1)*scale,(y2-y1)*scale);});canvas.hidden = false;
  }
  function renderMap() {
   document.querySelectorAll('.maek-live-marker,.maek-live-pipe,.maek-access-pipe').forEach(node => node.remove());
   document.querySelectorAll('[data-map]').forEach(map => {
   const svg = map.querySelector('svg');if(!svg) return;const t = online ? state.telemetry || {} : {};
   const source = map.querySelector('.map-source');if(source) set(source,document.body.dataset.maekView === 'live' ? '저장 지도 형상 · 실시간 위치 별도' : '저장 경로 재구성');
   if(document.body.dataset.maekView !== 'live' || !online) return;
   const hits = new Map([...svg.querySelectorAll('polyline[data-map-pipe]')].map(node => [node.dataset.mapPipe,node]));
   const hit = hits.get(t.activePipe);
   const create = (tag,attrs) => {const node = document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([key,value]) => node.setAttribute(key,String(value)));return node;};
   list(t.access).forEach(row => {const line = hits.get(row.pipeId);if(!line || !['unobserved','partial'].includes(row.observationStatus)) return;
    const overlay = create('polyline',{points:line.getAttribute('points'),class:'maek-access-pipe '+(row.observationStatus === 'unobserved' ? 'maek-access-unobserved' : 'maek-access-partial')});
    const title = create('title',{});title.textContent = row.pipeId+' · '+(row.observationStatus === 'unobserved' ? '미관측 · 검사 유예' : '부분 관측 · 검사 미완료');overlay.append(title);svg.append(overlay);
   });
   if(hit) svg.append(create('polyline',{points:hit.getAttribute('points'),class:'pipe-line maek-live-pipe'}));
   const p = t.position;if(!p || !['x','y','z'].every(axis => finite(p[axis])) || typeof project !== 'function') return;
   // operations.js uses the original model plane XY; Unity V(p) = (p[0], p[2], p[1]).
   const xy = project([p.x,p.z,p.y]);if(!xy.every(finite)) return;
   if(xy[0] < 0 || xy[0] > 1000 || xy[1] < 0 || xy[1] > 560){set(locationText,locationText.textContent+' · 드론 좌표가 저장 지도 범위 밖입니다. 위치를 임의로 표시하지 않습니다.');return;}
   const group = create('g',{class:'maek-live-marker','aria-label':'실시간 Unity 위치'});group.append(create('circle',{cx:xy[0],cy:xy[1],r:10,class:'drone-mark'}));const title = create('title',{});title.textContent = '실시간 '+show(t.activePipe)+' · Unity '+p.x+'/'+p.y+'/'+p.z;group.append(title);svg.append(group);
   });
  }
  async function json(url,options = {}) {const controller = new AbortController(),timer = setTimeout(() => controller.abort(),3500);try {const response = await fetch(url,{...options,signal:controller.signal,cache:'no-store'});const value = await response.json();if(!response.ok) throw new Error(value.message || 'HTTP '+response.status);return value;}finally{clearTimeout(timer);}}
  async function send(command) {
   if(!enabled(command)) return;const sentSession = session,payload = {command};sending = true;enableControls();set(commandStatus,'명령 전송 중');
   try {const reply = await json('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(session !== sentSession || !online){set(commandStatus,'전송 중 세션·연결 변경 · 적용 여부를 확인하세요.');return;}if(reply.status !== 'queued' || !reply.commandId) throw new Error('명령 접수 응답 오류');pending = {id:reply.commandId,at:Date.now()};set(commandStatus,labels[command]+' · 전송됨, Unity 적용 대기 · '+reply.commandId);}catch(error){set(commandStatus,'명령 전송 실패 · '+error.message);}finally{sending = false;enableControls();}
  }
  function accept(next) {
   if(!next || next.version !== 1) throw new Error('API v1 상태 응답이 아닙니다.');
   if(session !== next.sessionId){if(session !== null) set(commandStatus,'세션 변경 · 이전 명령은 새 세션에 적용하지 않습니다.');session = next.sessionId;pending = null;followLatest = true;liveId = null;}
   state = next;online = next.connected === true && finite(next.ageSeconds) && next.ageSeconds <= 5 && Boolean(session);lastGood = Date.now();
   const last = next.lastCommand;if(last && buttons.has(last.command) && (!pending || last.commandId === pending.id)){set(commandStatus,labels[last.command]+' · '+({queued:'전송됨 · 적용 대기',applied:'Unity 적용 완료',error:'Unity 적용 실패'}[last.status] || show(last.status))+(last.message ? ' · '+last.message : ''));if(['applied','error'].includes(last.status)) pending = null;}
   if(pending && Date.now()-pending.at > 15000) set(commandStatus,'Unity 명령 적용 지연 · 응답을 기다리고 있습니다.');paint();
  }
  function offline(message) {online = false;set(commandStatus,pending ? '연결 끊김 · 명령 적용 미확인. 재연결 후 상태를 확인하세요.' : message);paint();}
  async function poll() {try {accept(await json('/api/state'));}catch(error){offline('상태 수신 실패 · '+error.message);}finally{setTimeout(poll,500);}}
  window.addEventListener('resize',draw);if(typeof ResizeObserver !== 'undefined') new ResizeObserver(draw).observe(still.frame);
  window.addEventListener('pagehide',() => {analysisController?.abort();if(objectUrl) URL.revokeObjectURL(objectUrl);});
  setInterval(() => {if(online && Date.now()-lastGood > 5000) offline('상태 수신 지연 · 실시간 제어 중단');},1000);
  paint();poll();
 }
 if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
