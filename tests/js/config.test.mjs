/* ============================================================
 * config.test.mjs — 阈值双滑杆「已选区间」纯函数单元测试
 * 运行：node --test "tests/js"
 *
 * 被测模块：static/js/config.js 的 dualRangeGeometry(lower, upper, min, max)
 *   把两个滑块值换算成轨道上的百分比（left/width），供 .dual-range-fill 定位。
 *   纯函数、无 DOM 依赖，因此可在 node 下直接单测。
 * ============================================================ */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

// config.js 是浏览器 IIFE：这里给最小 DOM 桩，只为让脚本体跑完并导出纯函数
globalThis.document = globalThis.document || {
    getElementById: () => null,
    createElement: () => ({ style: {}, appendChild() {}, querySelector: () => null }),
    createDocumentFragment: () => ({ appendChild() {} }),
    addEventListener() {}
};
globalThis.QH = globalThis.QH || {
    $: () => null, setText() {}, setStyle() {}, toggleClass() {}, closeModal() {}
};
globalThis.S = globalThis.S || { config: {}, manualMode: false };
globalThis.updateThresholdFusionHint = globalThis.updateThresholdFusionHint || function () {};

const CFG = require(path.resolve(__dirname, '../../static/js/config.js'));
const { dualRangeGeometry } = CFG;

test('dualRangeGeometry 被导出到 QH_CONFIG 与模块导出', () => {
    assert.equal(typeof dualRangeGeometry, 'function');
    assert.equal(typeof globalThis.QH_CONFIG.dualRangeGeometry, 'function');
});

test('dualRangeGeometry 湿度阈值默认 40~80 / 量程 0~100', () => {
    const geo = dualRangeGeometry(40, 80, 0, 100);
    assert.equal(geo.left, 40);
    assert.equal(geo.width, 40);
});

test('dualRangeGeometry 水位阈值默认 30~150 / 量程 0~300', () => {
    const geo = dualRangeGeometry(30, 150, 0, 300);
    assert.equal(geo.left, 10);
    assert.equal(geo.width, 40);
});

test('dualRangeGeometry 支持字符串输入（input.value 永远是字符串）', () => {
    const geo = dualRangeGeometry('30', '150', '0', '300');
    assert.equal(geo.left, 10);
    assert.equal(geo.width, 40);
});

test('dualRangeGeometry 两端闭合：0~满量程铺满整条轨道', () => {
    const geo = dualRangeGeometry(0, 300, 0, 300);
    assert.equal(geo.left, 0);
    assert.equal(geo.width, 100);
});

test('dualRangeGeometry 单点区间宽度为 0，不会出现负宽度', () => {
    const geo = dualRangeGeometry(50, 50, 0, 100);
    assert.equal(geo.left, 50);
    assert.equal(geo.width, 0);
});

test('dualRangeGeometry 上下限颠倒时自动交换，保证 left/width 非负', () => {
    const geo = dualRangeGeometry(80, 40, 0, 100);
    assert.equal(geo.left, 40);
    assert.equal(geo.width, 40);
});

test('dualRangeGeometry 越界值按量程夹紧', () => {
    const low = dualRangeGeometry(-50, 80, 0, 100);
    assert.equal(low.left, 0);
    assert.equal(low.width, 80);
    const high = dualRangeGeometry(40, 999, 0, 100);
    assert.equal(high.left, 40);
    assert.equal(high.width, 60);
});

test('dualRangeGeometry 非法/缺失值回退到量程两端', () => {
    const geo = dualRangeGeometry('abc', undefined, 0, 100);
    assert.equal(geo.left, 0);
    assert.equal(geo.width, 100);
});

test('dualRangeGeometry 非零起点量程（min≠0）按比例换算', () => {
    const geo = dualRangeGeometry(25, 75, 25, 75);
    assert.equal(geo.left, 0);
    assert.equal(geo.width, 100);
});

test('dualRangeGeometry 量程非法（max<=min）不产生 NaN/Infinity', () => {
    const geo = dualRangeGeometry(10, 20, 100, 0);
    assert.ok(Number.isFinite(geo.left));
    assert.ok(Number.isFinite(geo.width));
    assert.ok(geo.left >= 0 && geo.width >= 0);
});
