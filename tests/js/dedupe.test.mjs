/**
 * dedupe.test.mjs — 运行日志与告警的「重复消息抑制」纯函数单测
 *
 * 背景：设备抖动或自动调控反复触发时，`[自动] 水位 29.8mm < 下限 30mm…`
 * 这类消息会在极短时间内刷满日志区/告警区，并把同一条 webhook 推很多次。
 * 两个模块各自提供了一套指纹 + 冷却：
 *   - app.js      : logFingerprint / shouldRecordLog（LOG_COOLDOWN_MS）
 *   - realtime.js : alertFingerprint / shouldEmitAlert（ALERT_COOLDOWN_MS + ALERT_MIN_GAP_MS）
 *
 * 这两个文件都是浏览器 IIFE，末尾有 `module.exports` 出口，node 下可直接 require。
 *
 * 运行：node --test "tests/js/**\/*.test.mjs"
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

/* 两个脚本在浏览器里依赖 core.js 挂的全局；node 下先铺最小桩，
   并让 document.readyState 停在 loading，避免 init() 真的去发请求。 */
globalThis.window = globalThis;
globalThis.document = {
    readyState: 'loading',
    addEventListener() {},
    getElementById() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() {
        return { style: {}, classList: { add() {}, remove() {}, toggle() {} }, appendChild() {}, addEventListener() {} };
    }
};
globalThis.addEventListener = function () {};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.QH = {
    $: () => null, setText() {}, toast() {}, registerTask() {},
    enqueueFlag() {}, enqueueField() {}, enqueuePump() {}, enqueueSlider() {},
    pad2: (n) => String(n).padStart(2, '0')
};
globalThis.S = { alertCoolDown: {}, logCoolDown: {} };
globalThis.QH_STORE = { pushLog: () => ({}), pushAlert: () => ({}), getLogs: () => [], getAlerts: () => [] };

const APP = require('../../static/js/app.js');
const RT = require('../../static/js/realtime.js');

/* ==================== 日志：指纹 ==================== */

test('logFingerprint: 数值不同但事实相同 -> 同一指纹', () => {
    const a = APP.logFingerprint('[自动] 水位 29.8mm < 下限 30mm，自动开启水泵灌水');
    const b = APP.logFingerprint('[自动] 水位 30.1mm < 下限 30mm，自动开启水泵灌水');
    assert.equal(a, b, '阈值附近抖动应视为同一条日志');
});

test('logFingerprint: 不同事实 -> 不同指纹', () => {
    const water = APP.logFingerprint('[自动] 水位 29.8mm < 下限 30mm，自动开启水泵灌水');
    const air = APP.logFingerprint('[自动] RORI 72 重度厌氧，气泵满载增氧');
    assert.notEqual(water, air);
});

test('logFingerprint: 空白归一化（多余空格/换行不产生新指纹）', () => {
    assert.equal(
        APP.logFingerprint('  系统已启动，   正在连接云平台...  '),
        APP.logFingerprint('系统已启动， 正在连接云平台...')
    );
});

test('logFingerprint: 空值安全', () => {
    assert.equal(APP.logFingerprint(null), '');
    assert.equal(APP.logFingerprint(undefined), '');
    assert.equal(APP.logFingerprint(''), '');
});

/* ==================== 日志：冷却 ==================== */

test('shouldRecordLog: 冷却窗口内重复内容被抑制，窗口外放行', () => {
    const table = {};
    const now = 1_000_000;
    assert.equal(APP.shouldRecordLog('水位 29.8mm 偏低，开启水泵', now, table), true);
    // 30s 内、数值抖动的同一条事实：抑制
    assert.equal(APP.shouldRecordLog('水位 29.9mm 偏低，开启水泵', now + 5_000, table), false);
    assert.equal(APP.shouldRecordLog('水位 30.1mm 偏低，开启水泵', now + 29_999, table), false);
    // 超过冷却窗口：放行
    assert.equal(APP.shouldRecordLog('水位 30.2mm 偏低，开启水泵', now + APP.LOG_COOLDOWN_MS, table), true);
});

