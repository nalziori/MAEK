// Simulation controller: the whole UI is derived from time t (state = f(t)), so seeking is free.
import { createScene } from "./scene.js";
import { inferPitting, loadCnn } from "./cnn.js";

const $ = (s) => document.querySelector(s);
const END = 120;
const PHASES = [
  { n: 1, name: "부식 탐지 · RGB", from: 0, to: 20, pipe: "BF1-G003" },
  { n: 2, name: "누설 탐지 · 열화상", from: 20, to: 40, pipe: "BF1-G004" },
  { n: 3, name: "피팅 검사 · 로봇팔 UT", from: 40, to: 100, pipe: "BF1-G005" },
  { n: 4, name: "착륙", from: 100, to: 120 },
];
const PIPES = [
  { id: "BF1-G001", name: "고로 상승관 (업테이크 1)" },
  { id: "BF1-G002", name: "고로 상승관 (업테이크 2)" },
  { id: "BF1-G003", name: "하강관 (다운커머) → 제진기" },
  { id: "BF1-G004", name: "제진기 → 습식 집진기" },
  { id: "BF1-G005", name: "습식 집진기 → TRT 수직관" },
  { id: "BF1-G006", name: "TRT 출구 → 가스 본관" },
];
const ON_ROUTE = { "BF1-G003": [4, 18], "BF1-G004": [20, 38], "BF1-G005": [40, 85] }; // inspecting from, verdict at

const [results, ascan] = await Promise.all([fetch("data/results.json").then((r) => r.json()), fetch("data/ascan.json").then((r) => r.json())]);
const C = results.corrosion, L = results.leak;
let cnn = null, cnnStarted = false;
const pct = (x) => (x > 0.999 ? ">99.9" : (x * 100).toFixed(1)) + "%";

function events() {
  const ev = [
    [0, "이륙 · BF1-G003 하강관 상부 진입"],
    [4, "RGB 카메라 다각도 촬영 시작 (나선 하강)"],
    [14, "부식 후보 프레임 포착 → 부식 분할 모델 추론"],
    [18, `BF1-G003 부식 의심 · 신뢰도 ${pct(C.confidence)}`, "alert"],
    [20, "제진기(BF1.DC) 둘레 나선 하강 · 열화상 촬영"],
    [32, "열화상 고온부 포착 → 열화상 이상 탐지 모델 추론"],
    [38, `BF1-G004 누설 의심 · 신뢰도 ${pct(L.confidence)}`, "alert"],
    [40, "BF1-G005 수직관으로 이동"],
    [55, "피팅 의심 구간 정지 비행 · 로봇팔 전개"],
    [60, "UT 탐촉자 접촉 · A-scan 수신 시작"],
    [82, "A-scan 수신 완료 → 피팅 판정 CNN 추론 (브라우저)"],
  ];
  if (cnn) ev.push([85, cnn.pitting ? `BF1-G005 피팅 의심 · 확률 ${pct(cnn.probability)}` : `BF1-G005 피팅 없음 · 확률 ${pct(cnn.probability)}`, cnn.pitting ? "alert" : ""]);
  ev.push([92, "로봇팔 회수"], [100, "착륙 지점으로 하강"], [118, "착륙 완료 · 의심 배관 3건 기록"]);
  return ev;
}

