#!/usr/bin/env node

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..');
const webRoot = path.join(repoRoot, 'web');

const chromeBin = process.env.CHROME_BIN || process.env.GOOGLE_CHROME || '/usr/bin/google-chrome';
const tolerancePx = Number.isFinite(Number(process.env.IMPACT_LAYOUT_TOLERANCE_PX))
  ? Number(process.env.IMPACT_LAYOUT_TOLERANCE_PX)
  : 2;
const timeoutMs = Number.isFinite(Number(process.env.IMPACT_LAYOUT_TIMEOUT_MS))
  ? Number(process.env.IMPACT_LAYOUT_TIMEOUT_MS)
  : 30000;
const viewportWidth = Number.isFinite(Number(process.env.IMPACT_LAYOUT_VIEWPORT_WIDTH))
  ? Number(process.env.IMPACT_LAYOUT_VIEWPORT_WIDTH)
  : 1366;
const viewportHeight = Number.isFinite(Number(process.env.IMPACT_LAYOUT_VIEWPORT_HEIGHT))
  ? Number(process.env.IMPACT_LAYOUT_VIEWPORT_HEIGHT)
  : 1800;

function fail(message) {
  console.error(`ERROR: ${message}`);
  process.exitCode = 1;
  throw new Error(message);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function findFreePort() {
  return await new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const address = srv.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      srv.close((closeErr) => {
        if (closeErr) reject(closeErr);
        else resolve(port);
      });
    });
  });
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case '.html':
      return 'text/html; charset=utf-8';
    case '.js':
    case '.mjs':
      return 'text/javascript; charset=utf-8';
    case '.css':
      return 'text/css; charset=utf-8';
    case '.json':
      return 'application/json; charset=utf-8';
    case '.svg':
      return 'image/svg+xml';
    case '.png':
      return 'image/png';
    case '.jpg':
    case '.jpeg':
      return 'image/jpeg';
    case '.woff2':
      return 'font/woff2';
    case '.woff':
      return 'font/woff';
    case '.csv':
      return 'text/csv; charset=utf-8';
    default:
      return 'application/octet-stream';
  }
}

function createStaticServer(rootDir) {
  const rootAbs = path.resolve(rootDir);
  const server = http.createServer(async (req, res) => {
    try {
      const rawUrl = req.url || '/';
      const url = new URL(rawUrl, 'http://127.0.0.1');
      const pathname = decodeURIComponent(url.pathname);

      if (pathname.startsWith('/api/v1/')) {
        res.writeHead(404, { 'content-type': 'application/json; charset=utf-8' });
        res.end(JSON.stringify({ detail: 'Not Found' }));
        return;
      }

      let filePath = path.join(rootAbs, pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, ''));
      const normalized = path.resolve(filePath);
      if (!normalized.startsWith(rootAbs)) {
        res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
        res.end('Forbidden');
        return;
      }

      let stat;
      try {
        stat = await fsp.stat(normalized);
      } catch {
        res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
        res.end('Not Found');
        return;
      }

      if (stat.isDirectory()) {
        filePath = path.join(normalized, 'index.html');
      } else {
        filePath = normalized;
      }

      const data = await fsp.readFile(filePath);
      res.writeHead(200, {
        'content-type': contentTypeFor(filePath),
        'cache-control': 'no-store'
      });
      res.end(data);
    } catch (err) {
      res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
      res.end(`Internal Server Error: ${err.message}`);
    }
  });

  return server;
}

class CdpClient {
  constructor(webSocket) {
    this.webSocket = webSocket;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    this.closed = false;

    this.webSocket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (Object.prototype.hasOwnProperty.call(payload, 'id')) {
        const pending = this.pending.get(payload.id);
        if (!pending) return;
        this.pending.delete(payload.id);
        if (payload.error) {
          const error = new Error(payload.error.message || `CDP error for ${payload.id}`);
          error.code = payload.error.code;
          pending.reject(error);
        } else {
          pending.resolve(payload.result || {});
        }
        return;
      }
      this.events.push(payload);
      const listener = this._listeners?.get(payload.method);
      if (listener) listener(payload);
    };
    this.webSocket.onclose = () => {
      this.closed = true;
      const error = new Error('Chrome websocket closed unexpectedly');
      for (const pending of this.pending.values()) pending.reject(error);
      this.pending.clear();
    };
    this.webSocket.onerror = (err) => {
      const error = new Error(`Chrome websocket error: ${err.message || 'unknown'}`);
      for (const pending of this.pending.values()) pending.reject(error);
      this.pending.clear();
    };
    this._listeners = new Map();
  }

  on(method, handler) {
    this._listeners.set(method, handler);
  }

  off(method) {
    this._listeners.delete(method);
  }

  send(method, params = {}, sessionId = undefined) {
    if (this.closed) {
      return Promise.reject(new Error('Chrome websocket is closed'));
    }
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.webSocket.send(JSON.stringify(payload));
    });
  }
}

async function waitForJsonVersion(port, timeout) {
  const started = Date.now();
  const url = `http://127.0.0.1:${port}/json/version`;
  let lastErr = null;
  while (Date.now() - started < timeout) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload = await res.json();
      if (typeof payload.webSocketDebuggerUrl === 'string' && payload.webSocketDebuggerUrl) return payload;
      throw new Error('webSocketDebuggerUrl missing');
    } catch (err) {
      lastErr = err;
      await sleep(200);
    }
  }
  throw lastErr || new Error(`Timeout waiting for Chrome debugging endpoint on port ${port}`);
}

