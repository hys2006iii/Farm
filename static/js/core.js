/* ============================================================
 * core.js — 全局状态 / 工具函数 / 统一 tick 调度器 / DOM 批量更新队列
 * 必须最先加载（其余脚本依赖此处的全局）。
 * ============================================================ */
(function (root) {
    'use strict';

    /* ================= 全局状态 ================= */
    var S = {
        // 传感器实时值
        currentWaterLevel: 0,    // 水位 mm
        currentSoilMoisture: 58, // 土壤湿度 %
        waterAdc: 0,             // 水位 ADC 原始值
        soilAdc: 0,              // 土壤 ADC 原始值
        doValue: 0,              // 根区溶解氧 mg/L
        ehValue: 0,              // 根区氧化还原电位 mV
        currentRori: null,       // 最近一次算得的 RORI（内存态，避免读 DOM 文本）
        // 运行状态
        manualMode: false,
        config: {},
        cloudConnected: false,
        deviceOnline: false,
        dataReceived: false,
        socket: null,
        // 图表 / 趋势
        waterChart: null, soilChart: null, roriChart: null,
        trendData: [],
        roriTrendData: [],
        chartType: 'line',
        chartDirty: false,
        // 自动调控去重标记
        alertCoolDown: {},
        pumpAutoState: '',
        airPumpAutoState: '',
        // 心跳：连续丢心跳达此上限（每 5s 一跳）即判设备离线
        heartbeatMiss: 0,
        heartbeatMissLimit: 4,
        // 天气
        forecastData: [],
        dynamicThreshold: null
    };
    root.S = S;

    /* ================= 工具函数 ================= */
    /** HTML 转义：所有拼接进 innerHTML 的外部/存储数据必须先经此函数。 */
    function esc(s) {
        return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    /** 时间戳 -> HH:MM:SS */
    function fmtTime(ts) {
        var d = new Date(ts);
        return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
    }

    /** 补零 */
    function pad2(n) { return String(n).padStart(2, '0'); }

    /** 安全取元素 */
    function $(id) { return document.getElementById(id); }

    /** 写文本：值未变化则不触碰 DOM（减少无谓重排） */
    function setText(el, text) {
        if (!el) return;
        if (el.__qhText === text) return;
        el.__qhText = text;
        el.textContent = text;
    }

    /** 写属性：值未变化则不写 */
    function setAttr(el, name, value) {
        if (!el) return;
        var key = '__qhAttr_' + name;
        if (el[key] === value) return;
        el[key] = value;
        el.setAttribute(name, value);
    }

    /** 写样式：值未变化则不写 */
    function setStyle(el, prop, value) {
        if (!el) return;
        var key = '__qhStyle_' + prop;
        if (el[key] === value) return;
        el[key] = value;
        el.style[prop] = value;
    }

    /** 切换 class：状态未变化则不写 */
    function toggleClass(el, cls, on) {
        if (!el) return;
        var key = '__qhCls_' + cls;
        if (el[key] === on) return;
        el[key] = on;
        el.classList.toggle(cls, on);
    }

    /** toast 提示（文本走 textContent，天然免疫 XSS） */
    function toast(msg, type) {
        var box = $('toastContainer');
        if (!box) return;
        var el = document.createElement('div');
        el.className = 'toast ' + (type || 'success');
        el.textContent = String(msg);
        box.appendChild(el);
        setTimeout(function () { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 3000);
        setTimeout(function () { el.remove(); }, 3400);
    }

    /* ================= 弹窗 ================= */
    function openModal(id) { var el = $(id); if (el) el.classList.remove('hidden'); }
    function closeModal(id) { var el = $(id); if (el) el.classList.add('hidden'); }

    /* ================= DOM 批量更新队列 =================
     * SocketIO 消息可能 3s 一条、多设备更高频。所有消息只入队，
     * 由统一 tick 每 500ms 合并成一次 DOM 批量更新，并做「值未变不写」比对。
     */
    var pending = {
        fields: {},   // 传感器数值：key -> 文本
        styles: {},   // 元素样式：key -> [prop, value]
        pumps: {},    // 泵状态：elId -> 原始值
        flags: {},    // 布尔状态
        sliders: {}   // 阈值滑杆：type -> value
    };

    function enqueueField(key, value) { pending.fields[key] = value; }
    function enqueueStyle(key, prop, value) { pending.styles[key] = [prop, value]; }
    function enqueuePump(elId, rawVal) { pending.pumps[elId] = rawVal; }
    function enqueueFlag(key, value) { pending.flags[key] = value; }
    function enqueueSlider(kind, type, value) { pending.sliders[kind + ':' + type] = value; }

    /** 泵状态原始值 -> 展示文本/颜色（保持拆分前判定口径） */
    function pumpPresentation(rawVal) {
        var s = String(rawVal).toLowerCase();
        var on = s === '1' || s === 'on' || s === 'true';
        return { text: on ? '运行中' : '待机关闭', color: on ? '#3B6B4A' : '#2A2A2A' };
    }

    /** 把队列里的变更一次性刷进 DOM */
    function flushDom() {
        var k, v;
        for (k in pending.fields) {
            if (Object.prototype.hasOwnProperty.call(pending.fields, k)) setText($(k), pending.fields[k]);
        }
        for (k in pending.styles) {
            if (Object.prototype.hasOwnProperty.call(pending.styles, k)) {
                v = pending.styles[k];
                setStyle($(k), v[0], v[1]);
            }
        }
        for (k in pending.pumps) {
            if (Object.prototype.hasOwnProperty.call(pending.pumps, k)) {
                var p = pumpPresentation(pending.pumps[k]);
                var el = $(k);
                setText(el, p.text);
                setStyle(el, 'color', p.color);
            }
        }
        for (k in pending.sliders) {
            if (Object.prototype.hasOwnProperty.call(pending.sliders, k)) {
                var parts = k.split(':');
                var input = $(parts[0] + (parts[1] === 'up' ? 'UpInput' : 'DownInput'));
                if (input) input.value = pending.sliders[k];
                if (parts[0] === 'humi') onHumiditySlider(parts[1]);
                else onWaterLevelSlider(parts[1]);
            }
        }
        var flags = pending.flags;
        pending = { fields: {}, styles: {}, pumps: {}, flags: {}, sliders: {} };
        if (flags.refreshStatus) refreshStatus();
        if (flags.rori) updateRori();
        if (flags.alerts) checkAlerts();
        if (flags.chart) markChartDirty();
    }

    /* ================= 统一 tick 调度器 =================
     * 替代原先分散的 setInterval（时钟 1s、心跳 10s、图表 2s 去抖）。
     * 主循环 500ms 一跳，各任务按自己的分频执行：
     *   时钟 1s / DOM 刷写 500ms / 图表 2s / 心跳 5s / 告警巡检 5s / 趋势落盘 30s
     */
    var TICK_MS = 500;
    var tasks = [];
    var tickTimer = null;

    /**
     * 注册分频任务。
     * @param {string} name 任务名
     * @param {number} everyMs 执行间隔 ms
     * @param {Function} fn 任务体
     */
    function registerTask(name, everyMs, fn) {
        tasks.push({ name: name, every: everyMs, fn: fn });
    }

    function startTicker() {
        if (tickTimer) return;
        var last = Date.now();
        var acc = {};
        tickTimer = setInterval(function () {
            var now = Date.now();
            var dt = now - last;
            last = now;
            for (var i = 0; i < tasks.length; i++) {
                var t = tasks[i];
                acc[t.name] = (acc[t.name] || 0) + dt;
                if (acc[t.name] >= t.every) {
                    acc[t.name] = 0;
                    try { t.fn(); } catch (e) { /* 单个任务异常不拖垮主循环 */ }
                }
            }
        }, TICK_MS);
    }

    function stopTicker() {
        if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
    }

    /* ================= 事件绑定（点击/键盘） ================= */
    function bindDelegates() {
        // 弹窗遮罩点击关闭：拆分前无此行为，保持一致性故不启用
        // 这里仅统一处理需要防重复提交的按钮
    }

    root.QH = {
        esc: esc, fmtTime: fmtTime, pad2: pad2, $: $,
        setText: setText, setAttr: setAttr, setStyle: setStyle, toggleClass: toggleClass,
        toast: toast, openModal: openModal, closeModal: closeModal,
        enqueueField: enqueueField, enqueueStyle: enqueueStyle,
        enqueuePump: enqueuePump, enqueueFlag: enqueueFlag, enqueueSlider: enqueueSlider,
        flushDom: flushDom, pumpPresentation: pumpPresentation,
        registerTask: registerTask, startTicker: startTicker, stopTicker: stopTicker,
        bindDelegates: bindDelegates, TICK_MS: TICK_MS
    };

    // 浏览器全局别名：模板内联 onclick 与跨脚本调用需要
    root.esc = esc;
    root.fmtTime = fmtTime;
    root.toast = toast;
    root.openModal = openModal;
    root.closeModal = closeModal;
    root.updateRori = function () { /* 由 irrigation/realtime 覆盖 */ };
    root.refreshStatus = function () { /* 由 realtime 覆盖 */ };
    root.checkAlerts = function () { /* 由 alerts 逻辑覆盖 */ };
    root.markChartDirty = function () { /* 由 charts 覆盖 */ };
    root.updateThresholdFusionHint = function () { /* 由 weather 覆盖 */ };
    root.onHumiditySlider = function () { /* 由 config 覆盖 */ };
    root.onWaterLevelSlider = function () { /* 由 config 覆盖 */ };
})(typeof globalThis !== 'undefined' ? globalThis : this);
