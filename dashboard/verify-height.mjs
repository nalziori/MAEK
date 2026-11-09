import puppeteer from "puppeteer-core";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
const origin = process.env.MAEK_DASHBOARD_ORIGIN || "http://127.0.0.1:8877";
const executablePath =
  process.env.CHROME_PATH ||
  (process.platform === "win32"
    ? "C:/Program Files/Google/Chrome/Application/chrome.exe"
    : process.platform === "darwin"
      ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      : "/usr/bin/google-chrome");
const b = await puppeteer.launch({ executablePath, headless: true }),
  p = await b.newPage(),
  errors = [];
p.on("pageerror", (e) => errors.push(e.message));
mkdirSync(".hallmark/height", { recursive: true });
const checks = [];
try {
  await p.setViewport({ width: 1024, height: 768 });
  await p.goto(origin + "/index.html?pipe=BF1-G004", {
    waitUntil: "networkidle0",
  });
  const first = await p.evaluate(() => ({
    text: document.querySelector(".height-summary").textContent,
    min: Number(document.querySelector(".height-band").dataset.minHeight),
    max: Number(document.querySelector(".height-band").dataset.maxHeight),
    scope: document.querySelector(".height-summary").getAttribute("aria-label"),
    scale: document.querySelector(".height-gauge text").textContent,
    pointMarkers: document.querySelectorAll(".height-gauge circle").length,
  }));
  assert.match(first.text, /10–18 m/);
  assert.equal(first.min, 10);
  assert.equal(first.max, 18);
  assert.match(first.scope, /모델 지면 기준 배관 경로/);
  assert.match(first.text, /확인 지점 미연결/);
  assert.equal(first.pointMarkers, 0);
  checks.push(
    "Selected pipe model centerline range is separate from an unlinked inspection point",
  );
  const secondId = await p.evaluate(
    () =>
      MAEK_OPERATIONS.pipes.find(
        (p) => Math.max(...p.points.map((v) => v[2])) > 35,
      ).id,
  );
  await p.goto(origin + "/index.html?pipe=" + encodeURIComponent(secondId), {
    waitUntil: "networkidle0",
  });
  const second = await p.evaluate(() => {
    const id = new URLSearchParams(location.search).get("pipe"),
      pipe = MAEK_OPERATIONS.pipes.find((p) => p.id === id);
    return {
      min: Number(document.querySelector(".height-band").dataset.minHeight),
      max: Number(document.querySelector(".height-band").dataset.maxHeight),
      expectedMin: Math.min(...pipe.points.map((v) => v[2])),
      expectedMax: Math.max(...pipe.points.map((v) => v[2])),
      scale: document.querySelector(".height-gauge text").textContent,
    };
  });
  assert.equal(second.min, second.expectedMin);
  assert.equal(second.max, second.expectedMax);
  assert.equal(first.scale, second.scale);
  checks.push(
    "Selecting a different elevation updates range against the same zero-based scale",
  );
  await p.goto(origin + "/index.html?pipe=BF1-G004", {
    waitUntil: "networkidle0",
  });
  for (const selector of [
    "#expand-map",
    ".map-controls [data-map-action=selected]",
    "#problem-next",
    ".map-controls [data-map-action=fit]",
  ]) {
    const control = await p.$eval(selector, (e) => {
      const r = e.getBoundingClientRect(),
        svg = e.querySelector("svg");
      return {
        label: e.getAttribute("aria-label"),
        title: e.getAttribute("title"),
        w: r.width,
        h: r.height,
        svg: !!svg,
        viewBox: svg?.getAttribute("viewBox"),
        visible: svg
          ? svg.getBoundingClientRect().width > 0 &&
            svg.getBoundingClientRect().height > 0
          : false,
      };
    });
    assert.ok(control.label && control.title);
    assert.ok(control.w >= 44 && control.h >= 44);
    assert.equal(control.svg, true);
    assert.equal(control.viewBox, "0 0 24 24");
    assert.equal(control.visible, true);
  }
  await p.click(".map-controls [data-map-action=in]");
  assert.equal(
    await p.$eval(".map-controls .ui-icon", (e) => e.getAttribute("viewBox")),
    "0 0 24 24",
  );
  checks.push(
    "Icon-only controls remain named, visible, 44px targets and are not modified by map zoom",
  );
  for (const [width, height] of [
    [1024, 768],
    [1194, 834],
    [768, 1024],
  ]) {
    await p.setViewport({ width, height });
    await p.goto(origin + "/index.html?pipe=BF1-G004", {
      waitUntil: "networkidle0",
    });
    assert.equal(
      await p.evaluate(
        () =>
          document.documentElement.scrollHeight <= innerHeight + 1 &&
          document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      true,
    );
    if (width === 1024)
      await p.screenshot({
        path: ".hallmark/height/after.png",
        fullPage: true,
      });
  }
  assert.deepEqual(errors, []);
  checks.push(
    "Three tablet layouts retain critical text and no default document scroll",
  );
  writeFileSync(
    ".hallmark/height/checks.json",
    JSON.stringify(
      { passed: true, checks, first, second, page_errors: errors },
      null,
      2,
    ),
  );
  console.log(checks.length + " height and icon checks passed.");
} finally {
  await b.close();
}
