// "Try the models": run the three MAEK models on fixed samples with onnxruntime-web (WASM, in the browser).
// YOLO pre/post-processing mirrors Ultralytics predict (letterbox 114, conf 0.25, per-class NMS 0.5,
// seg mask = sigmoid(coeffs . protos) cropped to the box, bilinear, > 0.5). verify-site.mjs checks the
// browser result against the PyTorch reference recorded by scripts/export_try_demo.py.
import * as ort from "../vendor/ort.wasm.min.mjs";

ort.env.wasm.wasmPaths = new URL("../vendor/", import.meta.url).href;
ort.env.wasm.numThreads = 1; // GitHub Pages has no cross-origin isolation

const $ = (s) => document.querySelector(s);
const DATA = new URL("data/", location.href);
const S = 640, IOU = 0.5, PROTO = 160; // Ultralytics 8.4 predict default NMS IoU (PREDICT_IOU)
const KO = { corrosion: "외부 부식", cui_sign: "CUI 흔적", leak_stain: "누설 얼룩", normal: "정상",
  steam_leak: "증기 누설", wet_insulation: "젖은 보온재", insulation_damage: "보온재 손상", hot_spot: "열점", pitting: "내부 피팅" };
const RED = [255, 71, 71];
const META = {
  corrosion: { title: ["입력 · 드론 RGB 영상", "AI 출력 · 부식 영역 분할"], info: [["모델", "YOLOv8n-seg · 실사진 재학습 v1"], ["찾는 것", "외부 부식, CUI 흔적(보온재 밑 부식), 누설 얼룩"], ["입력", "640×640 RGB"]] },
  thermal: { title: ["입력 · 드론 열화상", "AI 출력 · 열점 검출"], info: [["모델", "YOLOv8s · 실사진 재학습 v1"], ["찾는 것", "증기 누설·젖은 보온재·보온재 손상이 만드는 열점"], ["입력", "열화상 (inferno 색상)"]] },
  ultrasonic: { title: ["입력 · 초음파 A-scan 파형", "AI 출력 · 피팅 확률"], info: [["모델", "1D-CNN (cnn_dr)"], ["찾는 것", "배관 내부 피팅(점부식)"], ["입력", "4,096 샘플 · 100 MHz"]] },
};

let data, model = null, sample = null, result = null;
const sessions = {}, images = {};
// onnxruntime-web cannot run one session twice at once (fast clicks), so runs go through one queue.
let queue = Promise.resolve();
const run = (sess, feeds) => (queue = queue.catch(() => {}).then(() => sess.run(feeds)));

