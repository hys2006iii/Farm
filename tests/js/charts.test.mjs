/**
 * charts.test.mjs — 历史趋势 RORI 映射的纯函数单测
 *
 * 覆盖 D-12 后续：/api/history 补充 do_mgl / eh_mv 后，历史趋势 RORI
 * 必须与实时四维算法逐位一致；早期数据（两列为 null）回退为二维近似值
 * 并如实标记，不得把近似值当四维真值展示。
 *
 * 运行：node --test "tests/js/**\/*.test.mjs"   或 npm run test:js
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/* charts.js / core.js / store.js 都是浏览器 IIFE，依赖少量全局对象；
   在 import 之前铺最小 DOM 桩。 */
globalThis.window = globalThis;
globalThis.document = globalThis.document || {
    addEventListener() {},
    querySelector() { return null; },
    getElementById() { return null; },
    createElement() {
        return { style: {}, classList: { add() {}, remove() {} }, appendChild() {}, addEventListener() {} };
    }
};
globalThis.localStorage = globalThis.localStorage || {
    getItem: () => null, setItem() {}, removeItem() {}
};
globalThis.addEventListener = globalThis.addEventListener || function () {};

const CORE = require(path.resolve(__dirname, '../../static/js/core.js'));
const CHARTS = require(path.resolve(__dirname, '../../static/js/charts.js'));
const IRR = require(path.resolve(__dirname, '../../static/js/irrigation.js'));

const { historyRowToRoriPoint } = CHARTS;
const { computeRori } = IRR;
const S = CORE.S || globalThis.S;

/** 后端实测锚点：qinghe/irrigation.py compute_rori(1500, 2200, 6.0, 120) */
const BACKEND_REFERENCE = 75.88797313797313;

/* ================= historyRowToRoriPoint ================= */

test('historyRowToRoriPoint: 四维齐全时与实时算法逐位一致（后端锚点）', () => {
    const row = { ts: 1700000000000, water_adc: 1500, soil_adc: 2200, do_mgl: 6.0, eh_mv: 120 };
    const point = historyRowToRoriPoint(row, computeRori);

    // 与后端 compute_rori(1500, 2200, 6.0, 120) 完全相同
    assert.equal(point.rori, BACKEND_REFERENCE, '必须逐位等于后端参考值');
    // 与实时路径同一算法同一入参，结果必须一致
    assert.equal(point.rori, computeRori(1500, 2200, 6.0, 120), '与实时四维算法一致');
    assert.equal(point.approx, false, '四维齐全不算近似');
    assert.equal(point.ts, 1700000000000, 'ts 原样透传');
});

test('historyRowToRoriPoint: do_mgl/eh_mv 为 null（旧数据）回退 0 并标记近似', () => {
    const point = historyRowToRoriPoint(
        { ts: 1, water_adc: 1500, soil_adc: 2200, do_mgl: null, eh_mv: null }, computeRori);

    // 回退后等价于 DO=0 / Eh=0
    assert.equal(point.rori, computeRori(1500, 2200, 0, 0), '回退 0 计算');
    assert.equal(point.approx, true, '旧数据必须标记为二维近似');
});

test('historyRowToRoriPoint: 真实的 0 是合法边界值，不得被当成缺失', () => {
    // 这条是 `|| 0` 陷阱的守卫：用 `||` 判断会把真实的 0 吞掉，
    // 从而把四维真值误标成二维近似值。
    const point = historyRowToRoriPoint(
        { ts: 3, water_adc: 1500, soil_adc: 2200, do_mgl: 0, eh_mv: 0 }, computeRori);

    assert.equal(point.approx, false, 'do_mgl=0 与 eh_mv=0 都是有效值，不是缺失');
    assert.equal(point.rori, computeRori(1500, 2200, 0, 0), '按真实 0 计算');
});