function state(t) {
  const phase = PHASES.find((p) => t < p.to) || PHASES[3];
  const alerts = new Set(), pipes = {};
  for (const p of PIPES) {
    const r = ON_ROUTE[p.id];
    if (!r) { pipes[p.id] = { cls: "off", text: "이번 경로 외" }; continue; }
    if (t < r[0]) pipes[p.id] = { cls: "", text: "점검 전" };
    else if (t < r[1]) pipes[p.id] = { cls: "active", text: p.id === "BF1-G005" && t >= 60 ? "UT 측정 중" : "점검 중" };
    else if (p.id === "BF1-G003") pipes[p.id] = { cls: "alert", text: "부식 의심", value: `부식 분할 · 신뢰도 ${pct(C.confidence)}` };
    else if (p.id === "BF1-G004") pipes[p.id] = { cls: "alert", text: "누설 의심", value: `열화상 탐지 · 신뢰도 ${pct(L.confidence)}` };
    else if (!cnn) pipes[p.id] = { cls: "active", text: "추론 중" };
    else pipes[p.id] = cnn.pitting ? { cls: "alert", text: "피팅 의심", value: `피팅 CNN · 확률 ${pct(cnn.probability)} (logit ${cnn.logit.toFixed(1)})` }
      : { cls: "ok", text: "정상", value: `피팅 CNN · 확률 ${pct(cnn.probability)}` };
    if (pipes[p.id].cls === "alert") alerts.add(p.id);
  }
  return { t, phase, pipes, alerts, events: events().filter((e) => e[0] <= t) };
}

// ---------- static UI ----------
$("#phases").innerHTML = PHASES.map((p) => `<li><button type="button" data-seek="${p.from}"><span class="n">${p.n}</span><span>${p.name}</span><span class="tm">${fmt(p.from)}–${fmt(p.to)}</span></button></li>`).join("");
$("#pipes").innerHTML = PIPES.map((p) => `<li class="pipe" id="p-${p.id}"><span class="lamp" aria-hidden="true"></span><span class="id">${p.id}</span><span class="nm">${p.name}</span><span class="st"></span></li>`).join("");
$("#segs").innerHTML = PHASES.map((p) => `<span style="flex:${p.to - p.from}"><i></i>${p.pipe ? `<em style="left:${(ON_ROUTE[p.pipe][1] - p.from) / (p.to - p.from) * 100}%"></em>` : ""}</span>`).join("");
function fmt(s) { s = Math.floor(s); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }

