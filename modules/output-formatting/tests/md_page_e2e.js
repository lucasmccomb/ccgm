// Browser assertions for test-md-page-e2e.sh. Headless Chromium only.
// Driver: orrery's pinned playwright, run with NODE_PATH at its node_modules
// (same approach as modules/orrery/tests/e2e/embed_check.js).
//
//   node md_page_e2e.js <basic.html> <xss.html> <mermaid.html>
//
// Static checks cannot prove a page renders: a wrong SRI hash or a missing
// crossorigin attribute blocks the script and leaves a blank page. Only a
// browser run shows that.
'use strict';

const { chromium } = require('playwright');
const fs = require('fs');

const [basic, xss, mermaid] = process.argv.slice(2);
for (const f of [basic, xss, mermaid]) {
  if (!f || !fs.existsSync(f)) {
    console.error('usage: node md_page_e2e.js <basic.html> <xss.html> <mermaid.html>');
    process.exit(2);
  }
}

const TIMEOUT = 45000;

function assert(cond, label) {
  if (!cond) throw new Error('assertion failed: ' + label);
  console.log('ok: ' + label);
}

async function online(browser) {
  console.log('--- online: headings render, scripts pass SRI ---');
  const page = await browser.newPage();
  await page.goto('file://' + basic, { waitUntil: 'load' });
  await page.waitForSelector('#content h1', { timeout: TIMEOUT });
  const heads = await page.$$eval('#content h1, #content h2', (els) => els.map((e) => e.textContent));
  assert(heads[0] === 'Release Report', 'h1 rendered: ' + heads[0]);
  for (const h of ['Summary', 'Results', 'Risks', 'Rollback', 'Follow-ups']) {
    assert(heads.includes(h), 'h2 rendered: ' + h);
  }
  assert((await page.$$('nav#toc a')).length === 5, 'table of contents lists the 5 sections');
  assert((await page.$$('.table-wrap table')).length === 1, 'table wrapped for narrow screens');
  await page.close();
}

async function offline(browser) {
  console.log('--- offline: the markdown stays readable ---');
  // JavaScript off: the <noscript> copy renders.
  const noJs = await browser.newContext({ javaScriptEnabled: false });
  await noJs.route(/^https?:/, (route) => route.abort());
  const p1 = await noJs.newPage();
  await p1.goto('file://' + basic, { waitUntil: 'load' });
  const ns = p1.locator('noscript pre');
  assert(await ns.isVisible(), '<noscript> markdown is visible with JavaScript off');
  assert((await ns.textContent()).includes('The answer: the migration is safe to ship.'), '<noscript> holds the markdown text');
  await noJs.close();

  // JavaScript on, network blocked: the script fallback shows the source.
  const blocked = await browser.newContext();
  await blocked.route(/^https?:/, (route) => route.abort());
  const p2 = await blocked.newPage();
  await p2.goto('file://' + basic, { waitUntil: 'load' });
  await p2.waitForSelector('#fallback', { timeout: TIMEOUT });
  assert(await p2.locator('#fallback').isVisible(), 'source fallback is visible with the network blocked');
  assert((await p2.locator('#fallback').textContent()).includes('## Summary'), 'source fallback holds the markdown text');
  await blocked.close();
}

async function hostile(browser) {
  console.log('--- hostile markdown never executes ---');
  const page = await browser.newPage();
  await page.goto('file://' + xss, { waitUntil: 'load' });
  await page.waitForSelector('#content h1', { timeout: TIMEOUT });
  // Give a late onerror or script a real chance to fire: wait for the image
  // request to fail rather than a fixed delay.
  await page.waitForLoadState('networkidle');
  const info = await page.evaluate(() => ({
    x: typeof window.__x,
    y: typeof window.__y,
    onerror: document.querySelectorAll('[onerror]').length,
    scripts: document.querySelectorAll('#content script').length,
    after: document.body.innerText.indexOf('Text after the payloads.') !== -1,
  }));
  assert(info.x === 'undefined', 'window.__x is undefined (img onerror stripped)');
  assert(info.y === 'undefined', 'window.__y is undefined (script injection stripped)');
  assert(info.onerror === 0, 'no element carries an onerror attribute');
  assert(info.scripts === 0, 'no script element inside the rendered content');
  assert(info.after, 'text after the payloads still renders');
  await page.close();
}

async function mermaidPage(browser) {
  console.log('--- mermaid block renders to SVG ---');
  const page = await browser.newPage();
  await page.goto('file://' + mermaid, { waitUntil: 'load' });
  await page.waitForSelector('#content pre.mermaid svg', { timeout: TIMEOUT });
  const svgs = await page.$$eval('#content pre.mermaid svg', (els) => els.length);
  assert(svgs > 0, 'mermaid diagram rendered as SVG inside pre.mermaid (' + svgs + ')');
  await page.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await online(browser);
    await offline(browser);
    await hostile(browser);
    await mermaidPage(browser);
  } finally {
    await browser.close();
  }
  console.log('md_page_e2e.js: PASS');
})().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
