/* ============================================================
 * irrigation.test.mjs — 前端灌溉决策纯函数单元测试
 * 运行：node --test tests/js   （或 npm run test:js）
 *
 * 被测模块：static/js/irrigation.js（UMD 形式，可直接 import）
 *   1) computeRori            边界：ADC=0 / 4095 / 中间值 / NaN
 *   2) classifyRori           各分级边界（0 / 39.99 / 40 / 69.99 / 70 / 100）
 *   3) computeDynamicThreshold P6d 在 0 / 10 / 50 / 100 各分段 + 无预报回退
 * ============================================================ */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const IRR = require(path.resolve(__dirname, '../../static/js/irrigation.js'));

// core.js 是浏览器 IIFE，会直接访问 document；测试里给最小桩，仅用于加载 esc 等纯工具函数
globalThis.document = globalThis.document || {
    getElementById: () => null,
    createElement: () => ({ style: {}, classList: { toggle() {} }, appendChild() {}, remove() {} }),
    createDocumentFragment: () => ({ appendChild() {} }),
    addEventListener() {}
};
globalThis.localStorage = globalThis.localStorage || {
    getItem: () => null, setItem() {}, removeItem() {}
};
globalThis.addEventListener = globalThis.addEventListener || function () {};
const CORE = require(path.resolve(__dirname, '../../static/js/core.js'));

const { computeRori, classifyRori, computeDynamicThreshold, RORI, RAIN, LEVEL } = IRR;
// core.js 是浏览器 IIFE，不导出 module.exports；esc 挂在 globalThis 上
const esc = CORE.esc || globalThis.esc;

/** 浮点近似断言 */
function near(actual, expected, eps = 1e-9, msg) {
    assert.ok(Math.abs(actual - expected) <= eps,
        `${msg || 'value'} 期望 ${expected}，实际 ${actual}`);
}

/* ======================= computeRori ======================= */

test('computeRori: 全部取最小风险（ADC=0, Eh 上限, DO 上限）-> 0', () => {
    // 水位 ADC=0 -> 0mm；土壤 ADC=0 -> 100% 湿润 -> riskSoil=1
    // Eh=300 -> sEh=0；DO=8 -> sDo=0；水位风险 0
    // pRisk = 0.30*max(0,1) + 0.5*0*1 = 0.30 -> 30
    near(computeRori(0, 0, RORI.EH_MAX, RORI.DO_MAX), 30, 1e-9, 'ADC=0');
});

test('computeRori: ADC=4095 全量程（水位满、土壤最干、Eh/DO 最低）-> 100', () => {
    // 水位 300mm -> riskWater=1；土壤 0% -> riskSoil=0；sEh=1；sDo=1
    // pRisk = 0.35 + 0.35 + 0.30*1 + 0.5*1*0 = 1.0 -> 100
    near(computeRori(4095, 4095, RORI.EH_MIN, RORI.DO_MIN), 100, 1e-9, 'ADC=4095');
});

test('computeRori: 中间值（ADC=2048 双通道）落在 0~100 之间且可复算', () => {
    const v = computeRori(2048, 2048, 100, 4);
    // 手工复算：water=2048/4095*300=150.03mm -> riskWater=(150.03-5)/100 夹逼到 1
    //          soil=(4095-2048)/4095*100=49.99% -> riskSoil=0.4999...
    //          sEh=(300-100)/450=0.4444...；sDo=(8-4)/8=0.5
    const waterMm = 2048 / RORI.ADC_FULL * RORI.WATER_FULL_MM;
    const soilPct = (RORI.ADC_FULL - 2048) / RORI.ADC_FULL * 100;
    const riskWater = Math.min((waterMm - RORI.WATER_DEADBAND_MM) / RORI.WATER_SPAN_MM, 1);
    const riskSoil = soilPct / 100;
    const sEh = (RORI.EH_MAX - 100) / (RORI.EH_MAX - RORI.EH_MIN);
    const sDo = (RORI.DO_MAX - 4) / (RORI.DO_MAX - RORI.DO_MIN);
    const expected = (RORI.W_EH * sEh + RORI.W_DO * sDo
        + RORI.W_WATER_SOIL * Math.max(riskWater, riskSoil)
        + RORI.GAMMA * riskWater * riskSoil) * 100;
    near(v, expected, 1e-9, 'ADC=2048');
    assert.ok(v >= 0 && v <= 100, 'RORI 必须落在 [0,100]');
});