async function launchChrome(url, port, userDataDir) {
  const chromeArgs = [
    '--headless=new',
    '--no-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--remote-allow-origins=*',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${userDataDir}`,
    `--window-size=${viewportWidth},${viewportHeight}`,
    url
  ];
  const proc = spawn(chromeBin, chromeArgs, {
    stdio: ['ignore', 'pipe', 'pipe']
  });

  let stderr = '';
  proc.stderr.on('data', (chunk) => {
    stderr += chunk.toString('utf8');
  });

  const exitPromise = new Promise((resolve, reject) => {
    proc.once('error', reject);
    proc.once('exit', (code, signal) => {
      resolve({ code, signal, stderr });
    });
  });

  return { proc, exitPromise };
}

async function connectChrome(webSocketUrl) {
  const ws = new WebSocket(webSocketUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('Unable to connect to Chrome websocket')), { once: true });
  });
  return new CdpClient(ws);
}

async function openPageAndMeasure(cdp, url, label) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Log.enable', {}, sessionId);
  await cdp.send('Page.navigate', { url }, sessionId);

  const rowsReadyExpr = `(() => {
    const storm = document.querySelectorAll('#impact-table-storm-body tr td:first-child').length;
    const cmcc = document.querySelectorAll('#impact-table-cmcc-body tr td:first-child').length;
    return storm >= 6 && cmcc >= 6;
  })()`;
  const timeoutAt = Date.now() + timeoutMs;
  let lastError = '';
  while (Date.now() < timeoutAt) {
    try {
      const result = await cdp.send('Runtime.evaluate', {
        expression: rowsReadyExpr,
        returnByValue: true,
        awaitPromise: true
      }, sessionId);
      if (result?.result?.value) break;
    } catch (err) {
      lastError = err.message || String(err);
    }
    await sleep(400);
  }

  const metrics = await cdp.send('Runtime.evaluate', {
    expression: `(() => {
      const collect = (bodySelector) => {
        const body = document.querySelector(bodySelector);
        if (!body) return { rowCount: 0, rows: [] };
        const rows = Array.from(body.querySelectorAll('tr')).map((tr) => {
          const cells = Array.from(tr.querySelectorAll('td'));
          if (cells.length < 2) return null;
          const nameCell = cells[0];
          const stateCell = cells[1];
          return {
            label: nameCell.textContent.trim(),
            nameClientWidth: nameCell.clientWidth,
            nameScrollWidth: nameCell.scrollWidth,
            stateClientWidth: stateCell.clientWidth,
            stateScrollWidth: stateCell.scrollWidth
          };
        }).filter(Boolean);
        return { rowCount: rows.length, rows };
      };
      return {
        title: document.title,
        storm: collect('#impact-table-storm-body'),
        stormCmcc: collect('#impact-table-cmcc-body')
      };
    })()`,
    returnByValue: true,
    awaitPromise: true
  }, sessionId);

  const value = metrics?.result?.value;
  if (!value) {
    fail(`No metrics returned for ${label}`);
  }
  return { sessionId, metrics: value, lastError };
}

function assertNoOverflow(pageLabel, tableLabel, tableMetrics) {
  if (!tableMetrics || !Array.isArray(tableMetrics.rows) || tableMetrics.rows.length === 0) {
    fail(`${pageLabel} ${tableLabel}: no impact rows rendered`);
  }

  const badRows = tableMetrics.rows.filter((row) => {
    const overflow = Math.max(0, Number(row.nameScrollWidth || 0) - Number(row.nameClientWidth || 0));
    return overflow > tolerancePx;
  });

  if (badRows.length) {
    const details = badRows.map((row) => {
      const overflow = Math.max(0, Number(row.nameScrollWidth || 0) - Number(row.nameClientWidth || 0));
      return `${row.label} overflow=${overflow}px (client=${row.nameClientWidth}, scroll=${row.nameScrollWidth})`;
    }).join('; ');
    fail(`${pageLabel} ${tableLabel}: network-name text overflows the first column: ${details}`);
  }
}

async function main() {
  if (!fs.existsSync(chromeBin)) {
    fail(`Chrome binary not found: ${chromeBin}`);
  }

  const staticPort = await findFreePort();
  const chromePort = await findFreePort();
  const userDataDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'sib-layout-chrome-'));
  const server = createStaticServer(webRoot);

  await new Promise((resolve) => server.listen(staticPort, '127.0.0.1', resolve));

  const pageBase = `http://127.0.0.1:${staticPort}/`;
  const { proc, exitPromise } = await launchChrome(pageBase, chromePort, userDataDir);

  try {
    const version = await waitForJsonVersion(chromePort, timeoutMs);
    const cdp = await connectChrome(version.webSocketDebuggerUrl);

    const targets = [
      { label: 'Guadeloupe', url: `${pageBase}#page1` },
      { label: 'Martinique', url: `${pageBase}#page2` }
    ];

    for (const target of targets) {
      const { metrics } = await openPageAndMeasure(cdp, target.url, target.label);
      assertNoOverflow(target.label, 'STORM', metrics.storm);
      assertNoOverflow(target.label, 'STORM_CMCC', metrics.stormCmcc);
      console.log(`OK: ${target.label} impact tables render without first-column overflow.`);
    }

    console.log('OK: impact-table layout smoke test passed.');
  } finally {
    proc.kill('SIGTERM');
    const exitInfo = await Promise.race([
      exitPromise,
      sleep(2000).then(() => null)
    ]);
    if (!exitInfo) proc.kill('SIGKILL');
    server.close();
  }
}

main().catch((err) => {
  console.error(`ERROR: ${err.message}`);
  process.exit(1);
});
