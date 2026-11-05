const fs = require('fs');
const { chromium } = require('playwright');
(async () => {
  const body = fs.readFileSync('posco-safety-archive.html', 'utf8');
  const wrapped = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style></head><body>' + body + '</body></html>';
  fs.writeFileSync('preview.html', wrapped);
  const browser = await chromium.launch();
  const errors = [];
  for (const [name, vp, scheme] of [['desktop', {width:1280,height:1600}, 'light'], ['phone', {width:400,height:1800}, 'dark']]) {
    const page = await browser.newPage({ viewport: vp, colorScheme: scheme });
    page.on('console', m => { if (m.type() === 'error') errors.push(name + ': ' + m.text()); });
    page.on('pageerror', e => errors.push(name + ' pageerror: ' + e.message));
    await page.goto('file://' + process.cwd() + '/preview.html', { waitUntil: 'load', timeout: 15000 }).catch(e => errors.push('goto ' + e.message));
    const info = await page.evaluate(() => ({
      articles: document.querySelectorAll('article.inc').length,
      years: document.querySelectorAll('.year').length,
      count: document.getElementById('count').textContent,
      scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth,
      links: document.querySelectorAll('a[href^="http"]').length
    }));
    console.log(name, JSON.stringify(info));
    // exercise filters on desktop
    if (name === 'desktop') {
      await page.click('#site-gwangyang');
      console.log('광양:', await page.textContent('#count'));
      await page.click('#site-all');
      await page.click('#chip-gas');
      console.log('gas:', await page.textContent('#count'));
      await page.click('#chip-gas');
      await page.check('#fatal-only');
      console.log('fatal:', await page.textContent('#count'));
      await page.uncheck('#fatal-only');
      await page.fill('#q', '파이넥스');
      console.log('q 파이넥스:', await page.textContent('#count'));
      await page.fill('#q', '');
    }
    await page.screenshot({ path: `shot-${name}.png`, fullPage: false });
    await page.close();
  }
  await browser.close();
  console.log('errors:', errors.length ? errors.join('\n') : 'none');
})();