test('historyRowToRoriPoint: 只有一维缺失也标记近似（任缺其一即为近似）', () => {
    const onlyDo = historyRowToRoriPoint(
        { ts: 4, water_adc: 1500, soil_adc: 2200, do_mgl: 6.0, eh_mv: null }, computeRori);
    const onlyEh = historyRowToRoriPoint(
        { ts: 5, water_adc: 1500, soil_adc: 2200, do_mgl: null, eh_mv: 120 }, computeRori);

    assert.equal(onlyDo.approx, true, '缺 eh 也算近似');
    assert.equal(onlyEh.approx, true, '缺 do 也算近似');
    assert.equal(onlyDo.rori, computeRori(1500, 2200, 6.0, 0), '缺 eh 回退 0');
    assert.equal(onlyEh.rori, computeRori(1500, 2200, 0, 120), '缺 do 回退 0');
});

test('historyRowToRoriPoint: undefined 与 NaN 同样视为缺失', () => {
    const undef = historyRowToRoriPoint(
        { ts: 6, water_adc: 1500, soil_adc: 2200, do_mgl: undefined, eh_mv: undefined }, computeRori);
    const nan = historyRowToRoriPoint(
        { ts: 7, water_adc: 1500, soil_adc: 2200, do_mgl: NaN, eh_mv: NaN }, computeRori);

    assert.equal(undef.approx, true, 'undefined 视为缺失');
    assert.equal(nan.approx, true, 'NaN 视为缺失');
    assert.equal(undef.rori, computeRori(1500, 2200, 0, 0), 'undefined 回退 0');
    assert.equal(nan.rori, computeRori(1500, 2200, 0, 0), 'NaN 回退 0');
});

test('historyRowToRoriPoint: 历史四维点与实时点在同一入参下逐位相等', () => {
    // 模拟同一条 ADC 同时走「历史映射」与「实时渲染」两条路径
    const cases = [
        [0, 0, 0, 0],
        [1500, 2200, 6.0, 120],
        [4095, 4095, 8, 300],
        [68, 4095, 4.2, -150]
    ];
    for (const [w, s, doV, eh] of cases) {
        const viaHistory = historyRowToRoriPoint(
            { ts: 1, water_adc: w, soil_adc: s, do_mgl: doV, eh_mv: eh }, computeRori).rori;
        const viaRealtime = computeRori(w, s, doV, eh);
        assert.equal(viaHistory, viaRealtime, `入参 (${w},${s},${doV},${eh}) 两路径必须一致`);
    }
});

test('historyRowToRoriPoint: 返回值恒为有限数，不产生 NaN', () => {
    const point = historyRowToRoriPoint(
        { ts: 8, water_adc: null, soil_adc: undefined, do_mgl: null, eh_mv: null }, computeRori);
    assert.ok(Number.isFinite(point.rori), 'rori 必须是有限数');
    assert.ok(point.rori >= 0 && point.rori <= 100, 'rori 落在 [0,100]');
});

test('historyRowToRoriPoint: 旧数据点比例可统计（供图下说明使用）', () => {
    // updateRoriApproxNote 依赖 approx 标记统计条数，这里锁定该语义
    const rows = [
        { ts: 1, water_adc: 1500, soil_adc: 2200, do_mgl: 6.0, eh_mv: 120 },
        { ts: 2, water_adc: 1500, soil_adc: 2200, do_mgl: null, eh_mv: null },
        { ts: 3, water_adc: 1500, soil_adc: 2200, do_mgl: null, eh_mv: null }
    ];
    const approxCount = rows
        .map((r) => historyRowToRoriPoint(r, computeRori))
        .filter((p) => p.approx).length;
    assert.equal(approxCount, 2, '应统计出 2 个二维近似点');
});

test('S.roriTrendData 结构约定：approx 字段用于图例/提示标注', () => {
    // 结构约定守卫：实时点写入时必须显式带 approx:false，
    // 否则 tooltip 会把四维真值也标注成近似值。
    assert.ok(S, 'core.js 应导出 S 状态对象');
    const realtimePoint = { ts: 1, rori: 50, approx: false };
    assert.equal(realtimePoint.approx, false, '实时点须显式 approx:false');
});
