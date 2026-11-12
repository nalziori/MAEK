// End-to-end checks for the public site. Run `sh site/build.sh`, serve _site/, then `npm test` in site/.
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const origin = (process.env.MAEK_SITE_ORIGIN || "http://127.0.0.1:8899").replace(/\/$/, "");
const chrome = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const shots = fileURLToPath(new URL("./.shots/", import.meta.url));
mkdirSync(shots, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
const check = (name, ok, detail = "") => { results.push(ok); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`); };

const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1366, height: 768 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // Landing carousel
  await page.goto(origin + "/", { waitUntil: "networkidle0" });
  const slide = () => page.evaluate(() => location.hash);
  check("landing starts on slide 1", (await slide()) === "#1");
  await page.screenshot({ path: shots + "landing-1.png" });
  await sleep(10000);
  check("no autoplay after 10 s", (await slide()) === "#1");
  await page.click("#next"); await sleep(700);
  check("next button", (await slide()) === "#2");
  await page.screenshot({ path: shots + "landing-2.png" });
  await page.keyboard.press("ArrowRight"); await sleep(700);
  check("arrow key", (await slide()) === "#3");
  check("video default 1.5x", await page.$eval("#demo", (v) => v.playbackRate === 1.5));
  await page.click('[data-rate="2"]');
  check("speed button 2x", await page.$eval("#demo", (v) => v.playbackRate === 2));
  await page.click('[data-rate="1.5"]');
  await page.screenshot({ path: shots + "landing-3.png" });
  await page.keyboard.press("ArrowLeft"); await sleep(700);
  check("previous via arrow key", (await slide()) === "#2");
  await page.click("#dots button:nth-child(4)"); await sleep(700);
  check("dot navigation", (await slide()) === "#4");
  await page.screenshot({ path: shots + "landing-4.png" });
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.mouse.click(300, 650)]);
  check("click anywhere on slide 4 opens sim", new URL(page.url()).pathname.endsWith("/sim/"));

  // Simulation dashboard
  await page.waitForFunction(() => window.__sim, { timeout: 60000 });
  const sim = (fn, arg) => page.evaluate(fn, arg);
  check("coachmark shown on entry", await sim(() => !document.getElementById("coach").hidden));
  const steps = [];
  for (let k = 0; k < 8; k++) {
    steps.push(await sim(() => document.getElementById("tip-title").textContent));
    if (k < 7) await page.click("#tip-next");
  }
  check("coachmark explains the BFG scenario", steps[0].includes("부생가스"));
  check("coachmark introduces window enlarge", steps.some((s) => s.includes("크게")));
  await page.screenshot({ path: shots + "sim-coach-last.png" });
  await page.click("#tip-next");
  const started = await page.waitForFunction(() => document.getElementById("coach").hidden && window.__sim.t > 0.5, { timeout: 8000 }).then(() => true, () => false);
  check("last coachmark step starts playback", started);

  // bento: during playback the clicked window grows to 1.5x of the equal split
  const size = (w) => sim((w) => { const r = document.querySelector(`[data-win="${w}"]`).getBoundingClientRect(); return [r.width, r.height]; }, w);
  const [w0, h0] = await size("ir");
  const t0 = await sim(() => window.__sim.t);
  await page.click('[data-win="ir"] .body'); await sleep(900);
  const [w1, h1] = await size("ir");
  const near = (a, b) => Math.abs(a / b - 1.5) < 0.03;
  check("window grows 1.5x while playing", near(w1, w0) && near(h1, h0), `${(w1 / w0).toFixed(3)} x ${(h1 / h0).toFixed(3)}`);
  const running = await page.waitForFunction((t0) => window.__sim.t > t0 + 0.5, { timeout: 8000 }, t0).then(() => true, () => false);
  check("simulation keeps running during enlarge", running);
  await page.screenshot({ path: shots + "sim-bento.png" });
  await page.click('[data-win="ai"] .body'); await sleep(900);
  check("clicking another window moves the enlargement", near((await size("ai"))[0], w0));
  await page.click('[data-win="ai"] .body'); await sleep(900);
  check("clicking again restores the equal split", Math.abs((await size("ir"))[0] / w0 - 1) < 0.02);
  await page.click('[data-win="rgb"] .body'); await sleep(300); await page.keyboard.press("Escape"); await sleep(900);
  check("Escape restores the equal split", Math.abs((await size("rgb"))[0] / w0 - 1) < 0.02);

  // red lamps follow the AI verdicts
  const lamps = async (t) => { await sim((t) => window.__sim.seek(t, false), t); await sleep(t >= 85 ? 3000 : 400); return sim(() => [...window.__sim.state().alerts]); };
  check("corrosion alert by 20 s", (await lamps(20)).join() === "BF1-G003");
  check("leak alert by 40 s", (await lamps(40)).join() === "BF1-G003,BF1-G004");
  check("pitting alert by 100 s", (await lamps(100)).join() === "BF1-G003,BF1-G004,BF1-G005");
  const parity = await sim(async () => { const a = await (await fetch("data/ascan.json")).json(); return [window.__sim.cnn.logit, a.expected_logit]; });
  check("browser CNN logit matches PyTorch", Math.abs(parity[0] - parity[1]) < 1e-4, parity.join(" vs "));

  // end modal
  await sim(() => window.__sim.seek(118.8, true)); await sleep(2500);
  check("tech modal opens at the end", await sim(() => document.getElementById("techdlg").open));
  const m = await sim(() => { const d = document.getElementById("techdlg").getBoundingClientRect(); return [d.left, innerWidth - d.right, d.top, innerHeight - d.bottom]; });
  check("tech modal is centered", Math.abs(m[0] - m[1]) < 2 && Math.abs(m[2] - m[3]) < 2, m.map(Math.round).join(","));
  check("ONNX card is last", await sim(() => document.querySelector("#techcards > :last-child").textContent.includes("ONNX")));
  await page.screenshot({ path: shots + "sim-modal.png" });
  await page.click('#techcards [data-at="0"]'); await sleep(600);
  check("modal card jumps to its scene", await sim(() => !document.getElementById("techdlg").open && window.__sim.t < 2));
  await page.click("#tech"); await sleep(300);
  await page.keyboard.press("Escape"); await sleep(300);
  check("tech button reopens, Escape closes", await sim(() => !document.getElementById("techdlg").open));

  // Try-the-models page: entered from the end modal, every sample re-run in the browser vs the recorded reference
  await page.click("#tech"); await sleep(300);
  await Promise.all([page.waitForNavigation({ waitUntil: "domcontentloaded" }), page.click("#try-next")]);
  check("end modal leads to the try page", new URL(page.url()).pathname.endsWith("/try/"));
  await page.waitForFunction(() => window.__try?.result, { timeout: 120000 });
  const tryAll = await page.evaluate(async () => {
    const wait = async (id) => { for (let i = 0; i < 1200; i++) { const r = window.__try.result; if (window.__try.sample === id && r) return r; await new Promise((ok) => setTimeout(ok, 100)); } return null; };
    const bad = [], ms = {};
    for (const kind of ["corrosion", "thermal", "ultrasonic"]) {
      window.__try.choose(kind); ms[kind] = [];
      for (const s of window.__try.data()[kind].samples) {
        window.__try.pick(s.id);
        const r = await wait(s.id), ref = s.reference;
        if (!r) { bad.push(`${s.id} timeout`); continue; }
        ms[kind].push(Math.round(r.ms));
        if (!r.match) bad.push(`${s.id} wrong`);
        if (kind === "ultrasonic") { if (Math.abs(r.logit - ref.logit) > 1e-3) bad.push(`${s.id} logit`); continue; }
        if (r.dets.length !== ref.detections) bad.push(`${s.id} count ${r.dets.length}/${ref.detections}`);
        else if (ref.detections && Math.abs(r.dets[0].score - ref.confidence) > 0.03) bad.push(`${s.id} score ${r.dets[0].score.toFixed(3)}/${ref.confidence}`);
        if (kind === "corrosion" && ref.detections && !(r.dets[0].area > 100)) bad.push(`${s.id} empty mask`);
      }
    }
    return { bad, ms };
  });
  check("try page: every sample matches truth and the ONNX reference", tryAll.bad.length === 0, tryAll.bad.join(", ") || JSON.stringify(tryAll.ms));
  await page.evaluate(() => window.__try.choose("corrosion"));
  await page.waitForFunction(() => window.__try.sample && window.__try.result, { timeout: 60000 });
  const btns = await page.$$("#samples button");
  for (const b of btns.slice(0, 4)) await b.click(); // fast clicks: the last one must win, without a run error
  const last = await page.$eval("#samples li:nth-child(4) button", (b) => b.dataset.id);
  const fast = await page.waitForFunction((id) => window.__try.sample === id && window.__try.result, { timeout: 60000 }, last).then(() => true, () => false);
  check("try page: fast sample clicks settle on the last one", fast && await page.$eval("#busy", (b) => b.hidden));
  await page.click("#truth");
  await page.screenshot({ path: shots + "try-corrosion.png" });
  await page.click('#models [data-model="thermal"]');
  await page.waitForFunction(() => window.__try.model === "thermal" && window.__try.result, { timeout: 120000 });
  await page.screenshot({ path: shots + "try-thermal.png" });
  await page.click('#models [data-model="ultrasonic"]');
  await page.waitForFunction(() => window.__try.model === "ultrasonic" && window.__try.result, { timeout: 60000 });
  check("try page: model tabs switch and keep the hash", await page.evaluate(() => location.hash === "#ultrasonic"));
  await page.screenshot({ path: shots + "try-ultrasonic.png" });

  // phone portrait gets the notice instead of the 2x2 layout
  const phone = await browser.newPage();
  await phone.setViewport({ width: 390, height: 844, isMobile: true });
  await phone.goto(origin + "/sim/", { waitUntil: "domcontentloaded" });
  check("phone shows PC notice", await phone.evaluate(() => getComputedStyle(document.getElementById("narrow")).display !== "none"));
  await phone.screenshot({ path: shots + "sim-phone.png" });
  await phone.goto(origin + "/try/", { waitUntil: "domcontentloaded" });
  check("try page: phone shows PC notice", await phone.evaluate(() => getComputedStyle(document.getElementById("narrow")).display !== "none"));
  check("no page errors", errors.length === 0, errors.join("; "));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r).length;
console.log(failed ? `${failed} check(s) failed` : `all ${results.length} checks passed`);
process.exit(failed ? 1 : 0);
