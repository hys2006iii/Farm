/**
 * diag.test.mjs — 设置页「测试连接」按钮的单测。
 *
 * `QH_DIAG.run(target)` 会先静默保存配置再发探测请求，然后把结果写进按钮右侧的
 * 小字。这里锁住四件事：
 *
 * 1. 每个目标都能映射到按钮与结果元素（id 写错会静默失效，最难查）；
 * 2. 请求期间按钮禁用，挡住连点产生重复请求；
 * 3. 成功 / 失败 / 网络异常三条路径都要给出可读文案；
 * 4. 结果用 textContent 写入，不拼 HTML。
 *
 * 运行：node --test "tests/js/**\/*.test.mjs"
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

/** 造一个够用的假元素 */
function fakeEl(id) {
    return {
        id,
        hidden: true,
        disabled: false,
        textContent: '',
        className: '',
        classList: {
            _set: new Set(),
            toggle(name, on) { if (on) this._set.add(name); else this._set.delete(name); },
            contains(name) { return this._set.has(name); }
        }
    };
}

/** 每个用例重建一套 DOM 替身 */
function setupDom() {
    const ids = [
        'diagIotBtn', 'diagIotResult',
        'diagWeatherBtn', 'diagWeatherResult',
        'diagAiBtn', 'diagAiResult',
        'diagWebhookBtn', 'diagWebhookResult'
    ];
    const els = {};
    ids.forEach((id) => { els[id] = fakeEl(id); });
    els.diagIotBtn.textContent = '测试连接';
    els.diagWeatherBtn.textContent = '测试连接';
    els.diagAiBtn.textContent = '测试连接';
    els.diagWebhookBtn.textContent = '推送测试消息';
    return els;
}

let els = setupDom();
const fetchCalls = [];
let fetchImpl = null;

globalThis.window = globalThis;
globalThis.document = { readyState: 'loading', addEventListener() {}, getElementById: (id) => els[id] || null };
globalThis.QH = {
    $: (id) => els[id] || null,
    setText(el, text) { if (el) el.textContent = String(text); },
    toast() {}, registerTask() {}, setStyle() {}, toggleClass() {},
    openModal() {}, closeModal() {}, dialogAlert() {}
};
globalThis.fetch = function (url, opts) {
    fetchCalls.push({ url, opts });
    return fetchImpl ? fetchImpl(url, opts) : Promise.resolve({ status: 200, json: () => Promise.resolve({}) });
};

require('../../static/js/diag.js');
const DIAG = globalThis.QH_DIAG;

/** 等一轮微任务，让 then 链跑完 */
function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * `run()` 会先把「静默保存」的 Promise 接上再发请求，所以 fetch 不是在调用
 * `run()` 的那一刻同步发生的，断言前必须先让微任务队列跑一轮。
 */
async function tick() {
    await Promise.resolve();
    await Promise.resolve();
}

/**
 * 每个用例重建一套 DOM 替身。
 *
 * 必须 `await`：模块里的 `busy` 表是跨用例共享的，上一个用例若把某目标留在
 * 「进行中」，下一个用例的 `run()` 会被直接挡掉（表现为 fetch 一次都没发）。
 * 这里先把上一轮的微任务排空，再换掉 DOM。
 */
async function reset() {
    await flush();
    await flush();
    els = setupDom();
    fetchCalls.length = 0;
    fetchImpl = null;
}

/* ==================== 目标映射 ==================== */

test('TARGETS: 四个目标都有按钮与结果元素', () => {
    for (const target of ['iot', 'weather', 'ai', 'webhook']) {
        assert.ok(DIAG.TARGETS[target], target);
        const [btnId, resId] = DIAG.TARGETS[target];
        assert.ok(els[btnId], btnId + ' 不存在');
        assert.ok(els[resId], resId + ' 不存在');
    }
});

test('run: 未知目标直接返回，不发请求', async () => {
    await reset();
    DIAG.run('no-such');
    assert.equal(fetchCalls.length, 0);
});

/* ==================== 成功 / 失败 ==================== */

test('run: 成功时显示 ✓ 与后端 message', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({
        status: 200,
        json: () => Promise.resolve({ ok: true, message: '连通正常（120ms）', detail: '模型已正常应答' })
    });
    DIAG.run('ai');
    await flush();
    const res = els.diagAiResult;
    assert.equal(res.hidden, false);
    assert.match(res.textContent, /^✓/);
    assert.match(res.textContent, /连通正常/);
    assert.match(res.textContent, /模型已正常应答/);
    assert.equal(res.classList.contains('is-ok'), true);
    assert.equal(res.classList.contains('is-bad'), false);
});