// ---------- AI window ----------
let aiKey = "";
function ai(t) {
  const el = $("#ai");
  let key, title, html, cls = "body ai";
  const wait = (msg) => `<div class="wait"><span class="spin"></span>${msg}</div>`;
  if (t < 14) { key = "c0"; title = "부식 분할 모델 (YOLOv8-seg)"; html = wait("드론 RGB 프레임 수신 중"); }
  else if (t < 20) {
    key = "c" + (t >= 16) + (t >= 18); title = "부식 분할 모델 (YOLOv8-seg)";
    html = `<div class="pane"><span class="lab">입력 · RGB 프레임</span><div class="frame"><img src="data/rgb_input.jpg" alt="부식 후보 RGB 프레임"></div></div><span class="arrow">→</span>
      <div class="pane"><span class="lab">출력 · 부식 영역</span><div class="frame">${t >= 16 ? `<img src="data/rgb_output.jpg" alt="모델이 찾은 부식 영역 표시">` : `<span class="spin"></span>`}</div></div>
      <p class="result">${t >= 18 ? `<span class="chip red">부식 의심</span><b>${pct(C.confidence)}</b><span>BF1-G003</span>` : "추론 중…"}</p>`;
  } else if (t < 32) { key = "l0"; title = "열화상 이상 탐지 모델 (YOLOv8s)"; html = wait("열화상 프레임 수신 중"); }
  else if (t < 40) {
    key = "l" + (t >= 35) + (t >= 38); title = "열화상 이상 탐지 모델 (YOLOv8s)";
    const b = L.box_xyxy_norm;
    const box = t >= 35 ? `<span class="box" style="left:${b[0] * 100}%;top:${b[1] * 100}%;width:${(b[2] - b[0]) * 100}%;height:${(b[3] - b[1]) * 100}%"></span>` : "";
    html = `<div class="pane"><span class="lab">입력 · 열화상 프레임</span><div class="frame"><img src="data/ir_input.png" alt="열화상 프레임"></div></div><span class="arrow">→</span>
      <div class="pane"><span class="lab">출력 · 고온 이상 영역</span><div class="frame"><span style="position:relative;display:inline-block;line-height:0"><img src="data/ir_input.png" alt="모델이 찾은 고온 영역 표시">${box}</span></div></div>
      <p class="result">${t >= 38 ? `<span class="chip red">누설 의심</span><b>${pct(L.confidence)}</b><span>BF1-G004</span>` : "추론 중…"}</p>`;
  } else if (t < 60) { key = "p0"; title = "피팅 판정 1D-CNN (ONNX)"; html = wait(t < 55 ? "BF1-G005로 이동 중" : "로봇팔 전개 · 탐촉자 접촉 대기"); }
  else if (t < 100) {
    key = "p1" + (t >= 82) + !!cnn; title = "피팅 판정 1D-CNN (ONNX · 브라우저 추론)"; cls = "body ai scan";
    const r = cnn && t >= 85 ? `<span class="chip ${cnn.pitting ? "red" : "green"}">${cnn.pitting ? "피팅 의심" : "정상"}</span><b>${pct(cnn.probability)}</b><span>logit ${cnn.logit.toFixed(2)} · 임계 ${ascan.threshold_logit.toFixed(2)} · ${cnn.ms.toFixed(0)} ms</span>`
      : t >= 82 ? "추론 중…" : "A-scan 수신 중";
    html = `<span class="lab">입력 · 초음파 A-scan (${ascan.rf.length} 샘플, ${ascan.sampling_mhz} MHz)</span><div class="frame"><canvas id="scan"></canvas></div><p class="result">${r}</p>`;
  } else {
    key = "s" + !!cnn; title = "점검 요약";
    html = `<div class="wait" style="gap:8px"><b>의심 배관 3건</b><span>BF1-G003 부식 ${pct(C.confidence)} · BF1-G004 누설 ${pct(L.confidence)} · BF1-G005 피팅 ${cnn ? pct(cnn.probability) : "-"}</span></div>`;
  }
  if (key !== aiKey) { aiKey = key; el.className = cls; el.innerHTML = html; $("#ai-title").textContent = "AI · " + title; }
  const cv = $("#scan");
  if (cv) drawScan(cv, Math.min(1, Math.max(0, (t - 60) / 22)));
}
let scanScale = 0;
function drawScan(cv, frac) {
  const w = cv.parentElement.clientWidth - 2, h = cv.parentElement.clientHeight - 2;
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const g = cv.getContext("2d"), rf = ascan.rf, n = Math.floor(rf.length * frac);
  const m = scanScale ||= [...rf].map(Math.abs).sort((a, b) => a - b)[Math.floor(rf.length * 0.99)] * 1.5; // clip the initial pulse so echoes stay visible
  const clip = (v) => Math.max(-1, Math.min(1, v));
  g.clearRect(0, 0, w, h); g.strokeStyle = "#2b3038"; g.beginPath(); g.moveTo(0, h / 2); g.lineTo(w, h / 2); g.stroke();
  g.strokeStyle = "#5fd1ff"; g.beginPath();
  for (let x = 0; x < w; x++) {
    const a = Math.floor(x / w * rf.length), b = Math.floor((x + 1) / w * rf.length);
    if (a >= n) break;
    let lo = 1, hi = -1; for (let i = a; i < Math.min(b, n); i++) { lo = Math.min(lo, clip(rf[i] / m)); hi = Math.max(hi, clip(rf[i] / m)); }
    g.moveTo(x + 0.5, h / 2 - hi * h * 0.45); g.lineTo(x + 0.5, h / 2 - lo * h * 0.45);
  }
  g.stroke();
}

