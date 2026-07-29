// Browser assertions for test-embed-browser.sh (plan Epic 1 spike (e)).
// Driver: the toolchain's OWN playwright (a direct likec4 dependency, pinned by
// the lockfile). Run with NODE_PATH pointing at the toolchain node_modules.
//
// (i)  Direct load (file://, top-level): the diagram mounts, the adversarial
//      payload renders as text (never as an img[onerror] element, never
//      executed), and the golden title is present.
// (ii) Frame-scoped load inside the published section-3.6 sandbox snippet,
//      served over HTTP: the frame is an opaque origin (no allow-same-origin)
//      and the diagram mounts there too, with target=_blank source links.
'use strict';

const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const artifact = process.argv[2];
if (!artifact || !fs.existsSync(artifact)) {
  console.error('usage: node embed_check.js <artifact.html> (artifact missing)');
  process.exit(2);
}
const slug = path.basename(artifact, '.html');

function assert(cond, label) {
  if (!cond) {
    throw new Error('assertion failed: ' + label);
  }
  console.log('ok: ' + label);
}

const MOUNT_TIMEOUT = 45000;

async function checkDirect(browser) {
  console.log('--- (i) direct load (top-level, file://) ---');
  const page = await browser.newPage();
  await page.goto('file://' + artifact, { waitUntil: 'load' });
  await page.waitForFunction(
    () => document.querySelectorAll('.react-flow__node').length > 0,
    null,
    { timeout: MOUNT_TIMEOUT }
  );
  // The adversarial marker lives in view-preview panes that render after the
  // first node mounts - wait on the condition itself, not a duration.
  await page.waitForFunction(
    () => document.body.innerText.indexOf('orrery-adv-payload') !== -1,
    null,
    { timeout: MOUNT_TIMEOUT }
  );
  const info = await page.evaluate(() => ({
    nodes: document.querySelectorAll('.react-flow__node').length,
    imgOnerror: document.querySelectorAll('img[onerror]').length,
    advExecuted: typeof window.orreryAdvPayload,
    hasGoldenTitle: document.body.innerText.indexOf('Acme Shop') !== -1,
    advMarkerAsText: document.body.innerText.indexOf('orrery-adv-payload') !== -1,
  }));
  assert(info.nodes > 0, 'diagram mounted (' + info.nodes + ' nodes)');
  assert(info.hasGoldenTitle, 'golden title node present (Acme Shop)');
  assert(info.imgOnerror === 0, 'no img[onerror] element from repo-derived prose');
  assert(info.advExecuted === 'undefined', 'adversarial payload never executed');
  assert(info.advMarkerAsText, 'adversarial payload renders as text (marker visible)');
  await page.close();
}

async function checkFramed(browser) {
  console.log('--- (ii) frame-scoped load inside the published sandbox snippet ---');
  // Host page carrying the section-3.6 embed snippet VERBATIM (slug substituted).
  const hostPage =
    '<!doctype html>\n<html><head><title>embed host</title></head><body>\n' +
    '<iframe src="/maps/' + slug + '.html"\n' +
    '        sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"\n' +
    '        style="width:100%;height:80vh;border:0" title="System map"></iframe>\n' +
    '</body></html>\n';

  const server = http.createServer((req, res) => {
    if (req.url === '/' || req.url === '/index.html') {
      res.writeHead(200, { 'content-type': 'text/html' });
      res.end(hostPage);
    } else if (req.url === '/maps/' + slug + '.html') {
      res.writeHead(200, { 'content-type': 'text/html' });
      fs.createReadStream(artifact).pipe(res);
    } else {
      res.writeHead(404);
      res.end('not found');
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'load' });
    // Condition-based wait: the child frame exists and its diagram mounted.
    let child = null;
    const deadline = Date.now() + MOUNT_TIMEOUT;
    while (Date.now() < deadline) {
      child = page.frames().find((f) => f !== page.mainFrame());
      if (child) {
        const mounted = await child
          .evaluate(() => document.querySelectorAll('.react-flow__node').length > 0)
          .catch(() => false);
        if (mounted) break;
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    assert(child, 'child frame present');
    const info = await child.evaluate(() => ({
      nodes: document.querySelectorAll('.react-flow__node').length,
      origin: window.origin,
      imgOnerror: document.querySelectorAll('img[onerror]').length,
      advExecuted: typeof window.orreryAdvPayload,
      blankLinks: document.querySelectorAll('a[target=_blank]').length,
    }));
    assert(info.nodes > 0, 'diagram mounted inside the sandboxed iframe (' + info.nodes + ' nodes)');
    assert(info.origin === 'null', 'frame runs as an opaque origin (sandbox without allow-same-origin)');
    assert(info.imgOnerror === 0, 'no img[onerror] element inside the frame');
    assert(info.advExecuted === 'undefined', 'adversarial payload never executed inside the frame');
    assert(info.blankLinks > 0, 'source links present as target=_blank (' + info.blankLinks + ')');
    await page.close();
  } finally {
    server.close();
  }
}

(async () => {
  const browser = await chromium.launch();
  try {
    await checkDirect(browser);
    await checkFramed(browser);
  } finally {
    await browser.close();
  }
  console.log('embed_check.js: PASS');
})().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
