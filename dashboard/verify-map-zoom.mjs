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
  const geometry = await p.evaluate(() => ({
    buildings: document.querySelectorAll(".solid-building[data-building]")
      .length,
    devices: document.querySelectorAll(".solid-device[data-device]").length,
    expectedBuildings: MAEK_OPERATIONS.buildings.length,
    expectedDevices: MAEK_OPERATIONS.devices.length,
    pipeIds: [...document.querySelectorAll(".pipe-hit")].map(
      (e) => e.dataset.mapPipe,
    ),
    expectedPipeIds: MAEK_OPERATIONS.pipes.map((e) => e.id),
    heightProjectsUpward: project([0, 0, 10])[1] < project([0, 0, 0])[1],
  }));
  assert.equal(geometry.buildings, geometry.expectedBuildings);
  assert.equal(geometry.devices, geometry.expectedDevices);
  assert.deepEqual(geometry.pipeIds, geometry.expectedPipeIds);
  assert.equal(geometry.heightProjectsUpward, true);
  checks.push(
    "Industrial renderer preserves model equipment, all 247 pipe IDs and vertical projection",
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
  assert.ok(Math.abs((await box())[2] - initial[2]) < 1);
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
  assert.ok((await box())[2] < initial[2]);
  checks.push("Two-finger pinch zoom");
  await p.click(".map-panel [data-map-action=fit]");
  assert.ok((await p.$$eval(".drone-trail", (es) => es.length)) > 0);
  assert.equal(await p.$$eval(".visited-zone", (es) => es.length), 2);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /방문 구역/);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /현재 위치/);
  assert.match(await p.$eval(".map-panel", (e) => e.textContent), /조치 필요/);
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
  const gradientIds = await p.$$eval("linearGradient[id]", (es) =>
    es.map((e) => e.id),
  );
  assert.equal(new Set(gradientIds).size, gradientIds.length);

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