test('shouldRecordLog: 不同事实互不影响', () => {
    const table = {};
    const now = 2_000_000;
    assert.equal(APP.shouldRecordLog('云服务连接成功', now, table), true);
    assert.equal(APP.shouldRecordLog('服务器断开', now + 100, table), true);
});

test('shouldRecordLog: 空正文不记录', () => {
    assert.equal(APP.shouldRecordLog('', 1, {}), false);
    assert.equal(APP.shouldRecordLog(null, 1, {}), false);
});

test('LOG_COOLDOWN_MS: 冷却窗口为正数且不短于 5 秒', () => {
    assert.ok(APP.LOG_COOLDOWN_MS >= 5000, '冷却窗口过短挡不住刷屏');
});

/* ==================== 告警：指纹 ==================== */

test('alertFingerprint: RORI 数值抖动 -> 同一指纹', () => {
    assert.equal(
        RT.alertFingerprint('RORI 72 重度厌氧，强制增氧'),
        RT.alertFingerprint('RORI 75 重度厌氧，强制增氧')
    );
});

test('alertFingerprint: 不同告警类型 -> 不同指纹', () => {
    assert.notEqual(
        RT.alertFingerprint('水位过高 180mm > 上限 150mm，注意排水'),
        RT.alertFingerprint('土壤湿度过高 88% > 动态上限 80%，注意排湿')
    );
});

/* ==================== 告警：冷却 + 全局间隔 ==================== */

test('shouldEmitAlert: 同一指纹 60s 内只放行一次', () => {
    const table = {};
    const now = 5_000_000;
    assert.equal(RT.shouldEmitAlert('RORI 72 重度厌氧，强制增氧', now, table), true);
    assert.equal(RT.shouldEmitAlert('RORI 78 重度厌氧，强制增氧', now + 10_000, table), false);
    assert.equal(RT.shouldEmitAlert('RORI 80 重度厌氧，强制增氧', now + 59_999, table), false);
    assert.equal(RT.shouldEmitAlert('RORI 81 重度厌氧，强制增氧', now + RT.ALERT_COOLDOWN_MS, table), true);
});

test('shouldEmitAlert: 全局最小间隔挡住连环刷屏', () => {
    const table = {};
    const now = 6_000_000;
    assert.equal(RT.shouldEmitAlert('土壤湿度过低 20% 建议补灌', now, table), true);
    // 不同事实，但间隔太短：仍被挡下
    assert.equal(RT.shouldEmitAlert('水位过高 180mm 注意排水', now + 500, table), false);
    // 拉开最小间隔后放行
    assert.equal(RT.shouldEmitAlert('水位过高 180mm 注意排水', now + RT.ALERT_MIN_GAP_MS, table), true);
});

test('shouldEmitAlert: 连续 100 条相似消息只放行 1 条', () => {
    const table = {};
    const now = 7_000_000;
    let emitted = 0;
    for (let i = 0; i < 100; i++) {
        if (RT.shouldEmitAlert('土壤湿度过低 ' + (20 + i * 0.1).toFixed(1) + '% < 动态下限 40%，建议补灌', now + i * 100, table)) {
            emitted += 1;
        }
    }
    assert.equal(emitted, 1, '10 秒内 100 条相似告警应只放行 1 条');
});

test('shouldEmitAlert: 空正文不放行', () => {
    assert.equal(RT.shouldEmitAlert('', 1, {}), false);
    assert.equal(RT.shouldEmitAlert(null, 1, {}), false);
});

test('冷却常量：告警窗口不短于日志窗口，全局间隔为正', () => {
    assert.ok(RT.ALERT_COOLDOWN_MS >= 30000);
    assert.ok(RT.ALERT_MIN_GAP_MS > 0);
});
