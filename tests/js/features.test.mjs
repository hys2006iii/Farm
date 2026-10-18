/**
 * features.test.mjs — 本轮新增两个纯函数的单测
 *
 * 1) `freshnessState(ageMs)`（realtime.js）
 *    把「距上次收到遥测的毫秒数」翻译成新鲜度状态。看板顶栏据此显示
 *    「N 秒前更新」并在数字变旧时换色 —— 与「设备是否离线」是两件事：
 *    设备可能在线但很久没上报，也可能刚上报过而 MQTT 链路显示断开。
 *
 * 2) `threshPreset(key)`（config.js）
 *    「节水优先 / 标准灌溉 / 保墒防旱」三个阈值预设。四个数字一旦写错，
 *    自动调控就会在错误的区间里开关泵，所以单独锁住。
 *
 * 运行：node --test "tests/js/**\/*.test.mjs"
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

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
    setStyle() {}, toggleClass() {}, openModal() {}, closeModal() {},
    enqueueFlag() {}, enqueueField() {}, enqueuePump() {}, enqueueSlider() {},
    pad2: (n) => String(n).padStart(2, '0')
};
globalThis.S = { alertCoolDown: {}, logCoolDown: {}, config: {}, manualMode: false };
globalThis.QH_STORE = { pushLog: () => ({}), pushAlert: () => ({}), getLogs: () => [], getAlerts: () => [] };

const RT = require('../../static/js/realtime.js');
const CFG = require('../../static/js/config.js');

/* ==================== 数据新鲜度 ==================== */

test('freshnessState: 15 秒内为 fresh', () => {
    assert.equal(RT.freshnessState(0).level, 'fresh');
    assert.equal(RT.freshnessState(3_000).level, 'fresh');
    assert.equal(RT.freshnessState(14_999).level, 'fresh');
});

test('freshnessState: 15~60 秒为 stale（画面变旧但没到不可信）', () => {
    assert.equal(RT.freshnessState(15_000).level, 'stale');
    assert.equal(RT.freshnessState(45_000).level, 'stale');
    assert.equal(RT.freshnessState(59_999).level, 'stale');
});

test('freshnessState: 60 秒及以上为 lost', () => {
    assert.equal(RT.freshnessState(60_000).level, 'lost');
    assert.equal(RT.freshnessState(3_600_000).level, 'lost');
});

test('freshnessState: 从未收到数据（null/undefined/NaN/负数）为 lost', () => {
    for (const bad of [null, undefined, NaN, -1, 'abc']) {
        const state = RT.freshnessState(bad);
        assert.equal(state.level, 'lost', String(bad));
    }
});

test('freshnessState: 秒/分/小时文案随量级切换', () => {
    assert.match(RT.freshnessState(5_000).text, /秒前更新/);
    assert.match(RT.freshnessState(90_000).text, /分钟前更新/);
    assert.match(RT.freshnessState(3_600_000).text, /小时前更新/);
});

test('freshnessState: 文案里带具体秒数，便于运维判断', () => {
    assert.match(RT.freshnessState(7_000).text, /7 秒/);
    assert.match(RT.freshnessState(120_000).text, /2 分钟/);
});

test('freshness 阈值常量：fresh < stale < 60s 判离线', () => {
    assert.ok(RT.FRESH_MS > 0 && RT.FRESH_MS < RT.STALE_MS);
    assert.equal(RT.FRESH_MS, 15000);
    assert.equal(RT.STALE_MS, 60000);
});

/* ==================== 阈值预设 ==================== */

const PRESET_KEYS = ['water_saving', 'standard', 'moisture_hold'];

test('threshPreset: 三个预设都存在且有中文名与说明', () => {
    for (const key of PRESET_KEYS) {
        const preset = CFG.threshPreset(key);
        assert.ok(preset, key);
        assert.ok(preset.name, key);
        assert.ok(preset.desc, key);
    }
});

test('threshPreset: 未知键返回 null（不抛异常）', () => {
    assert.equal(CFG.threshPreset('no-such'), null);
    assert.equal(CFG.threshPreset(''), null);
    assert.equal(CFG.threshPreset(null), null);
    assert.equal(CFG.threshPreset('toString'), null, '不能命中原型链上的键');
});

test('threshPreset: 每个预设下限都小于上限（否则滑杆联动会打架）', () => {
    for (const key of PRESET_KEYS) {
        const p = CFG.threshPreset(key);
        assert.ok(p.humi_down < p.humi_up, key + ' 湿度上下限顺序错');
        assert.ok(p.waterlevel_down < p.waterlevel_up, key + ' 水位上下限顺序错');
    }
});

test('threshPreset: 取值都落在合法量程内', () => {
    for (const key of PRESET_KEYS) {
        const p = CFG.threshPreset(key);
        assert.ok(p.humi_down >= 0 && p.humi_up <= 100, key + ' 湿度越界');
        assert.ok(p.waterlevel_down >= 0 && p.waterlevel_up <= 300, key + ' 水位越界');
    }
});

test('threshPreset: 标准灌溉与后端出厂默认一致', () => {
    // 后端 config.THRESH_DEFAULTS = 40 / 80 / 30 / 150
    const p = CFG.threshPreset('standard');
    assert.equal(p.humi_down, 40);
    assert.equal(p.humi_up, 80);
    assert.equal(p.waterlevel_down, 30);
    assert.equal(p.waterlevel_up, 150);
});

test('threshPreset: 节水优先比标准更省水（下限更高、上限更低）', () => {
    const save = CFG.threshPreset('water_saving');
    const std = CFG.threshPreset('standard');
    assert.ok(save.humi_down > std.humi_down, '节水方案应抬高湿度下限（更晚才灌）');
    assert.ok(save.waterlevel_up < std.waterlevel_up, '节水方案应压低水位上限');
});

test('threshPreset: 保墒防旱比标准更保守（下限更低、上限更高）', () => {
    const hold = CFG.threshPreset('moisture_hold');
    const std = CFG.threshPreset('standard');
    assert.ok(hold.humi_down < std.humi_down, '保墒方案应放低湿度下限');
    assert.ok(hold.humi_up > std.humi_up, '保墒方案应放宽湿度上限');
});

test('threshPreset: 返回的是副本，改它不会污染全局预设', () => {
    const first = CFG.threshPreset('standard');
    first.humi_down = -999;
    assert.equal(CFG.threshPreset('standard').humi_down, 40);
});
