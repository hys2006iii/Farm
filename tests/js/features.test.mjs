/**
 * features.test.mjs — 阈值预设纯函数的单测
 *
 * `threshPreset(key)`（config.js）
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

const CFG = require('../../static/js/config.js');

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

/* ==================== 预设选中态 ==================== */

/** 造一个假按钮：只实现 markThreshPreset 会用到的那点 DOM 接口。 */
function fakeButton(preset) {
    const classes = new Set();
    return {
        classes,
        getAttribute: (name) => (name === 'data-preset' ? preset : null),
        classList: {
            toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }
        }
    };
}

test('markThreshPreset: 只有被选中的那个按钮带 is-on', () => {
    const buttons = [fakeButton('water_saving'), fakeButton('standard'), fakeButton('moisture_hold')];
    const marked = CFG.markThreshPreset(buttons, 'moisture_hold');
    assert.equal(marked, 1);
    assert.equal(buttons[0].classes.has('is-on'), false);
    assert.equal(buttons[1].classes.has('is-on'), false);
    assert.equal(buttons[2].classes.has('is-on'), true);
});

test('markThreshPreset: 换选另一个模式时旧的选中态被清掉', () => {
    const buttons = [fakeButton('water_saving'), fakeButton('standard')];
    CFG.markThreshPreset(buttons, 'standard');
    assert.equal(buttons[1].classes.has('is-on'), true);
    CFG.markThreshPreset(buttons, 'water_saving');
    assert.equal(buttons[0].classes.has('is-on'), true);
    assert.equal(buttons[1].classes.has('is-on'), false, '旧选中态必须清掉，否则会同时高亮两个');
});

test('markThreshPreset: 未知键把所有按钮都置为未选中', () => {
    const buttons = [fakeButton('standard')];
    CFG.markThreshPreset(buttons, 'standard');
    assert.equal(CFG.markThreshPreset(buttons, 'no-such'), 0);
    assert.equal(buttons[0].classes.has('is-on'), false);
});

test('markThreshPreset: 传入空值不抛异常（模板未渲染时也要安全）', () => {
    assert.equal(CFG.markThreshPreset(null, 'standard'), 0);
    assert.equal(CFG.markThreshPreset(undefined, 'standard'), 0);
    assert.equal(CFG.markThreshPreset([null, undefined], 'standard'), 0);
});