// ---------- render loop ----------
let t = 0, playing = false, last = 0, scene = null, endShown = false, lastEv = -1, lastPipes = "";
const params = new URLSearchParams(location.search);
function draw() {
  const s = state(t);
  scene?.render(t, s);
  ai(t);
  $("#clock").textContent = fmt(t);
  $("#head").style.left = `calc(${t / END * 100}% - 1px)`;
  $("#timeline").setAttribute("aria-valuenow", Math.floor(t));
  $("#timeline").setAttribute("aria-valuetext", fmt(t));
  [...$("#segs").children].forEach((el, i) => { const p = PHASES[i]; el.firstChild.style.transform = `scaleX(${Math.min(1, Math.max(0, (t - p.from) / (p.to - p.from)))})`; });
  document.querySelectorAll("#phases button").forEach((b, i) => { if (PHASES[i] === s.phase) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current"); });
  if (s.events.length !== lastEv) {
    const newAlert = s.events.length > lastEv && lastEv >= 0 ? s.events.slice(lastEv).find((e) => e[2] === "alert") : null;
    lastEv = s.events.length;
    $("#log").innerHTML = s.events.map((e) => `<li class="${e[2] || ""}"><time>${fmt(e[0])}</time><span>${e[1]}</span></li>`).join("");
    $("#log").scrollTop = 1e9;
    if (newAlert) $("#announce").textContent = newAlert[1];
  }
  const pj = JSON.stringify(s.pipes);
  if (pj !== lastPipes) {
    lastPipes = pj;
    for (const p of PIPES) {
      const st = s.pipes[p.id], li = document.getElementById("p-" + p.id);
      li.className = "pipe " + st.cls;
      li.querySelector(".st").innerHTML = `<span class="chip ${st.cls === "alert" ? "red" : st.cls === "ok" ? "green" : ""}">${st.text}</span>${st.value ? `<span>${st.value}</span>` : ""}`;
    }
  }
  $("#hud-rgb").textContent = `${fmt(t)} · ${s.phase.name}`;
  $("#hud-ir").textContent = "열화상";
}
function tick(now) {
  if (playing) {
    t = Math.min(END, t + Math.min(0.1, (now - last) / 1000));
    if (t >= 82 && !cnnStarted) runCnn();
    if (t >= END) { setPlaying(false); if (!endShown) { endShown = true; setTimeout(openTech, 600); } }
  }
  last = now;
  draw();
  requestAnimationFrame(tick);
}
function runCnn() { cnnStarted = true; inferPitting(ascan).then((r) => { cnn = r; lastPipes = ""; lastEv = -1; aiKey = ""; }); }
function setPlaying(on) {
  playing = on && t < END;
  $("#play-label").textContent = playing ? "일시정지" : t > 0 && t < END ? "이어서 재생" : "시뮬레이션 재생";
  $("#play-icon").setAttribute("d", playing ? "M7 4h4v16H7zM14 4h4v16h-4z" : "M7 4l13 8-13 8z");
}
function seek(s, play = true) {
  t = Math.max(0, Math.min(END, s));
  if (t >= 82 && !cnnStarted) runCnn();
  if (t < END) endShown = false;
  aiKey = ""; lastEv = -1; lastPipes = "";
  setPlaying(play);
}
$("#play").onclick = () => { if (t >= END) seek(0); else setPlaying(!playing); };
$("#restart").onclick = () => seek(0);
$("#phases").onclick = (e) => { const b = e.target.closest("[data-seek]"); if (b) seek(+b.dataset.seek); };
const tl = $("#timeline");
tl.addEventListener("click", (e) => { e.stopPropagation(); const r = tl.getBoundingClientRect(); seek((e.clientX - r.left) / r.width * END, playing); });
tl.addEventListener("keydown", (e) => { const d = { ArrowRight: 5, ArrowLeft: -5 }[e.key]; if (d) { e.preventDefault(); e.stopPropagation(); seek(t + d, playing); } });
addEventListener("keydown", (e) => {
  if (e.key === " " && !e.target.closest("button,[role=slider],dialog") && $("#coach").hidden) { e.preventDefault(); $("#play").click(); }
  if (e.key === "Escape" && bigWin && !$("#techdlg").open) setBig(null);
});

// ---------- bento: clicked window grows to 1.5x of the equal split (3fr:1fr = 75%) ----------
let bigWin = null;
function setBig(win) {
  bigWin = win === bigWin ? null : win;
  const st = $("#stage");
  st.style.gridTemplateColumns = bigWin ? (bigWin.dataset.col === "0" ? "3fr 1fr" : "1fr 3fr") : "1fr 1fr";
  st.style.gridTemplateRows = bigWin ? (bigWin.dataset.row === "0" ? "3fr 1fr" : "1fr 3fr") : "1fr 1fr";
  document.querySelectorAll(".win").forEach((w) => { w.classList.toggle("big", w === bigWin); w.querySelector(".grow").setAttribute("aria-expanded", w === bigWin); });
}
document.querySelectorAll(".win").forEach((w) => {
  w.addEventListener("click", (e) => { if (!e.target.closest(".timeline,.events")) setBig(w); });
});

// ---------- end modal: K-NewDeal academy topics -> MAEK ----------
const TECH = [
  ["9월 · 컴퓨터비전, YOLO 객체 검출", "드론 카메라 부식 분할 모델(YOLOv8-seg)과 열화상 이상 탐지 모델(YOLOv8s)을 학습했습니다.", "① 부식 · ② 누설 장면", 0],
  ["8월 · DNN·CNN 딥러닝", "초음파 A-scan 1D 신호로 피팅과 균열을 판정하는 1D-CNN을 만들었습니다.", "③ 피팅 판정 장면", 60],
  ["8월 · 머신러닝 분류·회귀·군집", "초음파 MLP 기준선을 만들고 검출률·오경보율로 모델을 비교했습니다.", "③ 피팅 판정 장면", 82],
  ["8월 · numpy·pandas·전처리·시각화", "A-scan 신호 처리와 결과 표·그래프를 만들었습니다.", "AI 창 · 로그", 60],
  ["9월 · Jetson Orin Nano 온디바이스 AI", "드론에 탑재할 수 있도록 열화상 모델을 128×160 입력으로 줄여 Jetson에서 돌렸습니다.", "드론 비행 전체", 20],
  ["7–8월 · Python·Git·GitHub·가상환경", "팀 저장소에서 PR과 CI로 협업했습니다.", "", null],
  ["7–8월 · LLM 에이전트·AI Fluency", "AI 도구로 개발하고, 결과는 사람이 검증했습니다.", "", null],
  ["9월 · ONNX 모델 변환·배포", "PyTorch 피팅 CNN을 ONNX로 변환해 이 웹페이지에 올렸습니다. 방금 본 피팅 판정은 브라우저에서 바로 추론한 결과입니다.", "③ 피팅 판정 장면", 82, "last"],
];
$("#techcards").innerHTML = TECH.map(([when, how, sc, at, cls]) => {
  const [w, what] = when.split(" · ");
  const inner = `<span class="when">${w}</span><span class="what">${what}</span><span class="how">${how}</span>${sc ? `<span class="scene">▶ ${sc}</span>` : ""}`;
  return at == null ? `<div class="${cls || ""}">${inner}</div>` : `<button type="button" class="${cls || ""}" data-at="${at}">${inner}</button>`;
}).join("");
$("#techcards").onclick = (e) => { const b = e.target.closest("[data-at]"); if (b) { $("#techdlg").close(); seek(+b.dataset.at); } };
function openTech() { if (!$("#techdlg").open) $("#techdlg").showModal(); }
$("#tech").onclick = openTech;

// ---------- coachmarks ----------
const STEPS = [
  [".stage", "고로 부생가스(BFG) 배관 점검", "이 시뮬레이션은 1고로의 부생가스 배관 점검입니다. 드론이 하강관과 제진기, 가스 배관 둘레를 천천히 돌며 내려가면서 다각도로 촬영하고, 부식·누설·피팅 의심 지점을 찾습니다. 약 2분 동안 진행됩니다."],
  ['[data-win="rgb"]', "드론 1인칭 RGB", "드론 카메라 화면입니다. 배관 표면의 부식을 찾습니다."],
  ['[data-win="ir"]', "드론 1인칭 열화상", "같은 위치의 열화상입니다. 가스 누설은 주변보다 뜨거운 지점으로 보입니다."],
  ['[data-win="ai"]', "AI 모델 입력 → 출력", "부식 분할, 열화상 이상 탐지, 초음파 피팅 판정 모델이 차례로 동작합니다. 모델이 무엇을 보고 어떻게 판단했는지 여기서 확인합니다."],
  ['[data-win="log"]', "이벤트 로그 · 타임라인", "드론과 AI가 한 일을 시간 순서로 기록합니다. 타임라인을 누르면 원하는 시점으로 이동합니다."],
  [".right", "구간 배관 · AI 판정", "이 구간에 속한 배관 ID와 AI 판정입니다. 의심이 나오면 해당 배관에 빨간 불이 켜집니다."],
  ['[data-win="rgb"]', "창 크게 보기", "재생 중에도 창을 누르면 1.5배로 커지고 다른 창은 작아집니다. 다시 누르면 원래대로 돌아옵니다. 지금 눌러 보세요."],
  ["#play", "시작해 볼까요?", "시뮬레이션 재생을 누르면 점검이 시작됩니다."],
];
let step = 0;
function showStep() {
  const [sel, title, text] = STEPS[step], r = $(sel).getBoundingClientRect(), pad = 6;
  Object.assign($("#spot").style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
  $("#tip-step").textContent = `가이드 ${step + 1} / ${STEPS.length}`;
  $("#tip-title").textContent = title; $("#tip-text").textContent = text;
  const last = step === STEPS.length - 1;
  $("#tip-next").textContent = last ? "시뮬레이션 재생" : "다음";
  $("#tip-prev").hidden = step === 0;
  const tip = $("#tip"), tw = 340, th = tip.offsetHeight || 200, vw = innerWidth, vh = innerHeight;
  let x = r.right + 16, y = r.top;
  if (x + tw > vw - 12) x = r.left - tw - 16;
  if (x < 12) { x = Math.min(Math.max(12, r.left + r.width / 2 - tw / 2), vw - tw - 12); y = r.bottom + 16 > vh - th ? Math.max(12, r.top - th - 16) : r.bottom + 16; }
  if (r.height > vh * 0.7) { x = r.left + r.width / 2 - tw / 2; y = r.top + r.height / 2 - th / 2; }
  tip.style.left = x + "px"; tip.style.top = Math.min(Math.max(12, y), vh - th - 12) + "px";
  $("#tip-next").focus();
}
function coach(on) { $("#coach").hidden = !on; if (on) { step = 0; showStep(); } }
$("#tip-next").onclick = () => { if (step === STEPS.length - 1) { coach(false); seek(0); } else { step++; showStep(); } };
$("#tip-prev").onclick = () => { step = Math.max(0, step - 1); showStep(); };
$("#tip-skip").onclick = () => coach(false);
$("#guide").onclick = () => { setPlaying(false); coach(true); };
addEventListener("resize", () => { if (!$("#coach").hidden) showStep(); });
$("#stage").addEventListener("transitionend", () => { if (!$("#coach").hidden) showStep(); });

// ---------- start ----------
$("#narrow-go").onclick = () => $("#narrow").classList.add("dismissed");
setPlaying(false);
requestAnimationFrame((n) => { last = n; tick(n); });
try {
  scene = await createScene($("#rgb"), $("#ir"), (f) => { $("#load-pct").textContent = Math.round(f * 100) + "%"; });
} catch (e) {
  $("#loading").innerHTML = `<p>3D 장면을 불러오지 못했습니다. 브라우저의 WebGL을 확인해 주세요.<br><a class="primary-link" href="../#3">시연 영상 보기</a></p>`;
  throw e;
}
$("#loading").hidden = true;
(requestIdleCallback || setTimeout)(() => loadCnn());
window.__sim = { get t() { return t; }, seek, state: () => state(t), get cnn() { return cnn; }, setBig };
if (params.has("t")) seek(+params.get("t"), false);
if (params.get("guide") !== "0" && !params.has("t")) coach(true);