test('computeRori: NaN / undefined / 非数字入参不产生 NaN，回退为有限值', () => {
    assert.ok(Number.isFinite(computeRori(NaN, NaN, NaN, NaN)), 'NaN 入参');
    assert.ok(Number.isFinite(computeRori(undefined, undefined, undefined, undefined)), 'undefined 入参');
    assert.ok(Number.isFinite(computeRori('abc', null, {}, [])), '非数字入参');
    // 缺省 eh/do 视为 0 -> 最大风险因子；water/soil ADC 视为 0
    const v = computeRori(NaN, NaN);
    near(v, computeRori(0, 0, 0, 0), 1e-9, 'NaN 等价于全 0');
});

test('computeRori: 超量程入参被夹逼，结果仍在 [0,100]', () => {
    assert.ok(computeRori(99999, -5000, 9999, -9999) <= 100);
    assert.ok(computeRori(-1, 99999, -9999, 9999) >= 0);
});

test('computeRori: 水位死区 5mm 以内不计水位风险', () => {
    // water ADC=68 -> 68/4095*300 = 4.98mm < 5mm 死区
    const deadZone = computeRori(68, 4095, RORI.EH_MAX, RORI.DO_MAX);
    near(deadZone, 0, 1e-9, '死区内水位无风险');
});

test('computeRori: DO 边界 0 / 8.0 / 超上限，风险因子夹逼到 [0,1]', () => {
    // DO=0 -> 风险因子 1（最缺氧）；DO=8 -> 0；DO>8 -> 夹逼后仍为 0
    const doZero = computeRori(0, 4095, RORI.EH_MAX, 0);
    const doFull = computeRori(0, 4095, RORI.EH_MAX, RORI.DO_MAX);
    const doOver = computeRori(0, 4095, RORI.EH_MAX, 999);
    near(doZero, RORI.W_DO * 100, 1e-9, 'DO=0');
    near(doFull, 0, 1e-9, 'DO=8.0');
    near(doOver, doFull, 1e-9, 'DO>8 与 DO=8 等价');
});

test('computeRori: Eh 边界 -150 / 300，风险因子夹逼到 [0,1]', () => {
    const ehMin = computeRori(0, 4095, RORI.EH_MIN, RORI.DO_MAX);
    const ehMax = computeRori(0, 4095, RORI.EH_MAX, RORI.DO_MAX);
    const ehUnder = computeRori(0, 4095, -9999, RORI.DO_MAX);
    near(ehMin, RORI.W_EH * 100, 1e-9, 'Eh=-150 满风险');
    near(ehMax, 0, 1e-9, 'Eh=300 零风险');
    near(ehUnder, ehMin, 1e-9, 'Eh 低于下限与下限等价');
});

/* ======================= classifyRori ======================= */

test('classifyRori: 分级边界 0 / 39.99 / 40 / 69.99 / 70 / 100', () => {
    assert.equal(classifyRori(0).code, 0, 'RORI=0 安全');
    assert.equal(classifyRori(39.99).code, 0, 'RORI=39.99 安全');
    assert.equal(classifyRori(LEVEL.MEDIUM).code, 1, 'RORI=40 中度');
    assert.equal(classifyRori(69.99).code, 1, 'RORI=69.99 中度');
    assert.equal(classifyRori(LEVEL.HEAVY).code, 2, 'RORI=70 重度');
    assert.equal(classifyRori(100).code, 2, 'RORI=100 重度');
});

