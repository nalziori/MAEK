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
  check("no page errors", errors.length === 0, errors.join("; "));
} finally {
  await browser.close();
}
const failed = results.filter((r) => !r).length;
console.log(failed ? `${failed} check(s) failed` : `all ${results.length} checks passed`);
process.exit(failed ? 1 : 0);
