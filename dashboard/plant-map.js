"use strict";
// Parametric equipment geometry uses model dimensions, not a background screenshot.
window.MAEK_PLANT_MAP = (() => {
  const solidCorners = (d) => {
    const [x, y, z] = d.center,
      [w, h, t] = d.dimensions;
    return [-1, 1].flatMap((a) =>
      [-1, 1].flatMap((b) =>
        [0, t].map((v) => [x + (a * w) / 2, y + (b * h) / 2, z + v]),
      ),
    );
  };
  function defs(id) {
    return `<defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#4b626d"/><stop offset=".25" stop-color="#a7b8be"/><stop offset=".5" stop-color="#d6e0e2"/><stop offset=".74" stop-color="#8299a4"/><stop offset="1" stop-color="#3e5561"/></linearGradient></defs>`;
  }
  function drawScene(buildings, devices, project, scale, esc, round, metal) {
    const polygon = (points, cls) =>
      `<polygon class="${cls}" points="${points.map((p) => p.map(round).join(",")).join(" ")}"/>`;
    function box(d, building) {
      const [x, y, z] = d.center,
        [w, h, height] = d.dimensions,
        corners = [
          [-w / 2, -h / 2],
          [w / 2, -h / 2],
          [w / 2, h / 2],
          [-w / 2, h / 2],
        ],
        ground = corners.map(([a, b]) => project([x + a, y + b, z])),
        roof = corners.map(([a, b]) => project([x + a, y + b, z + height]));
      let out = `<g class="${building ? "map-building solid-building" : "map-device solid-device"}" ${building ? `data-building="${esc(d.id)}"` : `data-device="${esc(d.id)}"`}>`;
      out +=
        polygon(ground, "equipment-pad") +
        polygon([ground[0], ground[1], roof[1], roof[0]], "solid-front") +
        polygon([ground[1], ground[2], roof[2], roof[1]], "solid-side") +
        polygon(roof, "solid-top");
      if (building) {
        for (let i = 1; i < 6; i++) {
          const a = i / 6,
            p1 = [
              roof[0][0] + (roof[1][0] - roof[0][0]) * a,
              roof[0][1] + (roof[1][1] - roof[0][1]) * a,
            ],
            p2 = [
              roof[3][0] + (roof[2][0] - roof[3][0]) * a,
              roof[3][1] + (roof[2][1] - roof[3][1]) * a,
            ];
          out += `<path class="roof-seam" d="M${p1.map(round).join(" ")}L${p2.map(round).join(" ")}"/>`;
        }
        const c = project([x, y, z + height]);
        out += `<rect class="equipment-tag" x="${round(c[0] - (d.label.length * 7 + 16) / 2)}" y="${round(c[1] - 10)}" width="${d.label.length * 7 + 16}" height="20" rx="3"/><text class="building-label" x="${round(c[0])}" y="${round(c[1] + 4)}">${esc(d.label)}</text>`;
      }
      return out + "</g>";
    }
    function cylinder(d) {
      const [x, y, z] = d.center,
        [w, h, height] = d.dimensions,
        a = project([x, y, z]),
        b = project([x, y, z + height]),
        rx = Math.max(4, (w * scale) / 2),
        ry = Math.max(2, h * scale * 0.34);
      let out = `<g class="map-device solid-device ${d.kind}" data-device="${esc(d.id)}"><ellipse class="equipment-pad" cx="${round(a[0])}" cy="${round(a[1] + 2)}" rx="${round(rx + 3)}" ry="${round(ry + 2)}"/><path class="cylinder-wall" fill="url(#${metal})" d="M${round(b[0] - rx)} ${round(b[1])}L${round(a[0] - rx)} ${round(a[1])}A${round(rx)} ${round(ry)} 0 0 0 ${round(a[0] + rx)} ${round(a[1])}L${round(b[0] + rx)} ${round(b[1])}Z"/><ellipse class="cylinder-cap" cx="${round(b[0])}" cy="${round(b[1])}" rx="${round(rx)}" ry="${round(ry)}"/>`;
      for (const ratio of [0.2, 0.78]) {
        const cy = a[1] + (b[1] - a[1]) * ratio;
        out += `<path class="cylinder-band" d="M${round(a[0] - rx)} ${round(cy)}A${round(rx)} ${round(ry)} 0 0 0 ${round(a[0] + rx)} ${round(cy)}"/>`;
      }
      if (["furnace", "stove", "dust_catcher", "scrubber"].includes(d.kind))
        out += `<path class="vessel-nozzle" d="M${round(b[0])} ${round(b[1] - ry)}v-5"/>`;
      if (d.kind === "furnace")
        out += `<text class="map-label" x="${round(a[0])}" y="${round(a[1] + ry + 16)}" text-anchor="middle">${d.id.startsWith("BF1") ? "1고로" : "2고로"}</text>`;
      return out + "</g>";
    }
    return [
      ...buildings.map((d) => ({ d, building: true })),
      ...devices.map((d) => ({ d, building: false })),
    ]
      .sort((a, b) => b.d.center[1] - a.d.center[1])
      .map(({ d, building }) =>
        !building &&
        [
          "furnace",
          "stove",
          "dust_catcher",
          "scrubber",
          "clarifier",
          "makeup_tank",
        ].includes(d.kind)
          ? cylinder(d)
          : box(d, building),
      )
      .join("");
  }
  function pipeColor(p) {
    if (p.service.includes("가스")) return "#9dba72";
    if (p.service.includes("냉각") || p.service.includes("세정"))
      return "#6fb9c5";
    if (p.service.includes("공기") || p.service.includes("열풍"))
      return "#b2a5c8";
    return "#7fa999";
  }
  return { solidCorners, defs, drawScene, pipeColor };
})();