test('classifyRori: 返回等级名与策略文案', () => {
    assert.equal(classifyRori(10).name, '安全运行');
    assert.equal(classifyRori(50).name, '中度缺氧');
    assert.equal(classifyRori(90).name, '重度厌氧');
    assert.ok(classifyRori(10).strategy.length > 0);
    assert.ok(classifyRori(50).strategy.length > 0);
    assert.ok(classifyRori(90).strategy.length > 0);
});

test('classifyRori: NaN / 负值 / 非数字回退到安全级', () => {
    assert.equal(classifyRori(NaN).code, 0);
    assert.equal(classifyRori(-10).code, 0);
    assert.equal(classifyRori(undefined).code, 0);
    assert.equal(classifyRori('x').code, 0);
});

/* ================ computeDynamicThreshold ================ */

test('computeDynamicThreshold: 无预报数据回退基础阈值，P6d=0 / alpha=0.95', () => {
    const dt = computeDynamicThreshold([], 40, 80);
    assert.equal(dt.hasForecast, false);
    assert.equal(dt.rainComing, false);
    assert.equal(dt.P6d, 0);
    assert.equal(dt.alpha, RAIN.ALPHA_LOW);
    assert.equal(dt.effLower, 45, '下限有 45% 保底，基础 40% 也会被抬到 45%');
    assert.equal(dt.effUpper, 80);
    assert.equal(dt.baseLower, 40);
    assert.equal(dt.baseUpper, 80);
});

test('computeDynamicThreshold: forecast 非数组（null/undefined）同样回退', () => {
    [null, undefined, 'nope', 0].forEach((bad) => {
        const dt = computeDynamicThreshold(bad, 40, 80);
        assert.equal(dt.hasForecast, false);
        assert.equal(dt.P6d, 0);
        assert.equal(dt.effLower, 45, '回退后仍受 45% 保底约束');
        assert.equal(dt.effUpper, 80);
    });
});

test('computeDynamicThreshold: P6d=0 分段（alpha=0.95）不下调有效下限', () => {
    const dt = computeDynamicThreshold([{ precip: 0 }, { precip: 0 }], 40, 80);
    assert.equal(dt.P6d, 0);
    assert.equal(dt.alpha, RAIN.ALPHA_LOW);
    assert.equal(dt.effLower, 45, '基础 40% -> 保底 45%');
    assert.equal(dt.effUpper, 80);
    assert.equal(dt.rainComing, false);
});

test('computeDynamicThreshold: P6d 恰好 =10 走 alpha=0.95 分段（闭区间上界）', () => {
    // 只给第一日权重 1.0 -> P6d = 10
    const dt = computeDynamicThreshold([{ precip: 10 }], 40, 80);
    near(dt.P6d, 10, 1e-9);
    assert.equal(dt.alpha, RAIN.ALPHA_LOW);
    // effLower = max(45, 40 - 0.95*10/200*100) = max(45, 35.25) = 45
    near(dt.effLower, 45, 1e-9);
    assert.equal(dt.effUpper, 80, 'P6d<15 不放宽上限');
});

test('computeDynamicThreshold: P6d 恰好 =50 走 alpha=0.75 分段（闭区间上界）', () => {
    const dt = computeDynamicThreshold([{ precip: 50 }], 40, 80);
    near(dt.P6d, 50, 1e-9);
    assert.equal(dt.alpha, RAIN.ALPHA_MID);
    near(dt.effLower, 45, 1e-9, '下限被 45% 保底夹住');
    assert.equal(dt.effUpper, 95, 'P6d>=15 放宽上限 80+15=95');
});

test('computeDynamicThreshold: P6d=100 走 alpha=0.45 分段，上限放宽到 95%', () => {
    const dt = computeDynamicThreshold([{ precip: 100 }], 40, 80);
    near(dt.P6d, 100, 1e-9);
    assert.equal(dt.alpha, RAIN.ALPHA_HIGH);
    near(dt.effLower, 45, 1e-9);
    assert.equal(dt.effUpper, 95, '上限 80 + 放宽 15 = 95，未触顶 100');
});

