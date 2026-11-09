"use strict";
const O = window.MAEK_OPERATIONS,
  pipes = O.pipes,
  $ = (id) => document.getElementById(id),
  query = new URLSearchParams(location.search);
const escapeHTML = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const normalizeTab = (value) =>
  ["pipes", "areas", "records"].includes(value) ? "pipes" : "home";
let tab = normalizeTab(query.get("tab"));
let step =
  query.has("step") && /^\d+$/.test(query.get("step"))
    ? Math.min(pipes.length, Number(query.get("step")))
    : 125;
let visitPage = 0,
  problemPage = 0,
  viewerMode = null,
  mediaReturnFocus = null;
const pageSize = 5;
let selected =
    pipes.find((p) => p.id === query.get("pipe")) ||
    pipes.find((p, i) => i < step && p.result === "candidate") ||
    pipes[Math.min(step, pipes.length - 1)],
  timer = null,
  search = "",
  filter = "all",
  page = 0;
const titles = {
  home: ["현장 점검", "배관 위치 → 드론 관측 → 현장 비파괴검사"],
  pipes: ["배관 조회", "배관 검색 · 최신 검사 결과 · 검사 기록"],
};
const roles = {
  primary_inspection: "주 검사 대상",
  process_context: "공정 참고",
  training_only: "훈련 전용",
  standalone_utility_demo: "유틸리티 시연",
};
const index = (p) => pipes.indexOf(p),
  current = () => (step < pipes.length ? pipes[step] : null),
  visited = () =>
    pipes.filter((p) => index(p) < step && p.result === "candidate");
const done = (p) =>
  index(p) < step && p.analysed === p.planned && p.planned > 0;
const state = (p) =>
  index(p) === step
    ? "현재 위치 · 기록 기준"
    : done(p)
      ? "방문 완료 · 기록 기준"
      : "방문 예정 · 기록 기준";
const statusClass = (p) =>
  index(p) === step ? "current" : done(p) ? "done" : "";
const serviceArea = (p) =>
  (p.id.startsWith("BF2") ? "2고로" : "1고로") +
  " / " +
  (/BFG/.test(p.service) || p.service.includes("가스")
    ? "가스 계통"
    : p.service.includes("냉각")
      ? "냉각수 계통"
      : p.service.includes("슬러리")
        ? "슬러리 계통"
        : p.service);
const center = (p) =>
  p.points.reduce(
    (a, v) => a.map((n, i) => n + v[i] / p.points.length),
    [0, 0, 0],
  );
function url(next, pipe = selected.id) {
  return "?" + new URLSearchParams({ tab: next, step: String(step), pipe });
}
function sync() {
  history.replaceState(null, "", url(tab));
  document.querySelectorAll(".side-nav [data-tab]").forEach((a) => {
    const active = a.dataset.tab === tab;
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
    a.href = url(a.dataset.tab);
  });
}
function navigate(next, pipe = selected.id) {
  tab = normalizeTab(next);
  selected = pipes.find((p) => p.id === pipe) || selected;
  visitPage = 0;
  history.pushState(null, "", url(tab));
  render();
  $("page-title").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "instant" });
}
const footprints = O.buildings || [],
  allPoints = [
    ...pipes.flatMap((p) => p.points),
    ...footprints.flatMap((b) => [
      [b.center[0] - b.dimensions[0] / 2, b.center[1] - b.dimensions[1] / 2, 0],
      [b.center[0] + b.dimensions[0] / 2, b.center[1] + b.dimensions[1] / 2, 0],
    ]),
  ],
  xs = allPoints.map((p) => p[0]),
  ys = allPoints.map((p) => p[1]);
