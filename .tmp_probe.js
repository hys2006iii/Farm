const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { MiniWS } = require('./.tmp_miniws.js');
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9333 + (Number(process.argv[4]) || 0);
const url = process.argv[2];
const COOKIE = process.argv[6] || '';
const proc = spawn(EDGE, ['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
    '--remote-debugging-port=' + PORT, '--window-size=' + (process.argv[5] || '1600,1200'),
    '--user-data-dir=' + path.join(os.tmpdir(), 'edge-probe-' + PORT + '-' + Date.now()), 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function getJson(p) {
    return new Promise((resolve, reject) => {
        http.get({ host: '127.0.0.1', port: PORT, path: p }, (res) => {
            let b = ''; res.on('data', (c) => (b += c));
            res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
        }).on('error', reject);
    });
}
(async () => {
    let page = null;
    for (let i = 0; i < 40; i++) {
        try { const t = await getJson('/json/list'); page = t.find((x) => x.type === 'page' && x.webSocketDebuggerUrl); if (page) break; } catch (e) {}
        await sleep(500);
    }
    if (!page) { console.log(JSON.stringify({ error: 'no page target' })); proc.kill(); process.exit(1); }
    const ws = new MiniWS(page.webSocketDebuggerUrl);
    let id = 0; const pending = new Map();
    const send = (method, params) => new Promise((res) => { const myId = ++id; pending.set(myId, res); ws.send(JSON.stringify({ id: myId, method, params })); });
    ws.on('message', (raw) => { let m; try { m = JSON.parse(raw); } catch (e) { return; } if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
    await new Promise((r) => ws.on('open', r));
    await send('Network.enable');
    await send('Runtime.enable');
    if (COOKIE) {
        const name = COOKIE.split('=')[0], value = COOKIE.slice(COOKIE.indexOf('=') + 1);
        await send('Network.setCookie', { name: name, value: value, domain: '127.0.0.1', path: '/', url: url });
    }
    await send('Emulation.setDeviceMetricsOverride', { width: Number((process.argv[5]||'1600,1200').split(',')[0]), height: Number((process.argv[5]||'1600,1200').split(',')[1]), deviceScaleFactor: 1, mobile: false });
    await send('Page.enable');
    await send('Page.navigate', { url: url });
    await sleep(5000);
    const expr = fs.readFileSync(process.argv[3], 'utf8');
    const out = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    const val = out.result && out.result.result ? out.result.result.value : out;
    console.log(JSON.stringify(val, null, 2));
    ws.close(); proc.kill(); process.exit(0);
})();