test('computeDynamicThreshold: 上限放宽后不超过 100% 天花板', () => {
    const dt = computeDynamicThreshold([{ precip: 100 }], 40, 95);
    assert.equal(dt.effUpper, RAIN.UPPER_CAP, '95 + 15 应被夹到 100');
});

test('computeDynamicThreshold: 分段切换点在 10 与 50 之间切换 alpha', () => {
    near(computeDynamicThreshold([{ precip: 10 }], 40, 80).alpha, RAIN.ALPHA_LOW);
    near(computeDynamicThreshold([{ precip: 10.01 }], 40, 80).alpha, RAIN.ALPHA_MID);
    near(computeDynamicThreshold([{ precip: 50 }], 40, 80).alpha, RAIN.ALPHA_MID);
    near(computeDynamicThreshold([{ precip: 50.01 }], 40, 80).alpha, RAIN.ALPHA_HIGH);
});

test('computeDynamicThreshold: 6 日衰减权重累加（ω=[1,0.9,0.7,0.5,0.4,0.3]）', () => {
    const days = [10, 10, 10, 10, 10, 10].map((p) => ({ precip: p }));
    const dt = computeDynamicThreshold(days, 40, 80);
    near(dt.P6d, 10 * (1.0 + 0.9 + 0.7 + 0.5 + 0.4 + 0.3), 1e-9);
    assert.equal(dt.hasForecast, true);
});

test('computeDynamicThreshold: 超过 6 条预报只取前 6 条', () => {
    const many = new Array(10).fill({ precip: 10 });
    const six = new Array(6).fill({ precip: 10 });
    near(computeDynamicThreshold(many, 40, 80).P6d, computeDynamicThreshold(six, 40, 80).P6d, 1e-9);
});

test('computeDynamicThreshold: 下限保底 45%（大暴雨也不低于 45%）', () => {
    const dt = computeDynamicThreshold([{ precip: 500 }], 40, 80);
    assert.ok(dt.effLower >= RAIN.LOWER_FLOOR, '下限不得低于保底值');
    assert.equal(dt.rainComing, true);
});

test('computeDynamicThreshold: precip 非法值按 0 计，不产生 NaN', () => {
    const dt = computeDynamicThreshold([{ precip: 'x' }, {}, { precip: null }], 40, 80);
    assert.ok(Number.isFinite(dt.P6d));
    assert.equal(dt.P6d, 0);
    assert.equal(dt.hasForecast, true, '有数组即为有预报');
});

test('computeDynamicThreshold: 基础阈值缺省回退 40 / 80', () => {
    const dt = computeDynamicThreshold([], undefined, undefined);
    assert.equal(dt.baseLower, 40);
    assert.equal(dt.baseUpper, 80);
    const dt2 = computeDynamicThreshold([], NaN, 'x');
    assert.equal(dt2.baseLower, 40);
    assert.equal(dt2.baseUpper, 80);
});

/* =========================== esc() =========================== */

test('esc: 转义 <script> 标签，阻断 XSS 注入', () => {
    const out = esc('<script>alert(1)</script>');
    assert.equal(out, '&lt;script&gt;alert(1)&lt;/script&gt;');
    assert.ok(!out.includes('<'), '不得残留裸尖括号');
});

test('esc: 转义单双引号与 & 号', () => {
    assert.equal(esc('a"b'), 'a&quot;b');
    assert.equal(esc("a'b"), 'a&#39;b');
    assert.equal(esc('a&b'), 'a&amp;b');
    assert.equal(esc('<img src=x onerror="alert(1)">'),
        '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
});

test('esc: null / undefined / 数字安全降级为空串或原样字符串', () => {
    assert.equal(esc(null), '');
    assert.equal(esc(undefined), '');
    assert.equal(esc(0), '0');
    assert.equal(esc(12.5), '12.5');
});

test('esc: 中文字符与普通文本不被改动', () => {
    assert.equal(esc('土壤湿度过低 58%'), '土壤湿度过低 58%');
});