// ---------- loading ----------
async function fetchModel(kind) {
  const m = data[kind].model, url = new URL(m.file, DATA);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url.pathname}`);
  const total = +res.headers.get("content-length") || m.mb * 1e6;
  const reader = res.body.getReader(), parts = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value); got += value.length;
    busy(`모델 불러오는 중 ${Math.min(99, Math.round(got / total * 100))}% (${(got / 1e6).toFixed(1)} / ${m.mb} MB)`);
  }
  const buf = new Uint8Array(got);
  let o = 0;
  for (const p of parts) { buf.set(p, o); o += p.length; }
  busy("모델 준비 중");
  return ort.InferenceSession.create(buf);
}
const session = (kind) => (sessions[kind] ||= fetchModel(kind).catch((e) => { delete sessions[kind]; throw e; }));
const image = (src) => (images[src] ||= new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => bad(new Error(src)); i.src = new URL(src, DATA).href; }));

function busy(text, error = false) {
  $("#busy").hidden = !text;
  $("#busy").classList.toggle("error", error);
  $("#busy-text").textContent = text || "";
  $("#busy .spin").hidden = error;
}

// ---------- YOLO ----------
function letterbox(img) {
  const w = img.naturalWidth, h = img.naturalHeight, r = Math.min(S / w, S / h);
  const nw = Math.round(w * r), nh = Math.round(h * r);
  const left = Math.round((S - nw) / 2 - 0.1), top = Math.round((S - nh) / 2 - 0.1);
  const c = new OffscreenCanvas(S, S), g = c.getContext("2d", { willReadFrequently: true });
  g.fillStyle = "rgb(114,114,114)"; g.fillRect(0, 0, S, S);
  g.drawImage(img, left, top, nw, nh);
  const px = g.getImageData(0, 0, S, S).data, x = new Float32Array(3 * S * S);
  for (let i = 0; i < S * S; i++) { x[i] = px[i * 4] / 255; x[i + S * S] = px[i * 4 + 1] / 255; x[i + 2 * S * S] = px[i * 4 + 2] / 255; }
  return { tensor: new ort.Tensor("float32", x, [1, 3, S, S]), r, left, top, w, h };
}

function decode(out, nc, conf) {
  const [, C, N] = out.dims, d = out.data, cand = [];
  for (let j = 0; j < N; j++) {
    let best = 0, cls = 0;
    for (let c = 0; c < nc; c++) { const s = d[(4 + c) * N + j]; if (s > best) { best = s; cls = c; } }
    if (best <= conf) continue;
    const cx = d[j], cy = d[N + j], bw = d[2 * N + j], bh = d[3 * N + j];
    cand.push({ j, cls, score: best, box: [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], C });
  }
  cand.sort((a, b) => b.score - a.score);
  const keep = [];
  for (const c of cand) if (!keep.some((k) => k.cls === c.cls && iou(k.box, c.box) > IOU)) keep.push(c);
  return keep.slice(0, 300);
}

function iou(a, b) {
  const ix = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  return ix / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix);
}

// Mask of one detection at the original image size (Uint8Array, 1 = inside).
function segMask(det, out0, protos, nc, lb) {
  const N = out0.dims[2], P = PROTO * PROTO, m = new Float32Array(P), pd = protos.data;
  for (let k = 0; k < 32; k++) {
    const c = out0.data[(4 + nc + k) * N + det.j];
    for (let i = 0; i < P; i++) m[i] += c * pd[k * P + i];
  }
  const [x0, y0, x1, y1] = det.box, mask = new Uint8Array(lb.w * lb.h);
  for (let y = 0; y < lb.h; y++) {
    const ly = (y + 0.5) * lb.r + lb.top;
    if (ly < y0 || ly > y1) continue;
    const my = Math.min(PROTO - 1, Math.max(0, ly / 4 - 0.5)), y_ = Math.floor(my), fy = my - y_, y2 = Math.min(PROTO - 1, y_ + 1);
    for (let x = 0; x < lb.w; x++) {
      const lx = (x + 0.5) * lb.r + lb.left;
      if (lx < x0 || lx > x1) continue;
      const mx = Math.min(PROTO - 1, Math.max(0, lx / 4 - 0.5)), x_ = Math.floor(mx), fx = mx - x_, x2 = Math.min(PROTO - 1, x_ + 1);
      const v = (m[y_ * PROTO + x_] * (1 - fx) + m[y_ * PROTO + x2] * fx) * (1 - fy) + (m[y2 * PROTO + x_] * (1 - fx) + m[y2 * PROTO + x2] * fx) * fy;
      if (v > 0) mask[y * lb.w + x] = 1; // sigmoid(v) > 0.5
    }
  }
  return mask;
}

const toImage = (b, lb) => [(b[0] - lb.left) / lb.r, (b[1] - lb.top) / lb.r, (b[2] - lb.left) / lb.r, (b[3] - lb.top) / lb.r]
  .map((v, i) => Math.max(0, Math.min(i % 2 ? lb.h : lb.w, v)));

async function runYolo(kind, s) {
  const img = await image(s.image), sess = await session(kind), nc = data[kind].classes.length;
  busy("판정 중");
  const lb = letterbox(img), t0 = performance.now();
  const out = await run(sess, { [sess.inputNames[0]]: lb.tensor });
  const ms = performance.now() - t0;
  const out0 = out[sess.outputNames[0]], dets = decode(out0, nc, data.conf);
  return { ms, img, dets: dets.map((d) => ({
    cls: data[kind].classes[d.cls], score: d.score, box: toImage(d.box, lb),
    mask: kind === "corrosion" ? segMask(d, out0, out[sess.outputNames[1]], nc, lb) : null })) };
}

async function runUt(s) {
  const u = data.ultrasonic, sess = await session("ultrasonic");
  busy("판정 중");
  const x = Float32Array.from(s.rf, (v) => (v - u.rf_mean) / u.rf_std), t0 = performance.now();
  const out = await run(sess, { rf: new ort.Tensor("float32", x, [1, 1, x.length]) });
  const logit = out[sess.outputNames[0]].data[0];
  return { ms: performance.now() - t0, logit, p: 1 / (1 + Math.exp(-logit)), pitting: logit > u.threshold_logit };
}

// ---------- drawing ----------
function fit(canvas) {
  const r = canvas.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, r.width, r.height);
  return { g, W: r.width, H: r.height };
}

function placeImage(canvas, img) {
  const { g, W, H } = fit(canvas), pad = 12, k = Math.min((W - 2 * pad) / img.naturalWidth, (H - 2 * pad) / img.naturalHeight);
  const ox = (W - img.naturalWidth * k) / 2, oy = (H - img.naturalHeight * k) / 2;
  g.imageSmoothingQuality = "high";
  g.drawImage(img, ox, oy, img.naturalWidth * k, img.naturalHeight * k);
  return { g, k, ox, oy };
}

function maskImage(dets, w, h) {
  const c = new OffscreenCanvas(w, h), g = c.getContext("2d"), id = g.createImageData(w, h), px = id.data;
  for (const d of dets) {
    if (!d.mask) continue;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!d.mask[i]) continue;
      const edge = !d.mask[i - 1] || !d.mask[i + 1] || !d.mask[i - w] || !d.mask[i + w];
      px.set(edge ? [...RED, 255] : [...RED, 95], i * 4);
    }
  }
  g.putImageData(id, 0, 0);
  return c;
}

async function drawYolo() {
  const kind = model, s = sample, r = result;
  const img = await image(s.image);
  placeImage($("#in"), img);
  if (!r) { fit($("#out")); return; }
  const { g, k, ox, oy } = placeImage($("#out"), img), cw = $("#out").getBoundingClientRect().width;
  if (kind === "corrosion" && r.dets.length) g.drawImage(r.maskCanvas ||= maskImage(r.dets, img.naturalWidth, img.naturalHeight), ox, oy, img.naturalWidth * k, img.naturalHeight * k);
  if ($("#truth").checked) {
    if (s.truth_overlay) g.drawImage(await image(s.truth_overlay), ox, oy, img.naturalWidth * k, img.naturalHeight * k);
    g.setLineDash([6, 4]); g.strokeStyle = "#fff"; g.lineWidth = 2;
    for (const b of s.truth_boxes_norm || []) g.strokeRect(ox + b[0] * img.naturalWidth * k, oy + b[1] * img.naturalHeight * k, (b[2] - b[0]) * img.naturalWidth * k, (b[3] - b[1]) * img.naturalHeight * k);
    g.setLineDash([]);
  }
  g.font = "700 13px 'Pretendard Variable', sans-serif"; g.lineWidth = 2;
  for (const d of r.dets) {
    const [x0, y0, x1, y1] = d.box.map((v, i) => (i % 2 ? oy : ox) + v * k);
    g.strokeStyle = `rgb(${RED})`; g.strokeRect(x0, y0, x1 - x0, y1 - y0);
    const label = `${KO[d.cls]} ${Math.round(d.score * 100)}%`, tw = g.measureText(label).width + 12, ty = y0 > 24 ? y0 - 22 : y1 + 2;
    const tx = Math.max(0, Math.min(x0 - 1, cw - tw)); // keep the label inside the window
    g.fillStyle = `rgb(${RED})`; g.fillRect(tx, ty, tw, 20);
    g.fillStyle = "#fff"; g.fillText(label, tx + 6, ty + 15);
  }
}

function plotWave(canvas, rf, { axes = true } = {}) {
  const { g, W, H } = fit(canvas), pad = axes ? [16, 16, 34, 48] : [4, 4, 4, 4]; // top right bottom left
  const pw = W - pad[1] - pad[3], ph = H - pad[0] - pad[2];
  let m = 0;
  for (const v of rf) m = Math.max(m, Math.abs(v));
  m = m || 1;
  if (axes) {
    g.strokeStyle = "#343941"; g.lineWidth = 1; g.fillStyle = "#98a1ad"; g.font = "12px 'Pretendard Variable', sans-serif";
    for (let us = 0; us <= 40; us += 10) {
      const x = pad[3] + us / 40.96 * pw;
      g.beginPath(); g.moveTo(x, pad[0]); g.lineTo(x, pad[0] + ph); g.stroke();
      g.fillText(`${us} µs`, x - 12, H - 12);
    }
    g.beginPath(); g.moveTo(pad[3], pad[0] + ph / 2); g.lineTo(pad[3] + pw, pad[0] + ph / 2); g.stroke();
    g.fillText("진폭", 8, pad[0] + 12);
  }
  g.strokeStyle = "#4aa3df"; g.lineWidth = axes ? 1.2 : 1; g.beginPath();
  const step = Math.max(1, Math.floor(rf.length / (pw * 2)));
  for (let i = 0; i < rf.length; i += step) {
    const x = pad[3] + i / rf.length * pw, y = pad[0] + ph / 2 - rf[i] / m * ph / 2 * 0.95;
    i ? g.lineTo(x, y) : g.moveTo(x, y);
  }
  g.stroke();
}

function drawUt() {
  plotWave($("#in"), sample.rf);
  const { g, W, H } = fit($("#out"));
  if (!result) return;
  const thr = 1 / (1 + Math.exp(-data.ultrasonic.threshold_logit));
  const x0 = 40, x1 = W - 40, y = H / 2, bh = 36, wd = x1 - x0;
  g.fillStyle = "#262a30"; g.fillRect(x0, y - bh / 2, wd, bh);
  g.fillStyle = result.pitting ? `rgb(${RED})` : "#3fbf7f"; g.fillRect(x0, y - bh / 2, Math.max(2, wd * result.p), bh);
  g.strokeStyle = "#e3e7ec"; g.lineWidth = 2; g.setLineDash([5, 4]);
  g.beginPath(); g.moveTo(x0 + wd * thr, y - bh / 2 - 14); g.lineTo(x0 + wd * thr, y + bh / 2 + 14); g.stroke(); g.setLineDash([]);
  g.fillStyle = "#98a1ad"; g.font = "12px 'Pretendard Variable', sans-serif";
  g.fillText("0%", x0, y + bh / 2 + 30); g.fillText("100%", x1 - 30, y + bh / 2 + 30);
  g.fillText(`판정 기준 ${Math.round(thr * 100)}%`, x0 + wd * thr - 34, y - bh / 2 - 20);
  g.fillStyle = "#e3e7ec"; g.font = "800 28px 'Pretendard Variable', sans-serif";
  g.fillText(`피팅 확률 ${(result.p * 100).toFixed(1)}%`, x0, y - bh / 2 - 48);
}

const draw = () => (model === "ultrasonic" ? drawUt() : drawYolo());

// ---------- verdict + info ----------
function judge(kind, s, r) {
  if (!s.truth) { const top = r.dets[0]; return { label: top ? (kind === "thermal" ? "hot_spot" : top.cls) : "normal", score: top ? top.score : null, match: null }; }
  if (kind === "ultrasonic") return { label: r.pitting ? "pitting" : "normal", score: r.p, match: r.pitting === (s.truth === "pitting") };
  const top = r.dets[0];
  if (!top) return { label: "normal", score: null, match: s.truth === "normal" };
  const label = kind === "thermal" ? "hot_spot" : top.cls;
  return { label, score: top.score, match: kind === "thermal" ? s.truth !== "normal" : top.cls === s.truth };
}

function verdict() {
  const el = $("#verdict");
  if (!result) { el.innerHTML = `<p class="row"><span>샘플을 고르면 결과가 여기에 나옵니다.</span></p>`; return; }
  const j = judge(model, sample, result), n = model === "ultrasonic" ? null : result.dets.length;
  const found = model === "ultrasonic" ? KO[j.label] : n ? `${KO[j.label]} ${n}건` : "이상 없음";
  const real = sample.source === "real", ref = sample.reference || {}, ov = ref.mask_iou_vs_truth ?? ref.box_iou_vs_truth ?? 0;
  const chip = !sample.truth ? "" : real ? `<span class="chip ${ov >= 0.5 ? "green" : "red"}">${ref.detections ? `정답과 겹침 ${Math.round(ov * 100)}%` : "찾지 못함"}</span><span class="chip">실사진</span>`
    : `<span class="chip ${j.match ? "green" : "red"}">${j.match ? "정답과 일치" : "정답과 다름"}</span>`;
  const rows = [["정답", sample.truth ? KO[sample.truth] : "없음 (올린 사진)"], ["확신도", j.score == null ? "-" : `${(j.score * 100).toFixed(1)}%`], ["처리 시간", `${Math.round(result.ms)} ms`]];
  if (model === "ultrasonic") rows.push(["벽 두께", `${sample.wall_mm} mm`], ["피팅 깊이", sample.pit_depth_mm ? `${sample.pit_depth_mm} mm` : "-"]);
  el.innerHTML = `<p class="big">${found}</p>
    <div class="chips">${chip}</div>
    ${rows.map(([a, b]) => `<p class="row"><span>${a}</span><span>${b}</span></p>`).join("")}
    ${sample.credit ? `<p class="credit">사진 출처: ${sample.credit}</p>` : ""}`;
}

function info() {
  const m = data[model].model, rows = [...META[model].info, ["크기", `${m.mb} MB · ONNX`], ["실행", "이 브라우저 (WebAssembly)"]];
  $("#info").innerHTML = rows.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");
}

// ---------- samples ----------
function samples() {
  const ul = $("#samples");
  ul.innerHTML = "";
  data[model].samples.forEach((s, i) => {
    const li = document.createElement("li"), b = document.createElement("button");
    b.type = "button"; b.dataset.id = s.id; b.setAttribute("aria-pressed", "false");
    b.setAttribute("aria-label", `샘플 ${i + 1}: ${KO[s.truth]}`);
    if (s.image) { const im = document.createElement("img"); im.src = new URL(s.image, DATA).href; im.alt = ""; im.loading = "lazy"; b.append(im); }
    else { const c = document.createElement("canvas"); b.append(c); requestAnimationFrame(() => plotWave(c, s.rf, { axes: false })); }
    const cap = document.createElement("span"); cap.className = "cap"; cap.textContent = `${i + 1} · ${s.source === "real" ? "실사진" : KO[s.truth]}`;
    b.append(cap); b.onclick = () => pick(s); li.append(b); ul.append(li);
  });
  if (model !== "ultrasonic") {  // own photo: stays in this browser
    const li = document.createElement("li"), b = document.createElement("button");
    b.type = "button"; b.dataset.id = "upload"; b.className = "upload"; b.setAttribute("aria-pressed", "false");
    b.innerHTML = `<span class="plus" aria-hidden="true">+</span><span class="cap">${model === "thermal" ? "내 열화상 올리기" : "내 사진 올리기"}</span>`;
    b.onclick = () => $("#file").click(); li.append(b); ul.append(li);
  }
}

// Uploaded photos are shrunk to 1280 px on the long side (mask drawing cost) and never leave the page.
async function upload(file) {
  if (!file) return;
  const bmp = await createImageBitmap(file), k = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
  const c = new OffscreenCanvas(Math.round(bmp.width * k), Math.round(bmp.height * k));
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  const url = URL.createObjectURL(await c.convertToBlob({ type: "image/jpeg", quality: 0.92 }));
  pick({ id: "upload", image: url, truth: null });
}

let token = 0;
async function pick(s) {
  const my = ++token;
  sample = s; result = null;
  for (const b of $("#samples").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.id === s.id));
  verdict(); draw();
  try {
    const r = model === "ultrasonic" ? await runUt(s) : await runYolo(model, s);
    if (my !== token) return;
    result = r; busy(""); verdict(); await draw();
  } catch (e) {
    if (my !== token) return;
    console.error(e);
    busy("모델을 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.", true);
  }
}

function choose(kind) {
  if (!data[kind]) kind = "corrosion";
  model = kind;
  if (location.hash !== "#" + kind) history.replaceState(null, "", "#" + kind);
  for (const b of $("#models").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.model === kind));
  [$("#in-title").textContent, $("#out-title").textContent] = META[kind].title;
  $("#truth-wrap").hidden = kind === "ultrasonic";
  info(); samples(); pick(data[kind].samples[0]);
}

// ---------- boot ----------
$("#models").addEventListener("click", (e) => { const b = e.target.closest("button[data-model]"); if (b && b.dataset.model !== model) choose(b.dataset.model); });
$("#truth").onchange = () => draw();
$("#file").onchange = (e) => { upload(e.target.files[0]).catch((err) => { console.error(err); busy("사진을 읽지 못했습니다. JPG 또는 PNG 파일을 올려 주세요.", true); }); e.target.value = ""; };
$("#narrow-go").onclick = () => $("#narrow").classList.add("dismissed");
addEventListener("hashchange", () => { const k = location.hash.slice(1); if (k !== model && data[k]) choose(k); });
let rz;
addEventListener("resize", () => { cancelAnimationFrame(rz); rz = requestAnimationFrame(() => sample && draw()); });

data = await (await fetch(new URL("samples.json", DATA))).json();
choose(location.hash.slice(1));
window.__try = { get model() { return model; }, get sample() { return sample?.id; }, get result() { return result && { ...judge(model, sample, result), ms: result.ms, logit: result.logit, dets: result.dets?.map((d) => ({ cls: d.cls, score: d.score, box: d.box, area: d.mask?.reduce((a, v) => a + v, 0) })) }; },
  pick: (id) => pick(data[model].samples.find((s) => s.id === id)), choose, data: () => data, upload };