test('run: 失败时显示 ✗ 且标红', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({
        status: 200,
        json: () => Promise.resolve({ ok: false, message: '未填写 API Key', detail: '' })
    });
    DIAG.run('ai');
    await flush();
    const res = els.diagAiResult;
    assert.match(res.textContent, /^✗/);
    assert.match(res.textContent, /未填写 API Key/);
    assert.equal(res.classList.contains('is-bad'), true);
});

test('run: 后端返回 error 字段时也按失败渲染', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({ status: 400, json: () => Promise.resolve({ error: '未知的测试目标：x' }) });
    DIAG.run('iot');
    await flush();
    assert.match(els.diagIotResult.textContent, /未知的测试目标/);
});

test('run: 响应不是 JSON 时给出可读提示而不是卡住', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({
        status: 502,
        json: () => Promise.reject(new Error('not json'))
    });
    DIAG.run('iot');
    await flush();
    assert.match(els.diagIotResult.textContent, /无法解析/);
    assert.match(els.diagIotResult.textContent, /502/);
});

test('run: 网络异常时按钮要恢复可用，不能停在「测试中…」', async () => {
    await reset();
    fetchImpl = () => Promise.reject(new Error('offline'));
    DIAG.run('iot');
    await flush();
    assert.equal(els.diagIotBtn.disabled, false);
    assert.equal(els.diagIotBtn.textContent, '测试连接');
    assert.match(els.diagIotResult.textContent, /offline/);
});

/* ==================== 按钮状态 ==================== */

test('run: 请求期间按钮禁用并显示「测试中…」', async () => {
    await reset();
    let release;
    fetchImpl = () => new Promise((resolve) => { release = resolve; });
    DIAG.run('iot');
    assert.equal(els.diagIotBtn.disabled, true, '按钮应在调用当刻就禁用，挡住连点');
    assert.equal(els.diagIotBtn.textContent, '测试中…');
    await tick();
    release({ status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' }) });
    await flush();
});

test('run: 结束后按钮文案还原为原标题', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({ status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' }) });
    DIAG.run('webhook');
    await flush();
    assert.equal(els.diagWebhookBtn.textContent, '推送测试消息');
});

test('run: 连点只发一次请求', async () => {
    await reset();
    let release;
    fetchImpl = () => new Promise((resolve) => { release = resolve; });
    DIAG.run('iot');
    DIAG.run('iot');
    DIAG.run('iot');
    await tick();
    assert.equal(fetchCalls.length, 1, '请求期间重复点击不应再发请求');
    release({ status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' }) });
    // 必须等这次请求彻底收尾：模块里的 busy 表是跨用例共享的，
    // 上一个用例若把 iot 留在「进行中」，下一个用例的 run('iot') 会被直接挡掉。
    await flush();
});

test('run: 不同目标互不影响，可以各自测', async () => {
    await reset();
    // 两个目标各发一次请求，各自的 promise 要分别放行：只 release 一次会漏掉
    // 前一个，把那个目标永久留在「进行中」，污染后面的用例。
    const pending = [];
    fetchImpl = () => new Promise((resolve) => { pending.push(resolve); });
    DIAG.run('iot');
    DIAG.run('weather');
    await tick();
    assert.equal(fetchCalls.length, 2);
    assert.equal(els.diagIotBtn.disabled, true);
    assert.equal(els.diagWeatherBtn.disabled, true);
    pending.forEach((resolve) => resolve({
        status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' })
    }));
    await flush();
});

/* ==================== 请求内容 ==================== */

test('run: 请求打到 /api/diag/<target>', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({ status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' }) });
    DIAG.run('weather');
    await tick();
    assert.equal(fetchCalls[0].url, '/api/diag/weather');
    assert.equal(fetchCalls[0].opts.method, 'POST');
});

test('run: 物联网测试会先保存配置（否则拿旧参数去连）', async () => {
    // 注意：必须在 reset() 之后设置 saveConfig。reset() 会排空上一轮的微任务，
    // 若先设 saveConfig，它可能在排空过程中被上一轮遗留的 then 链消费掉。
    await reset();
    let saved = 0;
    globalThis.saveConfig = function () { saved++; return Promise.resolve(); };
    fetchImpl = () => Promise.resolve({ status: 200, json: () => Promise.resolve({ ok: true, message: 'ok' }) });
    DIAG.run('iot');
    await tick();
    await flush();
    assert.equal(saved, 1, '点测试连接前应先落库');
    delete globalThis.saveConfig;
});

test('run: 结果用 textContent 写入，不拼 HTML', async () => {
    await reset();
    fetchImpl = () => Promise.resolve({
        status: 200,
        json: () => Promise.resolve({ ok: false, message: '<img src=x onerror=alert(1)>', detail: '' })
    });
    DIAG.run('ai');
    await flush();
    // textContent 赋值不会被解析成标签；这里断言原样保留，说明没走 innerHTML
    assert.match(els.diagAiResult.textContent, /<img src=x/);
});
