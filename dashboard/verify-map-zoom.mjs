import puppeteer from "puppeteer-core";
const origin = process.env.MAEK_DASHBOARD_ORIGIN || "http://127.0.0.1:8877";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const b = await puppeteer.launch({
  executablePath:
    process.env.CHROME_PATH ||
    (process.platform === "win32"
      ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
      : process.platform === "darwin"
        ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        : "/usr/bin/google-chrome"),
  headless: true,
});
const p = await b.newPage(),
  errors = [];
p.on("pageerror", (e) => errors.push(e.message));
mkdirSync(".hallmark/map-zoom", { recursive: true });
const checks = [];
try {
  await p.setViewport({ width: 1024, height: 768, hasTouch: true });
  await p.goto(origin + "/index.html?pipe=BF1-G004", {
    waitUntil: "networkidle0",
  });
  const box = () =>
    p.$eval(".map-panel [data-map] svg", (e) =>
      e.getAttribute("viewBox").split(" ").map(Number),
    );
  const initial = await box();
  for (const [width, height] of [
    [1024, 768],
    [1194, 834],
    [768, 1024],
  ]) {
    await p.setViewport({ width, height, hasTouch: true });
    for (const id of ["BF1-G200", "BF1-G004"]) {
      await p.click(`[data-problem="${id}"]`);
      const focus = await p.$eval(".map-panel .pipe-line.selected", (line) => {
        const svg = line.ownerSVGElement,
          r = svg.getBoundingClientRect();
        const points = Array.from(line.points);
        const middle = new DOMPoint(
          points.reduce((n, v) => n + v.x, 0) / points.length,
          points.reduce((n, v) => n + v.y, 0) / points.length,
        ).matrixTransform(svg.getScreenCTM());
        const view = svg.viewBox.baseVal;
        return {
          dx: Math.abs(middle.x - r.x - r.width / 2),
          dy: Math.abs(middle.y - r.y - r.height / 2),
          aspect: view.width / view.height,
          viewport: r.width / r.height,
        };
      });
      assert.ok(
        focus.dx < 2 && focus.dy < 2,
        `${id} centered at ${width}x${height}`,
      );
      assert.ok(
        Math.abs(focus.aspect - focus.viewport) < 0.01,
        "Camera fills map viewport without letterboxing",
      );
      assert.equal(
        await p.$eval("[data-map-zoom-label]", (e) => e.textContent),
        "220%",
      );
    }
  }
  await p.setViewport({ width: 1024, height: 768, hasTouch: true });
  await p.screenshot({
    path: ".hallmark/map-zoom/focused-home.png",
    fullPage: true,
  });
  checks.push(
    "Initial 220% camera and newly selected pipes center in an aspect-matched map at three tablet sizes",
  );
  await p.click(".map-panel [data-map-action=in]");
  assert.ok((await box())[2] < initial[2]);
  await p.click(".map-panel [data-map-action=out]");
  assert.ok(Math.abs((await box())[2] - initial[2]) < 1);
  await p.click(".map-panel [data-map-action=in]");
  await p.click(".map-panel [data-map-action=in]");
  const beforePan = await box(),
    rect = await p.$eval(".map-panel [data-map]", (e) => {
      const r = e.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    });
  await p.mouse.move(rect.x + rect.w * 0.5, rect.y + rect.h * 0.2);
  await p.mouse.down();
  await p.mouse.move(rect.x + rect.w * 0.5 + 35, rect.y + rect.h * 0.2 + 25, {
    steps: 8,
  });
  await p.mouse.up();
  const afterPan = await box();
  assert.ok(afterPan[0] !== beforePan[0] || afterPan[1] !== beforePan[1]);
  assert.match(
    await p.$eval(".pipe-context h2", (e) => e.textContent),
    /BF1-G004/,
  );
  await p.click(".map-panel [data-map-action=fit]");
  const overview = await box();
  assert.ok(overview[2] > initial[2] * 2);
  assert.equal(
    await p.$eval("[data-map-zoom-label]", (e) => e.textContent),
    "100%",
  );
  await p.click('.map-panel [data-map-action="selected"]');
  assert.deepEqual(
    await box(),
    initial,
    "Selected-pipe action restores the initial focus after overview",
  );
  await p.click('.map-panel [data-map-action="fit"]');
  checks.push(
    "Plus/minus/fit and drag pan change view without changing selected pipe",
  );
  await p.mouse.move(rect.x + rect.w * 0.5, rect.y + rect.h * 0.3);
  await p.mouse.wheel({ deltaY: -150 });
  await p.waitForFunction(
    () =>
      document.querySelector("[data-map-zoom-label]").textContent !== "100%",
  );
  checks.push("Pointer wheel zoom");
  await p.click(".map-panel [data-map-action=fit]");
  const cdp = await p.createCDPSession(),
    x = rect.x + rect.w * 0.5,
    y = rect.y + rect.h * 0.35;
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchStart",
    touchPoints: [
      { x: x - 25, y, id: 1 },
      { x: x + 25, y, id: 2 },
    ],
  });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchMove",
    touchPoints: [
      { x: x - 45, y, id: 1 },
      { x: x + 45, y, id: 2 },
    ],
  });
  await cdp.send("Input.dispatchTouchEvent", {
    type: "touchEnd",
    touchPoints: [],
  });
  assert.ok((await box())[2] < overview[2]);
  checks.push("Two-finger pinch zoom");
  await p.click(".map-panel [data-map-action=fit]");
  assert.ok((await p.$$eval(".drone-trail", (es) => es.length)) > 0);
  assert.equal(await p.$$eval(".visited-zone", (es) => es.length), 2);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /방문 구역/);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /현재 위치/);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /점검 필요/);
  assert.match(
    await p.$eval(".map-source", (e) => e.textContent),
    /저장 경로 재구성/,
  );
  assert.match(
    await p.$eval(".visited-summary", (e) => e.textContent),
    /1고로.*2고로/,
  );
  checks.push(
    "Visited zones, separate per-pipe route traces and current/action terms retain saved-route qualification",
  );
  await p.screenshot({ path: ".hallmark/map-zoom/home.png", fullPage: true });
  await p.click("#expand-map");
  assert.equal(await p.$eval("#media-viewer", (e) => e.open), true);
  assert.match(
    await p.$eval("#media-title", (e) => e.textContent),
    /방문 구역 지도/,
  );
  await p.click("#media-content [data-map-action=in]");
  const fitControl = await p.$eval(
    '#media-content [data-map-action="fit"]',
    (button) => {
      const icon = button.querySelector("svg").getBoundingClientRect();
      const target = button.getBoundingClientRect();
      return {
        iconWidth: icon.width,
        iconHeight: icon.height,
        width: target.width,
        height: target.height,
      };
    },
  );
  assert.equal(
    fitControl.iconWidth,
    18,
    "Large-map fit icon keeps its fixed width",
  );
  assert.equal(
    fitControl.iconHeight,
    18,
    "Large-map fit icon keeps its fixed height",
  );
  assert.ok(fitControl.width >= 44 && fitControl.width <= 54);
  assert.ok(fitControl.height >= 44 && fitControl.height <= 54);
  assert.notEqual(
    await p.$eval("#media-content [data-map-zoom-label]", (e) => e.textContent),
    "100%",
  );
  await p.screenshot({
    path: ".hallmark/map-zoom/map-large.png",
    fullPage: true,
  });
  await p.keyboard.press("Escape");
  assert.equal(await p.$eval("#media-viewer", (e) => e.open), false);
  checks.push("Large map shares camera controls and Escape restores base view");
  await p.click("[data-open-image=rgb]");
  assert.equal(await p.$eval("#media-viewer", (e) => e.open), true);
  const image = await p.$eval("#media-content .sensor-image", (e) => {
    const r = e.getBoundingClientRect();
    return {
      w: r.width,
      h: r.height,
      region: !!e.querySelector(".rgb-region"),
      complete: e.querySelector("img").complete,
    };
  });
  assert.ok(image.w > 600);
  assert.ok(Math.abs(image.w / image.h - 640 / 360) < 0.01);
  assert.equal(image.region, true);
  assert.equal(image.complete, true);
  await p.screenshot({
    path: ".hallmark/map-zoom/rgb-large.png",
    fullPage: true,
  });
  await p.click("#close-media");
  assert.equal(await p.$eval("#media-viewer", (e) => e.open), false);
  assert.equal(
    await p.$eval("[data-open-image=rgb]", (e) => e === document.activeElement),
    true,
  );
  checks.push(
    "RGB enlarges above 600px with correct aspect ratio and candidate overlay; close restores focus",
  );
  assert.deepEqual(errors, []);
  writeFileSync(
    ".hallmark/map-zoom/checks.json",
    JSON.stringify(
      { passed: true, checks, enlarged_image: image, page_errors: errors },
      null,
      2,
    ),
  );
  console.log(checks.length + " map and image interaction checks passed.");
} finally {
  await b.close();
}