const bounds = {
  minX: Math.min(...xs) - 12,
  maxX: Math.max(...xs) + 12,
  minY: Math.min(...ys) - 12,
  maxY: Math.max(...ys) + 12,
};
const scale = Math.min(
  920 / (bounds.maxX - bounds.minX),
  450 / (bounds.maxY - bounds.minY),
);
const project = (p) => [
  (1000 - (bounds.maxX - bounds.minX) * scale) / 2 +
    (p[0] - bounds.minX) * scale,
  (560 - (bounds.maxY - bounds.minY) * scale) / 2 +
    (bounds.maxY - p[1]) * scale,
];
const coord = (n) => Number(n.toFixed(1));
function path(p) {
  return p.points.map((v) => project(v).map(coord).join(",")).join(" ");
}
function problemPipes() {
  return pipes.filter(
    (p) =>
      p.result === "candidate" ||
      window.MAEK_EVIDENCE.byPipe[p.id]?.thermal?.assessment_status ===
        "anomaly_observed",
  );
}
function problemReason(p) {
  const reasons = [];
  if (p.result === "candidate") reasons.push("부식 의심");
  if (
    window.MAEK_EVIDENCE.byPipe[p.id]?.thermal?.assessment_status ===
    "anomaly_observed"
  )
    reasons.push("열 이상 관측");
  return reasons.join(" · ") || "이상 여부 미확인";
}
function uiIcon(name) {
  const shapes = {
    left: '<path d="m15 6-6 6 6 6"/>',
    right: '<path d="m9 6 6 6-6 6"/>',
    expand:
      '<path d="M8 3H3v5m0-5 6 6M16 3h5v5m0-5-6 6M3 16v5h5m-5 0 6-6m7 6h5v-5m0 5-6-6"/>',
    fit: '<path d="M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5M9 9h6v6H9z"/>',
    locate:
      '<circle cx="12" cy="12" r="6"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
  };
  return `<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${shapes[name] || ""}</svg>`;
}
const heightCeiling = Math.max(
  10,
  Math.ceil(
    Math.max(
      ...pipes.flatMap((p) =>
        p.points.map((v) => v[2]).filter(Number.isFinite),
      ),
    ) / 10,
  ) * 10,
);
function heightSummary() {
  const values = selected.points.map((p) => p[2]).filter(Number.isFinite);
  if (!values.length)
    return '<section class="height-summary" aria-label="배관 높이"><strong>높이 미확인</strong></section>';
  const low = Math.min(...values),
    high = Math.max(...values),
    fmt = (v) => Number(v.toFixed(1)).toString(),
    range = low === high ? fmt(low) : fmt(low) + "–" + fmt(high),
    top = 54 - (high / heightCeiling) * 44,
    bottom = 54 - (low / heightCeiling) * 44;
  return `<section class="height-summary" aria-label="모델 지면 기준 배관 경로 높이 ${range}미터, 정확한 검사 지점의 높이 미확인" title="모델 지면 0m 기준 배관 경로(중심선)의 높이입니다. 외곽 치수나 실제 발판 높이가 아닙니다."><div class="height-copy"><span>배관 높이 · 모델 기준</span><strong>${range} m</strong><span class="point-height-missing">지점 높이 미확인</span></div><svg class="height-gauge" viewBox="0 0 54 64" aria-hidden="true"><text x="0" y="12">${heightCeiling}m</text><text x="5" y="60">0m</text><path class="height-axis" d="M38 10v44M30 10h16M33 32h10M28 54h20"/><rect class="height-band" x="32" y="${top.toFixed(2)}" width="12" height="${Math.max(3, bottom - top).toFixed(2)}" rx="2" data-min-height="${low}" data-max-height="${high}"/></svg></section>`;
}
function problemStrip() {
  const list = problemPipes(),
    size = 4;
  problemPage = Math.max(
    0,
    Math.min(problemPage, Math.ceil(list.length / size) - 1),
  );
  return `<section class="problem-strip" aria-label="점검 필요 배관 목록"><button type="button" id="problem-prev" aria-label="이전 의심 배관" title="이전 의심 배관" ${problemPage === 0 ? "disabled" : ""}>${uiIcon("left")}</button><div class="problem-cards">${list
    .slice(problemPage * size, (problemPage + 1) * size)
    .map(
      (p, i) =>
        `<button type="button" class="problem-card" data-problem="${escapeHTML(p.id)}" aria-pressed="${selected === p}"><span class="problem-number">${problemPage * size + i + 1}</span><span><strong>${escapeHTML(p.id)}</strong><span class="problem-cause">${escapeHTML(problemReason(p))}</span></span></button>`,
    )
    .join(
      "",
    )}${!list.length ? "<p>저장 자료에 의심 결과가 없습니다. 미연결 자료는 별도 점검이 필요합니다.</p>" : ""}</div><button type="button" id="problem-next" aria-label="다음 의심 배관" title="다음 의심 배관" ${(problemPage + 1) * size >= list.length ? "disabled" : ""}>${uiIcon("right")}</button></section>`;
}
const mapExtent = {
  x: (1000 - (bounds.maxX - bounds.minX) * scale) / 2,
  y: (560 - (bounds.maxY - bounds.minY) * scale) / 2,
  w: (bounds.maxX - bounds.minX) * scale,
  h: (bounds.maxY - bounds.minY) * scale,
};
let mapCamera = {
    x: mapExtent.x + mapExtent.w / 2,
    y: mapExtent.y + mapExtent.h / 2,
    zoom: 1,
  },
  mapDragged = false,
  focusedPipe = null;
