/**
 * farm.test.mjs — 多地块前端纯函数单测（圈地面积 / 面积文案）
 *
 * 这两个函数决定「系统设置 → 地块管理」里显示的面积数字，算错了会直接影响
 * 节水减碳估算，所以单独锁住。
 *
 * 运行：node --test "tests/js/**\/*.test.mjs"
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/* farm.js 是浏览器 IIFE：铺最小 DOM 桩，并让 readyState 停在 loading，
   这样 init() 不会执行（不会去发 fetch 请求），只导出 QH_FARM 供测试调用。 */
globalThis.window = globalThis;
globalThis.document = {
    readyState: 'loading',
    addEventListener() {},
    querySelector() { return null; },
    getElementById() { return null; },
    createElement() {
        return { style: {}, classList: { add() {}, remove() {} }, appendChild() {}, addEventListener() {} };
    }
};
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.addEventListener = function () {};

const FARM = require(path.resolve(__dirname, '../../static/js/farm.js'));
// 浏览器 IIFE 把接口挂在 globalThis.QH_FARM 上，require 的返回值是空对象
const API = globalThis.QH_FARM || FARM;
const { polygonArea, areaText } = API;

/** 广州附近 1e-3 度见方的四边形（约 111m × 102m） */
const SQUARE = [
    [23.1290, 113.2640],
    [23.1290, 113.2650],
    [23.1300, 113.2650],
    [23.1300, 113.2640],
];

test('polygonArea: 0.001° 见方 ≈ 1.1 万平方米（±2%）', () => {
    const area = polygonArea(SQUARE);
    // 独立算一遍参考值：经向 111320*cos(lat)*0.001，纬向 111132*0.001
    const lat = (23.1295 * Math.PI) / 180;
    const expected = 111320 * Math.cos(lat) * 0.001 * 111132 * 0.001;
    assert.ok(Math.abs(area - expected) / expected < 0.02,
        `面积偏差过大: got ${area}, expected ~${expected}`);
});

test('polygonArea: 顶点顺序不影响结果（顺/逆时针同面积）', () => {
    const clockwise = [SQUARE[0], SQUARE[3], SQUARE[2], SQUARE[1]];
    assert.ok(Math.abs(polygonArea(SQUARE) - polygonArea(clockwise)) < 1e-6);
});

test('polygonArea: 点不足 3 个或非数组返回 0', () => {
    assert.equal(polygonArea([]), 0);
    assert.equal(polygonArea([[23, 113], [23, 114]]), 0);
    assert.equal(polygonArea(null), 0);
    assert.equal(polygonArea(undefined), 0);
});

test('polygonArea: 大田块面积合理（0.01° 见方 ≈ 113 万平方米）', () => {
    const big = [
        [23.1000, 113.2000],
        [23.1000, 113.2100],
        [23.1100, 113.2100],
        [23.1100, 113.2000],
    ];
    const area = polygonArea(big);
    assert.ok(area > 1000000 && area < 1300000, '面积应在 100~130 万 m² 之间，实际 ' + area);
});

test('areaText: 未圈地显示占位文案', () => {
    assert.equal(areaText(0), '未圈地');
    assert.equal(areaText(null), '未圈地');
    assert.equal(areaText(-5), '未圈地');
});

test('areaText: 小于 1 万平米显示 m² 与亩', () => {
    const text = areaText(6667);
    assert.match(text, /6667 m²/);
    assert.match(text, /亩/);
    // 6667 m² ≈ 10 亩（1 亩 = 666.7 m²）
    assert.match(text, /约 10\.00 亩/);
});

test('areaText: 大于 1 万平米切换为公顷', () => {
    assert.match(areaText(20000), /2\.00 公顷/);
    assert.match(areaText(123456), /12\.35 公顷/);
});
