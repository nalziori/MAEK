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
const base = origin + "/index.html";
mkdirSync(".hallmark/problem", { recursive: true });
const metrics = {},
  checks = [];
async function importResult(path) {
  const [chooser] = await Promise.all([
    p.waitForFileChooser(),
    p.click("#import-ndt"),
  ]);
  await chooser.accept([path]);
}
try {
  for (const [width, height] of [
    [1024, 768],
    [1194, 834],
    [768, 1024],
  ]) {
    await p.setViewport({ width, height });
    for (const tab of ["home", "pipes"]) {
      await p.goto(base + "?tab=" + tab + "&pipe=BF1-G004", {
        waitUntil: "networkidle0",
      });
      await p.evaluate(() => localStorage.removeItem("maek.ndt.linked.v1"));
      const m = await p.evaluate(() => ({
        vertical: document.documentElement.scrollHeight > innerHeight + 1,
        horizontal: document.documentElement.scrollWidth > innerWidth + 1,
        navCount: document.querySelectorAll(".side-nav [data-tab]").length,
        body: getComputedStyle(document.body).fontSize,
      }));
      metrics[width + "x" + height + "-" + tab] = m;
      assert.equal(
        m.horizontal,
        false,
        JSON.stringify({ width, height, tab, m }),
      );
      assert.equal(
        m.vertical,
        false,
        JSON.stringify({ width, height, tab, m }),
      );
      assert.equal(m.navCount, 2);
      if (width === 1024)
        await p.screenshot({
          path: ".hallmark/problem/" + tab + ".png",
          fullPage: true,
        });
    }
  }
  checks.push(
    "Problem-first workspace, two primary destinations on three tablet sizes fit without document scrolling",
  );
  await p.setViewport({ width: 1024, height: 768 });
  await p.goto(base + "?pipe=BF1-G004", { waitUntil: "networkidle0" });
  const issueIDs = await p.evaluate(() =>
    MAEK_OPERATIONS.pipes
      .filter((r) => r.result === "candidate")
      .map((r) => r.id),
  );
  assert.equal(await p.$$eval(".map-spot", (es) => es.length), issueIDs.length);
  const reached = [];
  for (let n = 0; n < 4; n++) {
    reached.push(
      ...(await p.$$eval("[data-problem]", (es) =>
        es.map((e) => e.dataset.problem),
      )),
    );
    if (n < 3) await p.click("#problem-next");
  }
  assert.deepEqual(reached, issueIDs);
  await p.click('.map-panel [data-map-action="fit"]');
  await p.click('.map-spot[data-map-pipe="' + issueIDs[0] + '"]');
  assert.equal(
    await p.$eval(".problem-card[aria-pressed=true]", (e) => e.dataset.problem),
    issueIDs[0],
  );
  await p.click('.map-panel [data-map-action="fit"]');
  await p.click('.map-spot[data-map-pipe="' + issueIDs[15] + '"]');
  assert.equal(
    await p.$eval(".problem-card[aria-pressed=true]", (e) => e.dataset.problem),
    issueIDs[15],
  );
  assert.match(
    await p.$eval(".selected-issue", (e) => e.textContent),
    /부식 의심/,
  );
  checks.push(
    "All 16 issue IDs reachable, map numbers match list and selecting map moves to matching list page",
  );
  await p.setViewport({ width: 1024, height: 768 });
  await p.goto(base + "?pipe=BF1-G004", { waitUntil: "networkidle0" });
  assert.equal(
    await p.$eval(
      ".sensor-image img",
      (e) => e.complete && e.naturalWidth === 640,
    ),
    true,
  );
  assert.match(await p.$eval(".sensor-image img", (e) => e.alt), /BF1-G004/);
  assert.match(
    await p.$eval(".sensor-empty", (e) => e.textContent),
    /열화상.*미연결/,
  );
  assert.match(
    await p.$eval(".ndt-pending", (e) => e.textContent),
    /검사 결과 미접수/,
  );
  assert.ok((await p.$$eval(".rgb-region", (e) => e.length)) > 0);
  checks.push(
    "Verified same-pipe saved RGB and mapped regions shown; unlinked thermal and NDT never shown as normal",
  );
  await p.goto(base + "?pipe=BF2-G101", { waitUntil: "networkidle0" });
  const active = await p.$eval(".pipe-context h2", (e) =>
    e.firstChild.textContent.trim(),
  );
  assert.equal(active, await p.evaluate(() => MAEK_OPERATIONS.pipes[125].id));
  assert.match(
    await p.$eval(".sensor-image img", (e) => e.alt),
    new RegExp(active),
  );
  await p.click('.map-panel [data-map-action="fit"]');
  await p.click('.map-spot[data-map-pipe="BF1-G004"]');
  assert.equal(
    await p.$eval(".pipe-context h2", (e) => e.firstChild.textContent.trim()),
    "BF1-G004",
  );
  checks.push(
    "Pipe links and map selection update all sensor panels to the selected pipe",
  );
  const record = {
    result_id: "UI-TEST-ONLY-1",
    pipe_id: "BF1-G004",
    inspection_point: "테스트용 부위",
    method: "UT 두께 · UI 검증용",
    performed_at: "2026-11-09T13:00:00+09:00",
    inspector: "테스트 검사자",
    result_summary: "UI 검증용 결과이며 실제 측정값이 아닙니다.",
    procedure_ref: "TEST-PROCEDURE",
    coverage_ref: "TEST-COVERAGE",
    report_ref: "TEST-REPORT",
  };
  writeFileSync(".hallmark/problem/ndt-test.json", JSON.stringify(record));
  await importResult(".hallmark/problem/ndt-test.json");
  await p.waitForSelector(".ndt-measurement");
  assert.match(
    await p.$eval(".ndt-result-row", (e) => e.textContent),
    /검토 대기/,
  );
  await p.reload({ waitUntil: "networkidle0" });
  assert.match(
    await p.$eval(".ndt-measurement", (e) => e.textContent),
    /실제 측정값이 아닙니다/,
  );
  checks.push(
    "Valid same-pipe NDT report links below drone evidence, persists locally and remains review-pending",
  );
  await p.goto(base + "?pipe=BF2-G101", { waitUntil: "networkidle0" });
  assert.equal(await p.$(".ndt-measurement"), null);
  assert.ok(await p.$(".ndt-pending"));
  await importResult(".hallmark/problem/ndt-test.json");
  await p.waitForFunction(() =>
    document
      .querySelector(".ndt-feedback")
      ?.textContent.includes("배관 번호가 다릅니다"),
  );
  assert.equal(await p.$(".ndt-measurement"), null);
  checks.push("Other pipe does not inherit NDT; mismatched import rejected");
  await p.goto(base + "?pipe=BF1-G004", { waitUntil: "networkidle0" });
  const conflict = { ...record, result_summary: "다른 내용" };
  writeFileSync(
    ".hallmark/problem/ndt-conflict.json",
    JSON.stringify(conflict),
  );
  await importResult(".hallmark/problem/ndt-conflict.json");
  await p.waitForFunction(() =>
    document
      .querySelector(".ndt-feedback")
      ?.textContent.includes("같은 결과 번호"),
  );
  assert.match(
    await p.$eval(".ndt-measurement", (e) => e.textContent),
    /실제 측정값이 아닙니다/,
  );
  checks.push(
    "Conflicting result ID rejected without overwriting original report",
  );
  await p.click('[data-tab="pipes"]');
  assert.equal(await p.$eval("#page-title", (e) => e.textContent), "배관 조회");
  assert.match(
    await p.$eval(".lookup-overview", (e) => e.textContent),
    /현장 검사결과 1건/,
  );
  await p.click('.pipe-detail [data-route="home"]');
  assert.equal(new URL(p.url()).searchParams.get("pipe"), "BF1-G004");
  assert.equal(
    await p.$eval(".pipe-context h2", (e) => e.firstChild.textContent.trim()),
    "BF1-G004",
  );
  await p.goBack();
  await p.waitForFunction(() => document.body.dataset.tab === "pipes");
  assert.equal(new URL(p.url()).searchParams.get("pipe"), "BF1-G004");
  checks.push(
    "Unified lookup shows the latest result and opens the same pipe on the map; back retains selection",
  );

  await p.select("#status-filter", "candidate");
  assert.match(await p.$eval(".rows-footer", (e) => e.textContent), /16개 중/);
  const filteredIDs = await p.$$eval("[data-pipe]", (es) =>
    es.map((e) => e.dataset.pipe),
  );
  assert.ok(filteredIDs.every((id) => issueIDs.includes(id)));
  await p.type("#pipe-search", "BF1-G004");
  await p.click('[data-pipe="BF1-G004"]');
  await p.click('.pipe-detail [data-route="home"]');
  const older = {
    ...record,
    result_id: "UI-TEST-ONLY-OLDER",
    performed_at: "2026-11-08T13:00:00+09:00",
    result_summary: "과거 검사 UI 시험 자료",
  };
  writeFileSync(".hallmark/problem/ndt-older.json", JSON.stringify(older));
  await importResult(".hallmark/problem/ndt-older.json");
  await p.waitForFunction(() =>
    document
      .querySelector(".ndt-feedback")
      ?.textContent.includes("저장했습니다"),
  );
  assert.match(
    await p.$eval(".ndt-measurement", (e) => e.textContent),
    /실제 측정값이 아닙니다/,
  );
  await p.click('[data-tab="pipes"]');
  assert.equal(await p.$eval("#pipe-search", (e) => e.value), "BF1-G004");
  assert.equal(await p.$eval("#status-filter", (e) => e.value), "candidate");
  assert.equal(
    await p.$eval(".latest-inspection time", (e) => e.getAttribute("datetime")),
    record.performed_at,
  );
  assert.match(
    await p.$eval(".lookup-history summary", (e) => e.textContent),
    /2건/,
  );
  assert.equal(await p.$eval(".lookup-history", (e) => e.open), false);
  await p.click(".lookup-history summary");
  assert.deepEqual(
    await p.$$eval(".inspection-history > li", (es) =>
      es.map((e) => e.dataset.resultId),
    ),
    [record.result_id, older.result_id],
  );
  for (const [width, height] of [
    [1024, 768],
    [1194, 834],
    [768, 1024],
  ]) {
    await p.setViewport({ width, height });
    assert.equal(
      await p.evaluate(
        () => document.documentElement.scrollHeight > innerHeight + 1,
      ),
      false,
    );
  }
  checks.push(
    "Lookup retains search/filter; latest and expanded history sort by inspection time rather than import order and stay within tablet viewport",
  );

  await p.select("#status-filter", "all");
  await p.$eval("#pipe-search", (e) => {
    e.value = "";
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await p.click('[data-pipe="BF1-G001"]');
  assert.equal(
    await p.$eval(
      '.pipe-row[data-selected="true"] [data-pipe]',
      (e) => e.dataset.pipe,
    ),
    "BF1-G001",
  );
  assert.equal(
    await p.evaluate(() => document.activeElement.dataset.pipe),
    "BF1-G001",
  );
  assert.equal(
    await p.$eval('[data-pipe="BF1-G001"]', (e) =>
      e.getAttribute("aria-current"),
    ),
    "true",
  );
  assert.match(
    await p.$eval(".lookup-overview", (e) => e.textContent),
    /결과 미접수/,
  );
  checks.push(
    "Lookup selection updates the detail and focus without exposing another pipe’s reports",
  );
  await p.evaluate(() => localStorage.removeItem("maek.ndt.linked.v1"));
  for (const alias of ["areas", "records"]) {
    await p.goto(base + "?tab=" + alias + "&pipe=BF2-G101", {
      waitUntil: "networkidle0",
    });
    assert.equal(new URL(p.url()).searchParams.get("tab"), "pipes");
    assert.equal(
      await p.$eval(".pipe-detail h2", (e) => e.textContent),
      "BF2-G101",
    );
    assert.equal(await p.$$eval(".side-nav [data-tab]", (es) => es.length), 2);
  }
  checks.push(
    "Legacy list/history links resolve to the same unified lookup without losing pipe identity",
  );
  assert.deepEqual(errors, []);
  writeFileSync(
    ".hallmark/problem/checks.json",
    JSON.stringify(
      {
        passed: true,
        metrics,
        checks,
        page_errors: errors,
        local_test_reports_removed: true,
      },
      null,
      2,
    ),
  );
  console.log(checks.length + " unified flow checks passed.");
} finally {
  await p
    .evaluate(() => localStorage.removeItem("maek.ndt.linked.v1"))
    .catch(() => {});
  await b.close();
}
