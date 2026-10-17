/* ============================================================
 * irrigation.js — 灌溉决策纯函数（前端展示用）
 * 对应说明书 3.1 / 3.2 / 3.3 节，与后端 qinghe/irrigation.py 保持同一套公式。
 *
 * 本文件不触碰 DOM，可在 Node 下直接 import 做单元测试
 * （tests/js/irrigation.test.mjs）。
 * ============================================================ */
(function (root) {
    'use strict';

    /* ---------- 常量：RORI 融合权重与量程标定（说明书 3.1~3.2） ---------- */
    var RORI = {
        W_EH: 0.35,           // 氧化还原电位风险因子权重
        W_DO: 0.35,           // 溶解氧风险因子权重
        W_WATER_SOIL: 0.30,   // 水位/土壤取大者权重
        GAMMA: 0.5,           // 水位×土壤 耦合项系数
        ADC_FULL: 4095,       // 12 位 ADC 满量程
        WATER_FULL_MM: 300,   // 水位满量程对应 mm
        EH_MAX: 300,          // Eh 上限 mV
        EH_MIN: -150,         // Eh 下限 mV
        DO_MAX: 8.0,          // DO 上限 mg/L
        DO_MIN: 0,            // DO 下限 mg/L
        WATER_DEADBAND_MM: 5, // 水位死区
        WATER_SPAN_MM: 100    // 水位风险归一化跨度
    };

    /* ---------- 常量：降雨前馈动态阈值（说明书 3.3） ---------- */
    var RAIN = {
        WEIGHTS: [1.0, 0.9, 0.7, 0.5, 0.4, 0.3], // 6 日时间衰减权重 ω_t
        H_ROOT: 200,          // 核心活动根系层厚度 mm
        LOWER_FLOOR: 45,      // 控水下限保底（防枯萎）
        UPPER_BONUS: 15,      // 蓄雨型控灌放宽上限
        UPPER_CAP: 100,       // 上限天花板
        ALPHA_LOW: 0.95,      // P6d ≤ 10 时的有效利用系数
        ALPHA_MID: 0.75,      // 10 < P6d ≤ 50
        ALPHA_HIGH: 0.45,     // P6d > 50
        ALPHA_MID_EDGE: 10,
        ALPHA_HIGH_EDGE: 50,
        RAIN_STRONG_MM: 15    // 强降雨前馈阈值
    };

    /* ---------- 常量：RORI 分级（表 3-1） ---------- */
    var LEVEL = {
        HEAVY: 70,   // RORI ≥ 70 重度厌氧
        MEDIUM: 40   // 40 ≤ RORI < 70 中度缺氧
    };

    /** 数值兜底：非有限数一律回退到默认值，避免 NaN 污染下游。 */
    function num(v, fallback) {
        var n = parseFloat(v);
        return Number.isFinite(n) ? n : (fallback === undefined ? 0 : fallback);
    }

    /** 线性夹逼到 [lo, hi]。 */
    function clamp(v, lo, hi) {
        if (!Number.isFinite(v)) v = lo;
        return Math.max(lo, Math.min(v, hi));
    }

    /**
     * RORI 多维融合计算（说明书 3.1~3.2）。
     *
     * 参数顺序与后端 `qinghe/irrigation.py: compute_rori(water_adc, soil_adc, do_mgl, eh_mv)`
     * 严格一致——第 3、4 位是「溶解氧、氧化还原电位」，不要写反，
     * 否则会把 Eh 当 DO 代入，不报错但结果错。
     *
     * @param {number} waterAdc 水位 ADC 原始值（0~4095，越大水越深）
     * @param {number} soilAdc  土壤湿度 ADC 原始值（0~4095，越大越干）
     * @param {number} [doVal]  根区溶解氧 mg/L（0~8）
     * @param {number} [ehMv]   根区氧化还原电位 mV（-150~300）
     * @returns {number} RORI 指数 0~100
     */
    function computeRori(waterAdc, soilAdc, doVal, ehMv) {
        var wAdc = clamp(num(waterAdc, 0), 0, RORI.ADC_FULL);
        var sAdc = clamp(num(soilAdc, 0), 0, RORI.ADC_FULL);
        var ehV = clamp(num(ehMv, 0), RORI.EH_MIN, RORI.EH_MAX);
        var doV = clamp(num(doVal, 0), RORI.DO_MIN, RORI.DO_MAX);

        // 原始 ADC -> 物理量
        var waterMm = clamp(wAdc / RORI.ADC_FULL * RORI.WATER_FULL_MM, 0, RORI.WATER_FULL_MM);
        var soilPct = clamp((RORI.ADC_FULL - sAdc) / RORI.ADC_FULL * 100, 0, 100);

        // 3.1.1 氧化还原电位风险因子
        var sEh = clamp((RORI.EH_MAX - ehV) / (RORI.EH_MAX - RORI.EH_MIN), 0, 1);
        // 3.1.2 溶解氧风险因子
        var sDo = clamp((RORI.DO_MAX - doV) / (RORI.DO_MAX - RORI.DO_MIN), 0, 1);
        // 3.1.3 水位风险（>5mm 才开始计风险）
        var riskWater = waterMm > RORI.WATER_DEADBAND_MM
            ? clamp((waterMm - RORI.WATER_DEADBAND_MM) / RORI.WATER_SPAN_MM, 0, 1)
            : 0;
        // 3.1.3 土壤风险：越湿润风险越高
        var riskSoil = clamp(soilPct / 100, 0, 1);

        // 3.2 多维融合
        var pRisk = RORI.W_EH * sEh + RORI.W_DO * sDo
            + RORI.W_WATER_SOIL * Math.max(riskWater, riskSoil)
            + RORI.GAMMA * riskWater * riskSoil;
        return clamp(pRisk, 0, 1) * 100;
    }

    /**
     * RORI 分级（表 3-1）。
     * @param {number} rori
     * @returns {{code:number,name:string,strategy:string}} code: 0 安全 / 1 中度 / 2 重度
     */
    function classifyRori(rori) {
        var v = num(rori, 0);
        if (v >= LEVEL.HEAVY) return { code: 2, name: '重度厌氧', strategy: '重度厌氧预警，加气机全满载强制增氧' };
        if (v >= LEVEL.MEDIUM) return { code: 1, name: '中度缺氧', strategy: '根区微量缺氧，周期性脉冲加气补氧' };
        return { code: 0, name: '安全运行', strategy: '根区有氧环境优良，加气机低耗待机' };
    }

    /**
     * 降雨前馈动态阈值（说明书 3.3）。
     * P6d = Σ(t=1..6) ω_t·P_t，按分段定界取有效利用系数 α。
     * @param {Array<{precip:number|string}>} forecast 6 日预报（不足 6 条按实际条数累加）
     * @param {number} baseLower 基础土壤湿度下限 %
     * @param {number} baseUpper 基础土壤湿度上限 %
     * @returns {{P6d:number,alpha:number,effLower:number,effUpper:number,
     *            baseLower:number,baseUpper:number,hasForecast:boolean,rainComing:boolean}}
     */
    function computeDynamicThreshold(forecast, baseLower, baseUpper) {
        var fc = Array.isArray(forecast) ? forecast : [];
        var lo = num(baseLower, 40);
        var hi = num(baseUpper, 80);
        var P6d = 0;
        for (var i = 0; i < fc.length && i < RAIN.WEIGHTS.length; i++) {
            var p = fc[i] && fc[i].precip;
            P6d += RAIN.WEIGHTS[i] * num(p, 0);
        }
        P6d = Math.max(0, P6d);

        // 分段定界：α 随降雨量增大而下降（雨越多，天然降雨替代灌溉的比例越高）
        var alpha = P6d <= RAIN.ALPHA_MID_EDGE ? RAIN.ALPHA_LOW
            : (P6d <= RAIN.ALPHA_HIGH_EDGE ? RAIN.ALPHA_MID : RAIN.ALPHA_HIGH);

        // 前馈控水等雨：预测有雨则下调灌溉触发下限（限位 45% 防枯萎保底）
        var effLower = Math.max(RAIN.LOWER_FLOOR, lo - (alpha * P6d / RAIN.H_ROOT) * 100);
        // 蓄雨型控灌：强降雨前馈放宽蓄水上限
        var effUpper = P6d >= RAIN.RAIN_STRONG_MM
            ? Math.min(RAIN.UPPER_CAP, hi + RAIN.UPPER_BONUS)
            : hi;

        return {
            P6d: P6d,
            alpha: alpha,
            effLower: effLower,
            effUpper: effUpper,
            baseLower: lo,
            baseUpper: hi,
            hasForecast: fc.length > 0,
            rainComing: P6d > 0
        };
    }

    var api = {
        RORI: RORI,
        RAIN: RAIN,
        LEVEL: LEVEL,
        clamp: clamp,
        num: num,
        computeRori: computeRori,
        classifyRori: classifyRori,
        computeDynamicThreshold: computeDynamicThreshold
    };

    root.QH_IRRIGATION = api;
    // 浏览器全局：供 onclick / 其它脚本直接调用，保持拆分前行为一致
    root.computeRori = computeRori;
    root.classifyRori = classifyRori;

    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
