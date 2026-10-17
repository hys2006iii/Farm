/* ============================================================
 * advice.js — 七日灌溉建议与顶部概览带
 *
 * 数据来源：GET /api/advice/calendar（服务端算好的逐日建议）
 *          GET /api/metrics（近 7 日用水/增氧/减碳）
 *          GET /api/alerts（服务端告警）
 *
 * 治理点：
 *  - 所有文本走 textContent，不拼 innerHTML；
 *  - fetch 全部 .catch，后端不可用时保留「—」而不是塞假数据；
 *  - 只注册一个 5 分钟定时刷新，并挂在 app.js 的统一 ticker 上。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;

    /** 建议级别 → 样式类（与 advice.LEVEL_LABELS 对应） */
    var LEVEL_CLASS = {
        irrigate: 'advice-irrigate',
        wait_rain: 'advice-wait',
        watch: 'advice-watch',
        hold: 'advice-hold'
    };

    /** 6 日预报累计雨量（前端只做校验与求和，正式计算在服务端） */
    function sumPrecip(days) {
        if (!Array.isArray(days)) return 0;
        var total = 0;
        days.forEach(function (d) {
            var v = Number(d && d.precip);
            if (isFinite(v) && v > 0) total += v;
        });
        return Math.round(total * 10) / 10;
    }

    /** 取今天的建议（找不到就退回第一天） */
    function todayAdvice(days) {
        if (!Array.isArray(days) || !days.length) return null;
        var today = new Date();
        var iso = today.getFullYear() + '-' + QH.pad2(today.getMonth() + 1) + '-' + QH.pad2(today.getDate());
        for (var i = 0; i < days.length; i++) {
            if (days[i] && days[i].date === iso) return days[i];
        }
        return days[0];
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    /** 渲染逐日建议：一天一个小格 */
    function renderDays(days) {
        var wrap = QH.$('adviceDays');
        if (!wrap) return;
        wrap.textContent = '';
        if (!Array.isArray(days) || !days.length) {
            wrap.appendChild(el('div', 'advice-empty', '暂时取不到建议'));
            return;
        }
        days.forEach(function (day) {
            var cell = el('div', 'advice-day ' + (LEVEL_CLASS[day.level] || 'advice-hold'));
            cell.appendChild(el('div', 'advice-date', (day.date || '').slice(5)));
            cell.appendChild(el('div', 'advice-weekday', day.weekday || ''));
            cell.appendChild(el('div', 'advice-label', day.label || ''));
            cell.appendChild(el('div', 'advice-rain', '雨 ' + (Number(day.precip) || 0).toFixed(1) + ' mm'));
            cell.appendChild(el('div', 'advice-text', day.text || ''));
            wrap.appendChild(cell);
        });
    }

    function setKpi(id, text) {
        var node = QH.$(id);
        if (node) QH.setText(node, text);
    }

    /** 读七日建议并刷新建议区 + 两个概览指标 */
    function refreshCalendar() {
        return fetch('/api/advice/calendar').then(function (r) {
            if (!r.ok) throw new Error('http ' + r.status);
            return r.json();
        }).then(function (data) {
            if (!data || data.status !== 'success') throw new Error('bad payload');
            var days = data.days || [];
            renderDays(days);
            var today = todayAdvice(days);
            // 有氧风险时概览标题要让位给缺氧提示，否则会出现「正常维持」和红色 RORI 预警并存
            var title = today ? (today.label || '—') : '—';
            var lvl = data.rori_level || {};
            var rori = (typeof data.rori === 'number') ? data.rori : null;
            if (rori !== null && rori >= 70) {
                title = '缺氧 · ' + (lvl.name || '重度厌氧');
            } else if (rori !== null && rori >= 40) {
                title = '注意 · ' + (lvl.name || '中度缺氧');
            }
            setKpi('kpiAdvice', title);
            var sub = data.summary || '按当前墒情与 6 日报雨推算';
            setKpi('kpiAdviceSub', sub);
            var weekSub = QH.$('adviceWeekSub');
            if (weekSub) QH.setText(weekSub, data.has_forecast ? '按当前墒情与 6 日报雨推算' : '未取到天气预报，仅按当前墒情推算');
            setKpi('kpiRain', sumPrecip(days).toFixed(1));
            setKpi('kpiRainSub', data.has_forecast ? '毫米 · 未来 6 日累计' : '毫米 · 未取到预报');
        }).catch(function () {
            setKpi('kpiAdviceSub', '建议服务暂不可用');
            var weekSub = QH.$('adviceWeekSub');
            if (weekSub) QH.setText(weekSub, '建议服务暂不可用');
        });
    }

    /** 近 7 日用水量 */
    function refreshWater() {
        return fetch('/api/metrics').then(function (r) {
            if (!r.ok) throw new Error('http ' + r.status);
            return r.json();
        }).then(function (data) {
            if (!data || data.error) throw new Error('bad payload');
            var liters = Number(data.water_liters);
            setKpi('kpiWater', isFinite(liters) ? liters.toFixed(1) : '—');
        }).catch(function () { /* 保留「—」 */ });
    }

    /** 未确认告警数 */
    function refreshAlerts() {
        return fetch('/api/alerts?limit=200').then(function (r) {
            if (!r.ok) throw new Error('http ' + r.status);
            return r.json();
        }).then(function (data) {
            var rows = (data && data.alerts) || [];
            var unacked = rows.filter(function (a) { return !a.acked && !a.ack_ts; }).length;
            setKpi('kpiAlerts', String(unacked));
        }).catch(function () { /* 保留「—」 */ });
    }

    /** 整屏刷新（概览带 + 建议区） */
    function refresh() {
        refreshCalendar();
        refreshWater();
        refreshAlerts();
    }

    function init() {
        refresh();
        if (QH && typeof QH.registerTask === 'function') {
            QH.registerTask('advice', 300000, refreshCalendar);
        }
    }

    root.QH_ADVICE = {
        refresh: refresh,
        refreshCalendar: refreshCalendar,
        refreshWater: refreshWater,
        refreshAlerts: refreshAlerts,
        sumPrecip: sumPrecip,
        todayAdvice: todayAdvice,
        LEVEL_CLASS: LEVEL_CLASS
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})(typeof globalThis !== 'undefined' ? globalThis : this);
