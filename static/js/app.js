/* ============================================================
 * app.js — 启动引导：初始化顺序 / 定时器注册 / 页面卸载兜底
 * 依赖：core → store → charts → irrigation → realtime → config → ai → weather
 * 所有 DOM 操作在 DOMContentLoaded 之后执行（模板用 defer 引入本文件）。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var S = root.S;
    var STORE = root.QH_STORE;
    var REALTIME = root.QH_REALTIME;
    var CHARTS = root.QH_CHARTS;
    var CONFIG = root.QH_CONFIG;
    var WEATHER = root.QH_WEATHER;

    /* ================= 时钟 ================= */
    /** 顶栏时钟：日期与时间分两个节点写入（模板 id：sysDate / sysTime） */
    function updateClock() {
        var now = new Date();
        var week = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'][now.getDay()];
        var dateText = now.getFullYear() + '-' + QH.pad2(now.getMonth() + 1) + '-' + QH.pad2(now.getDate()) + ' ' + week;
        var timeText = QH.pad2(now.getHours()) + ':' + QH.pad2(now.getMinutes()) + ':' + QH.pad2(now.getSeconds());
        QH.setText(QH.$('sysDate'), dateText);
        QH.setText(QH.$('sysTime'), timeText);
    }

    /* ================= 运行日志 / 告警列表（增量渲染） ================= */
    /**
     * 渲染运行日志。首次全量，之后增量 prepend（最多 LOG_RENDER_MAX 条），
     * 避免每次全量重建 DOM。
     */
    var LOG_RENDER_MAX = 60;
    function renderLogs() {
        var listEl = QH.$('logList');
        if (!listEl) return;
        var logs = STORE.getLogs();
        var slice = logs.slice(0, LOG_RENDER_MAX);
        if (!listEl.__qhInit) {
            listEl.textContent = '';
            listEl.__qhInit = true;
            slice.forEach(function (l) { listEl.appendChild(makeLogNode(l)); });
            return;
        }
        // 增量：只插入比当前首节点更新的日志（按 ts 判定），已存在则跳过
        var firstTs = listEl.__qhFirstTs || 0;
        var fresh = slice.filter(function (l) { return l.ts > firstTs; });
        if (!fresh.length) return;
        var frag = document.createDocumentFragment();
        fresh.forEach(function (l) { frag.appendChild(makeLogNode(l)); });
        listEl.insertBefore(frag, listEl.firstChild);
        listEl.__qhFirstTs = fresh[0].ts;
        // 裁剪超出上限的尾部节点，避免 DOM 无限增长
        while (listEl.childNodes.length > LOG_RENDER_MAX) listEl.removeChild(listEl.lastChild);
    }

    /** 单条日志节点：文本走 textContent，主题色走 class */
    function makeLogNode(l) {
        var div = document.createElement('div');
        div.className = 'log-item ' + (l.theme || '');
        var timeEl = document.createElement('span');
        timeEl.className = 'log-time';
        timeEl.textContent = QH.fmtTime(l.ts);
        var msgEl = document.createElement('span');
        msgEl.className = 'log-msg';
        msgEl.textContent = l.msg;
        div.appendChild(timeEl);
        div.appendChild(msgEl);
        return div;
    }

    /**
     * 运行日志降噪：同一事实在冷却窗口内只保留第一条。
     *
     * 设备抖动或自动调控反复触发时，`[自动] 水位 29.8mm < 下限 30mm…` 这类
     * 消息会在极短时间内刷满日志区。这里按「级别 + 归一化正文」做指纹：
     * 正文里的数字统一抹成 `#`，所以 29.8mm / 30.1mm 视为同一条。
     */
    var LOG_COOLDOWN_MS = 30000;

    /** 正文指纹：压空白 + 抹掉数字 */
    function logFingerprint(msg) {
        return String(msg === undefined || msg === null ? '' : msg)
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/\d+(?:\.\d+)?/g, '#')
            .slice(0, 120);
    }

    /**
     * 是否应当记录这条日志（纯函数，便于单测）。
     * @param {string} msg 日志正文
     * @param {number} now 当前毫秒时间戳
     * @param {Object} table 冷却表（会被就地更新）
     */
    function shouldRecordLog(msg, now, table) {
        var store = table || S.logCoolDown;
        var key = logFingerprint(msg);
        if (!key) return false;
        var last = store[key];
        if (last && now - last < LOG_COOLDOWN_MS) return false;
        store[key] = now;
        return true;
    }

    /** 追加一条运行日志（内存态 + 增量渲染 + 节流落盘；重复内容按冷却窗口抑制） */
    function addLog(msg, theme, options) {
        var opts = options || {};
        if (opts.dedupe !== false && !shouldRecordLog(msg, Date.now())) return null;
        var item = STORE.pushLog(msg, theme);
        renderLogs();
        return item;
    }

    /**
     * 渲染告警列表。首次全量 + 之后增量 prepend，最多渲染 ALERT_RENDER_MAX 条。
     * @param {boolean} incremental 为 true 时只插入新告警（默认全量重建）
     */
    var ALERT_RENDER_MAX = 30;
    function renderAlerts(incremental) {
        var listEl = QH.$('alertList');
        if (!listEl) return;
        var alerts = STORE.getAlerts();
        var slice = alerts.slice(0, ALERT_RENDER_MAX);

        if (!incremental || !listEl.__qhInit) {
            listEl.textContent = '';
            listEl.__qhInit = true;
            if (!slice.length) {
                var empty = document.createElement('div');
                empty.className = 'alert-empty';
                empty.textContent = '暂无告警记录';
                listEl.appendChild(empty);
                listEl.__qhFirstTs = 0;
                return;
            }
            slice.forEach(function (a) { listEl.appendChild(makeAlertNode(a)); });
            listEl.__qhFirstTs = slice[0].time;
            return;
        }

        var firstTs = listEl.__qhFirstTs || 0;
        var fresh = slice.filter(function (a) { return a.time > firstTs; });
        if (!fresh.length) return;
        // 首次有告警时移除“暂无告警记录”占位
        var placeholder = listEl.querySelector('.alert-empty');
        if (placeholder) placeholder.remove();
        var frag = document.createDocumentFragment();
        fresh.forEach(function (a) { frag.appendChild(makeAlertNode(a)); });
        listEl.insertBefore(frag, listEl.firstChild);
        listEl.__qhFirstTs = fresh[0].time;
        while (listEl.childNodes.length > ALERT_RENDER_MAX) listEl.removeChild(listEl.lastChild);
    }

    /** 单条告警节点：等级标签 + 时间 + 文本，全部 textContent */
    function makeAlertNode(a) {
        var div = document.createElement('div');
        div.className = 'alert-item ' + (a.level === 'danger' ? 'alert-danger' : 'alert-warn');
        var tag = document.createElement('span');
        tag.className = 'alert-tag';
        tag.textContent = (a.level === 'danger' ? '危险' : '警告');
        var timeEl = document.createElement('span');
        timeEl.className = 'alert-time';
        timeEl.textContent = QH.fmtTime(a.time);
        var msgEl = document.createElement('span');
        msgEl.className = 'alert-msg';
        msgEl.textContent = a.msg;
        div.appendChild(tag);
        div.appendChild(timeEl);
        div.appendChild(msgEl);
        return div;
    }

    /* ================= 统一 tick 任务注册 ================= */
    /**
     * 注册分频任务（全部挂在 core.js 的唯一主循环上）：
     *   DOM 刷写 500ms / 时钟 1s / 图表 2s / 心跳与告警 5s / 趋势落盘 30s
     */
    function registerTickTasks() {
        QH.registerTask('dom', 500, function () {
            QH.flushDom();
        });
        QH.registerTask('clock', 1000, function () {
            updateClock();
            // 新鲜度每秒重算：读数变旧是"时间流逝"造成的，不能只在收到数据时更新
            REALTIME.renderFreshness();
        });
        QH.registerTask('chart', 2000, function () {
            if (!S.chartDirty) return;
            CHARTS.renderTrendCharts();
            CHARTS.pushChartPoint();
        });
        QH.registerTask('heartbeat', 5000, function () {
            REALTIME.watchHeartbeat();
            REALTIME.checkAlerts();
        });
        QH.registerTask('persist', 30000, function () {
            STORE.flushAll(S.trendData, S.roriTrendData);
        });
    }

    /* ================= 启动 ================= */
    function init() {
        // 1) 内存态初始化：日志 / 告警（读一次 localStorage）
        STORE.initLogs();
        STORE.initAlerts();
        renderLogs();
        renderAlerts(false);

        // 2) 图表
        CHARTS.initCharts();
        CHARTS.loadHistory();

        // 3) 启动统一 tick
        registerTickTasks();
        QH.startTicker();
        updateClock();

        // 4) 后端数据：配置 / 阈值 / 模式
        CONFIG.loadConfig().then(function () {
            WEATHER.fetchWeather();
            WEATHER.fetchForecast();
        });
        CONFIG.loadThreshSettings();

        // 5) SocketIO 实时数据
        REALTIME.initSocket();
        REALTIME.refreshStatus();
        // 刷新页面后先补一帧服务端最新遥测，避免读数空白而图表有数据
        if (typeof REALTIME.loadLatest === 'function') REALTIME.loadLatest();

        addLog('系统已启动，正在连接云平台...', 'log-info');
    }

    // 页面卸载前把内存态强制落盘，避免丢失最后 30s 内的日志/告警/趋势
    function flushOnUnload() {
        try {
            STORE.flushAll(S.trendData, S.roriTrendData);
        } catch (e) { /* 卸载阶段异常忽略 */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    root.addEventListener('pagehide', flushOnUnload);
    root.addEventListener('beforeunload', flushOnUnload);

    root.QH_APP = {
        init: init,
        updateClock: updateClock,
        renderLogs: renderLogs,
        renderAlerts: renderAlerts,
        addLog: addLog,
        logFingerprint: logFingerprint,
        shouldRecordLog: shouldRecordLog,
        LOG_COOLDOWN_MS: LOG_COOLDOWN_MS,
        LOG_RENDER_MAX: LOG_RENDER_MAX,
        ALERT_RENDER_MAX: ALERT_RENDER_MAX
    };

    // 模板内联 onclick / 跨脚本全局
    root.addLog = addLog;
    root.renderLogs = renderLogs;
    root.renderAlerts = renderAlerts;

    // node 单测出口：浏览器下无 module，静默跳过
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            logFingerprint: logFingerprint,
            shouldRecordLog: shouldRecordLog,
            LOG_COOLDOWN_MS: LOG_COOLDOWN_MS
        };
    }
})(typeof globalThis !== 'undefined' ? globalThis : this);