function cameraBox(svg = null) {
  const rect = svg?.getBoundingClientRect(),
    aspect =
      rect?.width && rect?.height
        ? rect.width / rect.height
        : mapExtent.w / mapExtent.h,
    h = Math.max(mapExtent.h, mapExtent.w / aspect) / mapCamera.zoom,
    w = h * aspect;
  mapCamera.x = Math.max(
    mapExtent.x,
    Math.min(mapExtent.x + mapExtent.w, mapCamera.x),
  );
  mapCamera.y = Math.max(
    mapExtent.y,
    Math.min(mapExtent.y + mapExtent.h, mapCamera.y),
  );
  return [mapCamera.x - w / 2, mapCamera.y - h / 2, w, h].map(coord).join(" ");
}
function updateMaps() {
  document
    .querySelectorAll("[data-map] > svg")
    .forEach((svg) => svg.setAttribute("viewBox", cameraBox(svg)));
  document
    .querySelectorAll("[data-map-zoom-label]")
    .forEach((el) => (el.textContent = Math.round(mapCamera.zoom * 100) + "%"));
  document
    .querySelectorAll('[data-map-action="out"]')
    .forEach((b) => (b.disabled = mapCamera.zoom <= 1));
  document
    .querySelectorAll('[data-map-action="in"]')
    .forEach((b) => (b.disabled = mapCamera.zoom >= 6));
}
function mapPoint(svg, x, y) {
  return new DOMPoint(x, y).matrixTransform(svg.getScreenCTM().inverse());
}
function zoomMap(value, svg = null, client = null) {
  const before = svg && client ? mapPoint(svg, client.x, client.y) : null;
  mapCamera.zoom = Math.max(1, Math.min(6, value));
  updateMaps();
  if (before) {
    const after = mapPoint(svg, client.x, client.y);
    mapCamera.x += before.x - after.x;
    mapCamera.y += before.y - after.y;
    updateMaps();
  }
}
function mapControls() {
  return `<div class="map-controls" aria-label="지도 조작"><button type="button" data-map-action="out" aria-label="지도 축소">−</button><span data-map-zoom-label aria-live="polite">${Math.round(mapCamera.zoom * 100)}%</span><button type="button" data-map-action="in" aria-label="지도 확대">+</button><button type="button" data-map-action="fit" aria-label="전체 구역 보기" title="전체 구역 보기">${uiIcon("fit")}</button><button type="button" data-map-action="selected" aria-label="선택 배관으로 이동" title="선택 배관으로 이동">${uiIcon("locate")}</button></div>`;
}
function routeMarkup() {
  let out = "";
  for (const prefix of ["BF1", "BF2"]) {
    const group = pipes.filter((p) => p.id.startsWith(prefix)),
      count = group.filter((p) => index(p) < step).length;
    if (!count) continue;
    const points = group.flatMap((p) => p.points).map(project),
      xx = points.map((p) => p[0]),
      yy = points.map((p) => p[1]),
      x = Math.min(...xx) - 8,
      y = Math.min(...yy) - 8,
      w = Math.max(...xx) - x + 8,
      h = Math.max(...yy) - y + 8;
    out += `<g class="visited-zone"><rect x="${coord(x)}" y="${coord(y)}" width="${coord(w)}" height="${coord(h)}" rx="10"/><text x="${coord(x + 8)}" y="${coord(y + 17)}">${prefix === "BF1" ? "1고로" : "2고로"} 방문 ${count}/${group.length}</text></g>`;
  }
  for (const p of pipes.slice(0, Math.min(step + 1, pipes.length))) {
    const points =
      index(p) === step
        ? p.route.slice(0, Math.floor(p.route.length / 2) + 1)
        : p.route;
    if (points.length < 2) continue;
    out += `<polyline class="drone-trail" data-route-pipe="${escapeHTML(p.id)}" points="${points.map((w) => project([w.position[0], w.position[2], w.position[1]]).map(coord).join(","))}"/>`;
  }
  return out;
}
function mapMarkup(compact = false, expandable = false) {
  const spots = tab === "home" ? problemPipes() : visited(),
    viewBox = cameraBox();
  let svg = `<svg viewBox="${viewBox}" role="group" aria-label="MAEK 가상 제철소 모델 평면도. 배관 위치는 모델 좌표이며 실제 제철소 지도와 다릅니다."><title>모델 배관 지도</title>${routeMarkup()}`;
  for (const b of footprints) {
    const xy = project(b.center),
      w = b.dimensions[0] * scale,
      h = b.dimensions[1] * scale;
    svg += `<g class="map-building" data-building="${escapeHTML(b.id)}"><rect x="${coord(xy[0] - w / 2)}" y="${coord(xy[1] - h / 2)}" width="${coord(w)}" height="${coord(h)}" rx="3"/><text class="building-label" x="${coord(xy[0])}" y="${coord(xy[1] + 4)}">${escapeHTML(b.label)}</text></g>`;
  }
  for (const d of O.devices) {
    const xy = project(d.center),
      w = Math.max(7, d.dimensions[0] * scale),
      h = Math.max(7, d.dimensions[1] * scale),
      round = [
        "furnace",
        "stove",
        "dust_catcher",
        "scrubber",
        "clarifier",
        "makeup_tank",
      ].includes(d.kind);
    svg += round
      ? `<ellipse class="map-device ${d.kind}" cx="${coord(xy[0])}" cy="${coord(xy[1])}" rx="${coord(w / 2)}" ry="${coord(h / 2)}"/>`
      : `<rect class="map-device" x="${coord(xy[0] - w / 2)}" y="${coord(xy[1] - h / 2)}" width="${coord(w)}" height="${coord(h)}" rx="2"/>`;
    if (d.kind === "furnace")
      svg += `<text class="map-label" x="${coord(xy[0])}" y="${coord(xy[1] + h / 2 + 18)}" text-anchor="middle">${d.id.startsWith("BF1") ? "1고로" : "2고로"}</text>`;
  }

  for (const p of pipes) {
    const cls = [
      done(p) ? "done" : "",
      (tab === "home" || done(p)) && p.result === "candidate" ? "visit" : "",
      p === current() ? "current" : "",
      p.role === "primary_inspection" ? "main-pipe" : "context-pipe",
    ].join(" ");
    svg += `<polyline class="pipe-line ${cls}" points="${path(p)}"/><polyline class="pipe-hit" data-map-pipe="${escapeHTML(p.id)}" points="${path(p)}"><title>${escapeHTML(p.id + " / " + p.service + " / " + state(p))}</title></polyline>`;
  }
  svg += `<polyline class="selected-underlay" points="${path(selected)}"/><polyline class="pipe-line selected" points="${path(selected)}"/>`;
  const placed = [];
  spots.forEach((p, i) => {
    const xy = project(center(p));
    let px = xy[0],
      py = xy[1];
    for (
      let tries = 0;
      tries < 8 && placed.some((q) => Math.hypot(q[0] - px, q[1] - py) < 29);
      tries++
    ) {
      px = xy[0] + Math.cos((tries + i) * 1.8) * (22 + tries * 5);
      py = xy[1] + Math.sin((tries + i) * 1.8) * (22 + tries * 5);
    }
    placed.push([px, py]);
    svg += `<g class="map-spot${p === selected ? " is-selected" : ""}" data-map-pipe="${escapeHTML(p.id)}" role="button" tabindex="0" aria-label="의심 배관 ${i + 1}: ${escapeHTML(p.id)}"><circle cx="${coord(px)}" cy="${coord(py)}" r="28" fill="transparent"/><path d="M${coord(xy[0])} ${coord(xy[1])}L${coord(px)} ${coord(py)}" stroke="#a3631a"/><circle class="spot-disc" cx="${coord(px)}" cy="${coord(py)}" r="12"/><text class="spot-number" x="${coord(px)}" y="${coord(py)}">${i + 1}</text></g>`;
  });
  const now = current();
  if (now) {
    const point = now.route[Math.floor(now.route.length / 2)].position,
      xy = project([point[0], point[2], point[1]]);
    svg += `<g aria-label="현재 위치, 저장 경로 기준 ${escapeHTML(now.id)}"><circle class="drone-mark" cx="${coord(xy[0])}" cy="${coord(xy[1])}" r="13"/><path d="m${coord(xy[0] - 6)} ${coord(xy[1])}h12m-6-6v12" stroke="white" stroke-width="2"/><text class="drone-caption" x="${coord(xy[0] + 18)}" y="${coord(xy[1] - 16)}">현재 위치</text></g>`;
  }
  svg += "</svg>";
  return `<div class="site-map interactive-map${compact ? " compact-map" : ""}" data-map tabindex="0" aria-label="방문 구역 지도. 확대 후 끌어서 이동할 수 있습니다.">${svg}${expandable ? `<button type="button" id="expand-map" class="map-expand icon-button" aria-label="지도 크게 보기" title="지도 크게 보기">${uiIcon("expand")}</button>` : ""}${mapControls()}<span class="map-source">저장 경로 재구성</span></div>`;
}
let ndtNotice = "";
const ndtStorageKey = "maek.ndt.linked.v1";
function readNdt() {
  try {
    const v = JSON.parse(localStorage.getItem(ndtStorageKey) || "[]");
    return Array.isArray(v)
      ? v.filter(
          (r) =>
            r &&
            [
              "result_id",
              "pipe_id",
              "inspection_point",
              "method",
              "performed_at",
              "inspector",
              "result_summary",
              "procedure_ref",
              "coverage_ref",
              "report_ref",
            ].every((k) => typeof r[k] === "string" && r[k].trim()) &&
            Number.isFinite(Date.parse(r.performed_at)),
        )
      : [];
  } catch {
    return [];
  }
}
function droneImage(kind, large = false) {
  const e = window.MAEK_EVIDENCE.byPipe[selected.id]?.[kind];
  if (!e)
    return `<div class="sensor-empty"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16v16H4zM8 15l3-3 3 2 3-5"/></svg><strong>${kind === "thermal" ? "열화상 사진 미연결" : "RGB 사진 미연결"}</strong></div>`;
  const boxes = (e.regions || [])
    .map((r) => {
      const [x, y, x2, y2] = r.bbox;
      return `<span class="rgb-region" style="left:${(x / e.width) * 100}%;top:${(y / e.height) * 100}%;width:${((x2 - x) / e.width) * 100}%;height:${((y2 - y) / e.height) * 100}%"></span>`;
    })
    .join("");
  return `<${large ? "div" : "button"} class="sensor-image" ${large ? "" : `type="button" data-open-image="${kind}" aria-label="${escapeHTML(selected.id)} ${kind === "rgb" ? "RGB" : "열화상"} 사진 크게 보기"`}><img src="${escapeHTML(e.src)}" width="${e.width}" height="${e.height}" alt="${escapeHTML(selected.id)} ${kind === "rgb" ? "저장 RGB 사진" : "열화상 사진"}">${boxes}${large ? "" : `<span class="image-expand">${uiIcon("expand")}</span>`}</${large ? "div" : "button"}>`;
}
function ndtPanel() {
  const all = pipeReports(),
    r = all[0];
  return `<section class="ndt-panel" aria-label="같은 배관의 비파괴검사"><div class="ndt-heading"><h2>현장 비파괴검사</h2><button type="button" id="import-ndt">결과 등록</button></div><div data-ut-pipe="${escapeHTML(selected.id)}"></div>${r ? `<div class="ndt-result-row"><strong>${escapeHTML(r.method)}</strong><span class="state visit">기기 저장 · 검토 필요</span></div><p class="ndt-measurement">${escapeHTML(r.result_summary.length > 100 ? r.result_summary.slice(0, 100) + "…" : r.result_summary)}</p><p class="ndt-meta">부위 ${escapeHTML(r.inspection_point)} · ${escapeHTML(r.inspector)} · ${escapeHTML(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short" }).format(new Date(r.performed_at)))}</p><details class="ndt-details"><summary>전체 결과·검사 범위</summary><dl><dt>결과</dt><dd>${escapeHTML(r.result_summary)}</dd><dt>절차</dt><dd>${escapeHTML(r.procedure_ref)}</dd><dt>검사 범위</dt><dd>${escapeHTML(r.coverage_ref)}</dd><dt>보고서</dt><dd>${escapeHTML(r.report_ref)}</dd></dl><p>배관 ID로 연결한 보고서이며 영상의 정확한 부위 정합은 별도 확인합니다.</p></details>` : `<div class="ndt-pending"><strong>검사 결과 미등록</strong></div>`}${ndtNotice ? '<p class="ndt-feedback" role="status">' + escapeHTML(ndtNotice) + "</p>" : ""}</section>`;
}
function home() {
  const rgb = window.MAEK_EVIDENCE.byPipe[selected.id]?.rgb,
    thermal = window.MAEK_EVIDENCE.byPipe[selected.id]?.thermal;
  return `${problemStrip()}<div class="unified-layout"><section class="map-panel" aria-label="배관 지도와 드론 위치">${mapMarkup(false, true)}<div class="drone-location"><p class="visited-summary">방문 구역 <strong>${[...new Set(pipes.slice(0, step).map((p) => (p.id.startsWith("BF1") ? "1고로" : p.id.startsWith("BF2") ? "2고로" : "기타 구역")))].join(" · ") || "방문 전"}</strong></p></div><div class="map-legend"><span class="legend-item"><i class="legend-line route"></i>방문 구역</span><span class="legend-item"><i class="legend-line current"></i>현재 위치</span><span class="legend-item"><i class="legend-line visit"></i>점검 필요</span></div></section><section class="inspection-flow" aria-label="선택 배관의 연속 검사"><div class="pipe-context problem-context" data-has-issue="${problemPipes().includes(selected)}"><div class="pipe-main"><h2>${escapeHTML(selected.id)}<span class="selected-issue">${escapeHTML(problemReason(selected))}</span></h2><p>${escapeHTML(selected.service)}</p></div>${heightSummary()}</div><div class="drone-evidence"><section class="sensor-panel" data-connected="${!!rgb}"><div class="sensor-heading"><h3>RGB · 부식</h3><span>저장 사진</span></div>${droneImage("rgb")}<div class="sensor-analysis"><strong>${rgb?.regions.length ? "부식 의심 " + rgb.regions.length + "건" : rgb ? "부식 의심 미검출" : "분석 결과 미연결"}</strong><span>${rgb ? "색상 규칙 분석" : ""}</span></div></section><section class="sensor-panel" data-connected="${!!thermal}"><div class="sensor-heading"><h3>열화상</h3><span>${thermal ? "연결 사진" : ""}</span></div>${droneImage("thermal")}<div class="sensor-analysis"><strong>${thermal ? escapeHTML(thermal.analysis_summary || "판독 결과 확인 필요") : "분석 결과 미연결"}</strong><span>${thermal ? escapeHTML(thermal.quality_status || "품질 확인 필요") : ""}</span></div></section></div>${ndtPanel()}</section></div>`;
}

function pipeReports() {
  return readNdt()
    .filter((r) => r.pipe_id === selected.id)
    .sort(
      (a, b) =>
        Date.parse(b.performed_at) - Date.parse(a.performed_at) ||
        a.result_id.localeCompare(b.result_id),
    );
}
const reportDate = (value) =>
  new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
function rows(filtered) {
  const slice = filtered.slice(page * pageSize, (page + 1) * pageSize);
  return `<ul class="row-list">${slice.map((p) => `<li class="pipe-row" data-selected="${p === selected}"><div><strong>${escapeHTML(p.id)}</strong><p>${escapeHTML(p.service)}</p><div class="row-status state ${p.result === "candidate" ? "visit" : statusClass(p)}">${p.result === "candidate" ? "부식 의심 " + p.findings + "건" : escapeHTML(state(p))}</div></div><button type="button" data-pipe="${escapeHTML(p.id)}" aria-current="${p === selected ? "true" : "false"}">상세 보기</button></li>`).join("")}</ul>${!filtered.length ? '<div class="empty"><h2>조건에 맞는 배관이 없습니다.</h2><p>배관 ID를 확인하거나 필터를 전체로 바꿔 주세요.</p></div>' : ""}<div class="rows-footer"><span class="muted">${filtered.length}개 중 ${filtered.length ? page * pageSize + 1 : 0}–${Math.min((page + 1) * pageSize, filtered.length)}</span><div class="page-buttons"><button id="previous-page" ${page === 0 ? "disabled" : ""}>이전</button><button id="next-page" ${(page + 1) * pageSize >= filtered.length ? "disabled" : ""}>다음</button></div></div>`;
}
function filteredPipes() {
  return pipes.filter(
    (p) =>
      (p.id + " " + p.service).toLowerCase().includes(search.toLowerCase()) &&
      (filter === "all" ||
        (filter === "primary" && p.role === "primary_inspection") ||
        (filter === "done" && done(p)) ||
        (filter === "waiting" && index(p) > step) ||
        (filter === "candidate" && p.result === "candidate")),
  );
}
function pipeDetail() {
  const reports = pipeReports(),
    latest = reports[0];
  return `<section class="summary-box pipe-detail" aria-label="${escapeHTML(selected.id)} 배관 상세"><header class="lookup-heading"><div><h2>${escapeHTML(selected.id)}</h2><p class="selected-service">${escapeHTML(selected.service)}</p></div><a class="icon-button" data-route="home" href="${url("home")}" aria-label="${escapeHTML(selected.id)} 지도에서 보기" title="지도에서 보기">${uiIcon("locate")}</a></header><dl class="lookup-overview"><dt>RGB · 부식</dt><dd>${selected.result === "candidate" ? "부식 의심 " + selected.findings + "건" : "부식 의심 미검출"}<small>${selected.analysed}/${selected.planned}장 분석 · 색상 규칙</small></dd><dt>열화상</dt><dd>결과 미연결</dd><dt>수동 등록 보고서</dt><dd>${latest ? "등록 " + reports.length + "건 · 검토 필요" : "결과 미등록"}</dd></dl><div data-ut-pipe="${escapeHTML(selected.id)}"></div>${latest ? `<div class="latest-inspection"><h3>최근 비파괴검사</h3><strong>${escapeHTML(latest.method)}</strong><time datetime="${escapeHTML(latest.performed_at)}">${escapeHTML(reportDate(latest.performed_at))}</time><p>${escapeHTML(latest.result_summary.length > 80 ? latest.result_summary.slice(0, 80) + "…" : latest.result_summary)}</p></div>` : ""}<details class="lookup-history"><summary>비파괴검사 기록 ${reports.length}건</summary>${reports.length ? `<ol class="inspection-history">${reports.map((r) => `<li data-result-id="${escapeHTML(r.result_id)}"><time datetime="${escapeHTML(r.performed_at)}">${escapeHTML(reportDate(r.performed_at))}</time><h3>${escapeHTML(r.method)}</h3><p>${escapeHTML(r.result_summary)}</p><dl><dt>부위</dt><dd>${escapeHTML(r.inspection_point)}</dd><dt>검사자</dt><dd>${escapeHTML(r.inspector)}</dd><dt>절차</dt><dd>${escapeHTML(r.procedure_ref)}</dd><dt>검사 범위</dt><dd>${escapeHTML(r.coverage_ref)}</dd><dt>보고서</dt><dd>${escapeHTML(r.report_ref)}</dd></dl><small>기기 저장 · 검토 필요</small></li>`).join("")}</ol>` : "<p>등록된 비파괴검사 결과가 없습니다.</p>"}</details><details class="evidence-ids"><summary>촬영 근거 ID ${selected.evidenceIds.length}개</summary><ul>${selected.evidenceIds.map((id) => `<li>${escapeHTML(id)}</li>`).join("")}</ul></details><p class="lookup-note">저장 시연 자료 · 미검출·미등록은 정상 판정이 아닙니다.</p></section>`;
}
function listing() {
  return `<div class="filters"><label class="sr-only" for="pipe-search">배관 검색</label><input type="search" id="pipe-search" placeholder="배관 ID 또는 계통" value="${escapeHTML(search)}"><label class="sr-only" for="status-filter">표시 범위</label><select id="status-filter"><option value="all">전체 배관</option><option value="candidate">점검 필요</option><option value="done">방문 완료</option><option value="waiting">방문 예정</option><option value="primary">주 검사 대상</option></select></div><div class="list-layout lookup-layout"><section class="list-panel" aria-label="배관 검색 결과"><div id="list-results">${rows(filteredPipes())}</div></section><aside aria-label="선택 배관 검사 정보">${pipeDetail()}</aside></div>`;
}
function updateList() {
  const filtered = filteredPipes();
  if (page * pageSize >= filtered.length) page = 0;
  $("list-results").innerHTML = rows(filtered);
  bindRows();
}
function bindRows() {
  document.querySelectorAll("[data-pipe]").forEach(
    (b) =>
      (b.onclick = () => {
        selected = pipes.find((p) => p.id === b.dataset.pipe);
        render();
        document
          .querySelector(`[data-pipe="${selected.id}"]`)
          ?.focus({ preventScroll: true });
      }),
  );
  if ($("previous-page"))
    $("previous-page").onclick = () => {
      page--;
      updateList();
    };
  if ($("next-page"))
    $("next-page").onclick = () => {
      page++;
      updateList();
    };
}
function bind() {
  document.querySelectorAll("[data-problem]").forEach(
    (b) =>
      (b.onclick = () => {
        selected = pipes.find((p) => p.id === b.dataset.problem);
        ndtNotice = "";
        render();
      }),
  );
  if ($("problem-prev"))
    $("problem-prev").onclick = () => {
      problemPage--;
      render();
    };
  if ($("problem-next"))
    $("problem-next").onclick = () => {
      problemPage++;
      render();
    };
  if ($("import-ndt"))
    $("import-ndt").onclick = () => {
      $("ndt-file").value = "";
      $("ndt-file").dataset.pipe = selected.id;
      $("ndt-file").click();
    };
  if ($("visit-prev"))
    $("visit-prev").onclick = () => {
      visitPage--;
      render();
    };
  if ($("visit-next"))
    $("visit-next").onclick = () => {
      visitPage++;
      render();
    };
  document.querySelectorAll("[data-route]").forEach(
    (a) =>
      (a.onclick = (e) => {
        e.preventDefault();
        navigate(a.dataset.route);
      }),
  );
  document.querySelectorAll("[data-map-pipe]").forEach((el) => {
    const pick = () => {
      if (mapDragged) return;
      selected = pipes.find((p) => p.id === el.dataset.mapPipe);
      const i = problemPipes().indexOf(selected);
      if (i >= 0) problemPage = Math.floor(i / 4);
      ndtNotice = "";
      render();
    };
    el.onclick = pick;
    if (el.getAttribute("role") === "button")
      el.onkeydown = (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          pick();
        }
      };
  });
  document.querySelectorAll("[data-visit]").forEach(
    (b) =>
      (b.onclick = () => {
        selected = pipes.find((p) => p.id === b.dataset.visit);
        render();
      }),
  );
  if ($("pipe-search"))
    $("pipe-search").oninput = (e) => {
      search = e.target.value;
      page = 0;
      updateList();
    };
  if ($("status-filter")) {
    $("status-filter").value = filter;
    $("status-filter").onchange = (e) => {
      filter = e.target.value;
      page = 0;
      updateList();
    };
  }
  if ($("visit-last")) $("visit-last").onclick = () => setStep(pipes.length);
  bindRows();
  bindMapInteractions();
  document
    .querySelectorAll("[data-open-image]")
    .forEach((b) => (b.onclick = () => openMedia(b.dataset.openImage, b)));
  if ($("expand-map"))
    $("expand-map").onclick = (e) => openMedia("map", e.currentTarget);
}
function render() {
  if (focusedPipe !== selected.id) {
    const [x, y] = project(center(selected));
    mapCamera = { x, y, zoom: 2.2 };
    focusedPipe = selected.id;
  }
  const text = titles[tab];
  $("page-title").textContent = text[0];
  $("page-description").textContent = text[1];
  $("progress").value = step;
  $("progress-label").textContent = step + " / " + pipes.length;
  $("replay-position").textContent = current()
    ? "드론 재생 위치 · " + current().id
    : "저장 기록의 마지막 단계";
  document.body.dataset.tab = tab;
  $("screen").innerHTML = tab === "home" ? home() : listing();
  sync();
  document.dispatchEvent(new CustomEvent("maek:render"));
  if (viewerMode) refreshMedia();
  bind();
  document.querySelectorAll("[data-map]").forEach((map) => {
    if (map.scrollWidth > map.clientWidth) {
      const x = map.classList.contains("compact-map")
        ? map.scrollWidth / 2
        : (project(center(selected))[0] / 1000) * map.scrollWidth;
      map.scrollLeft = Math.max(0, x - map.clientWidth / 2);
    }
  });
}
function bindMapInteractions() {
  document.querySelectorAll("[data-map]").forEach((map) => {
    const svg = map.querySelector("svg"),
      points = new Map();
    let start = null;
    map.style.touchAction = "none";
    map.onpointerdown = (e) => {
      if (e.target.closest("button")) return;
      points.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (points.size === 1) {
        start = { x: e.clientX, y: e.clientY };
        mapDragged = false;
      }
    };
    map.onpointermove = (e) => {
      if (!points.has(e.pointerId)) return;
      const old = [...points.values()],
        previous = points.get(e.pointerId);
      points.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 5)
        mapDragged = true;
      if (mapDragged && !map.hasPointerCapture(e.pointerId))
        map.setPointerCapture(e.pointerId);
      if (points.size === 2) {
        const now = [...points.values()],
          dist = (p) => Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
          mid = (p) => ({ x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2 });
        if (dist(old) > 0)
          zoomMap((mapCamera.zoom * dist(now)) / dist(old), svg, mid(old));
        const a = mapPoint(svg, mid(old).x, mid(old).y),
          b = mapPoint(svg, mid(now).x, mid(now).y);
        mapCamera.x += a.x - b.x;
        mapCamera.y += a.y - b.y;
        mapDragged = true;
      } else if (mapCamera.zoom > 1) {
        const a = mapPoint(svg, previous.x, previous.y),
          b = mapPoint(svg, e.clientX, e.clientY);
        mapCamera.x += a.x - b.x;
        mapCamera.y += a.y - b.y;
      }
      updateMaps();
    };
    const stop = (e) => {
      points.delete(e.pointerId);
      if (map.hasPointerCapture(e.pointerId))
        map.releasePointerCapture(e.pointerId);
      setTimeout(() => (mapDragged = false), 0);
    };
    map.onpointerup = stop;
    map.onpointercancel = stop;
    map.onwheel = (e) => {
      e.preventDefault();
      zoomMap(mapCamera.zoom * Math.exp(-e.deltaY * 0.002), svg, {
        x: e.clientX,
        y: e.clientY,
      });
    };
    map.onkeydown = (e) => {
      if (e.target !== map) return;
      if (
        [
          "+",
          "=",
          "-",
          "0",
          "ArrowLeft",
          "ArrowRight",
          "ArrowUp",
          "ArrowDown",
        ].includes(e.key)
      ) {
        e.preventDefault();
        if (e.key === "0") {
          mapCamera.zoom = 1;
          updateMaps();
        } else if (e.key === "+" || e.key === "=")
          zoomMap(mapCamera.zoom * 1.4);
        else if (e.key === "-") zoomMap(mapCamera.zoom / 1.4);
        else {
          const d = 35 / mapCamera.zoom;
          mapCamera.x +=
            e.key === "ArrowLeft" ? -d : e.key === "ArrowRight" ? d : 0;
          mapCamera.y +=
            e.key === "ArrowUp" ? -d : e.key === "ArrowDown" ? d : 0;
          updateMaps();
        }
      }
    };
  });
  document.querySelectorAll("[data-map-action]").forEach(
    (b) =>
      (b.onclick = (e) => {
        e.stopPropagation();
        if (b.dataset.mapAction === "in") zoomMap(mapCamera.zoom * 1.4);
        else if (b.dataset.mapAction === "out") zoomMap(mapCamera.zoom / 1.4);
        else if (b.dataset.mapAction === "selected") {
          const [x, y] = project(center(selected));
          mapCamera = { x, y, zoom: 2.2 };
          updateMaps();
        } else {
          mapCamera = {
            x: mapExtent.x + mapExtent.w / 2,
            y: mapExtent.y + mapExtent.h / 2,
            zoom: 1,
          };
          updateMaps();
        }
      }),
  );
  updateMaps();
}
function fitMedia() {
  if (!viewerMode || viewerMode === "map") return;
  const e = window.MAEK_EVIDENCE.byPipe[selected.id]?.[viewerMode],
    frame = $("media-content").querySelector(".sensor-image");
  if (!e || !frame) return;
  const size = Math.min(
    $("media-content").clientWidth / e.width,
    $("media-content").clientHeight / e.height,
  );
  frame.style.width = e.width * size + "px";
  frame.style.height = e.height * size + "px";
}
function refreshMedia() {
  $("media-title").textContent =
    viewerMode === "map"
      ? "방문 구역 지도"
      : selected.id +
        " · " +
        (viewerMode === "rgb" ? "RGB 원본 사진" : "열화상 원본 사진");
  if (viewerMode === "map") $("media-title").textContent = "방문 구역 지도";
  $("media-content").innerHTML =
    viewerMode === "map" ? mapMarkup() : droneImage(viewerMode, true);
  $("media-viewer").dataset.kind = viewerMode;
  if ($("media-viewer").open) fitMedia();
}
function openMedia(kind, trigger) {
  viewerMode = kind;
  mediaReturnFocus = trigger;
  refreshMedia();
  $("media-viewer").showModal();
  fitMedia();
  bind();
  $("close-media").focus();
}
$("close-media").onclick = () => $("media-viewer").close();
$("media-viewer").addEventListener("close", () => {
  viewerMode = null;
  if (mediaReturnFocus?.isConnected) mediaReturnFocus.focus();
  mediaReturnFocus = null;
});
function pause() {
  if (timer) clearInterval(timer);
  timer = null;
  $("play").textContent = "재생";
  $("play").setAttribute("aria-label", "기록 재생 시작");
}
function setStep(value) {
  pause();
  step = Math.max(0, Math.min(pipes.length, Number(value)));
  render();
}
document.querySelectorAll(".side-nav [data-tab]").forEach(
  (a) =>
    (a.onclick = (e) => {
      e.preventDefault();
      navigate(a.dataset.tab);
    }),
);
$("progress").oninput = (e) => setStep(e.target.value);
$("last-record").onclick = () => setStep(pipes.length);
$("play").onclick = () => {
  if (timer) {
    pause();
    return;
  }
  if (step === pipes.length) step = 0;
  $("play").textContent = "일시 정지";
  $("play").setAttribute("aria-label", "기록 재생 일시 정지");
  timer = setInterval(() => {
    step++;
    render();
    if (step >= pipes.length) pause();
  }, 1200);
  render();
};
$("ndt-file").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const target = e.target.dataset.pipe;
  try {
    if (file.size > 1048576)
      throw new Error(
        "파일이 너무 큽니다. 1 MB 이하의 검사 결과를 선택하세요.",
      );
    const r = JSON.parse(await file.text());
    const fields = [
      "result_id",
      "pipe_id",
      "inspection_point",
      "method",
      "performed_at",
      "inspector",
      "result_summary",
      "procedure_ref",
      "coverage_ref",
      "report_ref",
    ];
    if (!r || fields.some((k) => typeof r[k] !== "string" || !r[k].trim()))
      throw new Error(
        "배관·검사 부위·방법·시각·검사자·결과·절차·범위·보고서가 필요합니다.",
      );
    if (r.pipe_id !== target)
      throw new Error("선택한 배관과 결과의 배관 번호가 다릅니다.");
    if (
      !/(Z|[+-]\d{2}:\d{2})$/.test(r.performed_at) ||
      !Number.isFinite(Date.parse(r.performed_at))
    )
      throw new Error("검사 시각과 시간대를 확인하세요.");
    const clean = Object.fromEntries(fields.map((k) => [k, r[k].trim()]));
    const rows = readNdt(),
      old = rows.find((v) => v.result_id === clean.result_id);
    if (old && JSON.stringify(old) !== JSON.stringify(clean))
      throw new Error(
        "같은 결과 번호에 다른 내용이 있습니다. 기존 기록을 유지합니다.",
      );
    if (!old) {
      rows.push(clean);
      localStorage.setItem(ndtStorageKey, JSON.stringify(rows));
    }
    selected = pipes.find((p) => p.id === target);
    ndtNotice = old
      ? "이미 연결된 결과입니다."
      : "이 기기에 저장했습니다. 담당자 검토가 필요합니다.";
    $("ndt-announcement").textContent = ndtNotice;
    render();
  } catch (err) {
    ndtNotice =
      err instanceof SyntaxError
        ? "검사 결과 파일을 읽을 수 없습니다. JSON 형식을 확인하세요."
        : err.message;
    $("ndt-announcement").textContent = ndtNotice;
    render();
  }
};
window.addEventListener("resize", () => {
  fitMedia();
  updateMaps();
});
window.addEventListener("pagehide", pause);
window.addEventListener("popstate", () => {
  pause();
  const q = new URLSearchParams(location.search);
  tab = normalizeTab(q.get("tab"));
  step =
    q.has("step") && /^\d+$/.test(q.get("step"))
      ? Math.min(pipes.length, Number(q.get("step")))
      : 125;
  selected = pipes.find((p) => p.id === q.get("pipe")) || selected;
  visitPage = 0;
  render();
});
render();
