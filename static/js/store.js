/* ============================================================
 * store.js — localStorage 持久化层
 * 治理点：拆分前每次读全量 -> 改 -> 写全量，数据增长后卡顿。
 * 现在改为：内存态为准 + 30s 节流批量落盘 + 硬上限裁剪。
 *   趋势 farmTrend / farmTrendRori : 最多 2000 点
 *   日志   farmLogs                : 最多 500 条
 *   告警   farmAlerts              : 最多 200 条
 * ============================================================ */
(function (root) {
    'use strict';

    var LIMITS = {
        TREND_MAX_POINTS: 2000,   // 每个趋势序列最多 2000 点
        LOG_MAX: 500,             // 日志最多 500 条
        ALERT_MAX: 200,           // 告警最多 200 条
        TREND_KEEP_MS: 3 * 24 * 3600 * 1000,   // 趋势保留 3 天
        LOG_KEEP_MS: 24 * 3600 * 1000,         // 日志保留 24 小时
        ALERT_KEEP_MS: 24 * 3600 * 1000,       // 告警保留 24 小时
        FLUSH_MS: 30000                        // 落盘节流 30s
    };

    var KEYS = {
        TREND: 'farmTrend',
        TREND_RORI: 'farmTrendRori',
        LOGS: 'farmLogs',
        ALERTS: 'farmAlerts'
    };

    // 内存态：唯一数据源，渲染/写盘都读这里，不再每次 JSON.parse 全量
    var mem = {
        logs: [],
        alerts: [],
        dirty: { trend: false, logs: false, alerts: false }
    };

    /* ---------------- 低层读写 ---------------- */
    function readJSON(key, fallback) {
        try {
            var raw = localStorage.getItem(key);
            if (!raw) return fallback;
            var arr = JSON.parse(raw);
            return Array.isArray(arr) ? arr : fallback;
        } catch (e) {
            return fallback;
        }
    }

    function writeJSON(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 配额满等异常忽略 */ }
    }

    /** 按时间戳裁剪 + 条数硬上限（保留最新 N 条） */
    function trimByTime(list, keepMs, maxCount, tsKey) {
        var key = tsKey || 'ts';
        var cutoff = Date.now() - keepMs;
        var out = list.filter(function (it) { return it && it[key] >= cutoff; });
        if (out.length > maxCount) out.length = maxCount;
        return out;
    }

    /* ---------------- 趋势 ---------------- */
    /**
     * 读取本地趋势（过滤最近 3 天，剔除设备离线时的默认假点）。
     * @returns {{water:Array, rori:Array}}
     */
    function loadTrendStore() {
        var cutoff = Date.now() - LIMITS.TREND_KEEP_MS;
        var w = readJSON(KEYS.TREND, []).filter(function (p) {
            // water=0 且 soil=58 是设备离线时页面默认值产生的假点
            return p && p.ts >= cutoff && !(p.water === 0 && p.soil === 58);
        });
        if (w.length > LIMITS.TREND_MAX_POINTS) w = w.slice(w.length - LIMITS.TREND_MAX_POINTS);
        // 用有效水位点的时间桶集合过滤 RORI：离线假点是同一时刻一起写入的
        var validBuckets = {};
        w.forEach(function (p) { validBuckets[Math.floor(p.ts / 60000)] = 1; });
        var r = readJSON(KEYS.TREND_RORI, []).filter(function (p) {
            return p && p.ts >= cutoff && validBuckets[Math.floor(p.ts / 60000)];
        });
        if (r.length > LIMITS.TREND_MAX_POINTS) r = r.slice(r.length - LIMITS.TREND_MAX_POINTS);
        return { water: w, rori: r };
    }

    /**
     * 标记趋势需要落盘（真正的 JSON.stringify 由 30s 节流统一执行）。
     * @param {Array} trendData 水位/湿度序列
     * @param {Array} roriTrendData RORI 序列
     */
    function markTrendDirty(trendData, roriTrendData) {
        // 就地裁剪，避免数组无限增长
        if (trendData.length > LIMITS.TREND_MAX_POINTS) trendData.splice(0, trendData.length - LIMITS.TREND_MAX_POINTS);
        if (roriTrendData.length > LIMITS.TREND_MAX_POINTS) roriTrendData.splice(0, roriTrendData.length - LIMITS.TREND_MAX_POINTS);
        mem.dirty.trend = true;
    }

    /** 立即落盘趋势（节流到期或页面卸载时调用） */
    function flushTrend(trendData, roriTrendData) {
        if (!mem.dirty.trend) return;
        mem.dirty.trend = false;
        var cutoff = Date.now() - LIMITS.TREND_KEEP_MS;
        // 按分钟桶去重（同一分钟只留最后一点）
        var wm = {};
        trendData.forEach(function (p) { wm[Math.floor(p.ts / 60000) * 60000] = { ts: p.ts, water: p.water, soil: p.soil }; });
        var w = Object.keys(wm).map(function (k) { return wm[k]; })
            .filter(function (p) { return p.ts >= cutoff; })
            .sort(function (a, b) { return a.ts - b.ts; });
        if (w.length > LIMITS.TREND_MAX_POINTS) w = w.slice(w.length - LIMITS.TREND_MAX_POINTS);
        writeJSON(KEYS.TREND, w);

        var rm = {};
        roriTrendData.forEach(function (p) { rm[Math.floor(p.ts / 60000) * 60000] = { ts: p.ts, rori: p.rori }; });
        var r = Object.keys(rm).map(function (k) { return rm[k]; })
            .filter(function (p) { return p.ts >= cutoff; })
            .sort(function (a, b) { return a.ts - b.ts; });
        if (r.length > LIMITS.TREND_MAX_POINTS) r = r.slice(r.length - LIMITS.TREND_MAX_POINTS);
        writeJSON(KEYS.TREND_RORI, r);
    }

    /** 直接写入趋势（服务端历史回填等一次性场景） */
    function saveTrendStoreNow(trendData, roriTrendData) {
        mem.dirty.trend = true;
        flushTrend(trendData, roriTrendData);
    }

    /* ---------------- 日志 ---------------- */
    /** 内存态追加一条日志（不落盘，返回新日志对象） */
    function pushLog(msg, theme) {
        var item = { ts: Date.now(), msg: msg, theme: theme || '' };
        mem.logs.unshift(item);
        mem.logs = trimByTime(mem.logs, LIMITS.LOG_KEEP_MS, LIMITS.LOG_MAX, 'ts');
        mem.dirty.logs = true;
        return item;
    }

    /** 初始化内存日志（页面启动时调用一次） */
    function initLogs() {
        mem.logs = trimByTime(readJSON(KEYS.LOGS, []), LIMITS.LOG_KEEP_MS, LIMITS.LOG_MAX, 'ts');
        return mem.logs;
    }

    function flushLogs() {
        if (!mem.dirty.logs) return;
        mem.dirty.logs = false;
        mem.logs = trimByTime(mem.logs, LIMITS.LOG_KEEP_MS, LIMITS.LOG_MAX, 'ts');
        writeJSON(KEYS.LOGS, mem.logs);
    }

    function getLogs() { return mem.logs; }

    /* ---------------- 告警 ---------------- */
    /** 内存态追加一条告警 */
    function pushAlert(level, msg) {
        var item = { time: Date.now(), level: level, msg: msg };
        mem.alerts.unshift(item);
        mem.alerts = trimByTime(mem.alerts, LIMITS.ALERT_KEEP_MS, LIMITS.ALERT_MAX, 'time');
        mem.dirty.alerts = true;
        return item;
    }

    function initAlerts() {
        mem.alerts = trimByTime(readJSON(KEYS.ALERTS, []), LIMITS.ALERT_KEEP_MS, LIMITS.ALERT_MAX, 'time');
        return mem.alerts;
    }

    function flushAlerts() {
        if (!mem.dirty.alerts) return;
        mem.dirty.alerts = false;
        mem.alerts = trimByTime(mem.alerts, LIMITS.ALERT_KEEP_MS, LIMITS.ALERT_MAX, 'time');
        writeJSON(KEYS.ALERTS, mem.alerts);
    }

    function getAlerts() {
        // 渲染时同样过滤 24 小时
        return trimByTime(mem.alerts, LIMITS.ALERT_KEEP_MS, LIMITS.ALERT_MAX, 'time');
    }

    /* ---------------- 统一落盘 ---------------- */
    /**
     * 30s 节流批量落盘：只在有脏标记时才写 localStorage。
     * @param {Array} trendData
     * @param {Array} roriTrendData
     */
    function flushAll(trendData, roriTrendData) {
        flushTrend(trendData || [], roriTrendData || []);
        flushLogs();
        flushAlerts();
    }

    function hasDirty() { return mem.dirty.trend || mem.dirty.logs || mem.dirty.alerts; }

    root.QH_STORE = {
        LIMITS: LIMITS,
        KEYS: KEYS,
        mem: mem,
        loadTrendStore: loadTrendStore,
        markTrendDirty: markTrendDirty,
        flushTrend: flushTrend,
        saveTrendStoreNow: saveTrendStoreNow,
        pushLog: pushLog, initLogs: initLogs, flushLogs: flushLogs, getLogs: getLogs,
        pushAlert: pushAlert, initAlerts: initAlerts, flushAlerts: flushAlerts, getAlerts: getAlerts,
        flushAll: flushAll, hasDirty: hasDirty,
        trimByTime: trimByTime
    };
})(typeof globalThis !== 'undefined' ? globalThis : this);
