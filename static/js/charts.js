/* ============================================================
 * charts.js — Chart.js 初始化与统一刷新
 * 治理点：
 *   1) 不再每条 MQTT 消息调一次 chart.update()，改为统一 tick 2s 一次；
 *   2) update('none') 关闭过渡动画；
 *   3) 数据点超上限用 shift() 弹出，避免整数组重建；
 *   4) 关闭 parsing / animation，降低每帧开销。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var S = root.S;
    var QH_STORE = root.QH_STORE;   // store.js 先于本文件加载

    var CHART_LIMIT = 300;   // 单图最多渲染点数（超过则抽样）

    /** 初始化三张图表（水位 / 土壤湿度 / RORI） */
    function initCharts() {
        if (typeof Chart === 'undefined') return;
        Chart.defaults.font.family = '"Microsoft YaHei", sans-serif';
        Chart.defaults.color = '#6B7A72';
        // 全局关闭动画，配合 update('none') 彻底去掉重绘过渡
        Chart.defaults.animation = false;

        var common = {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            parsing: false,       // 数据已是数值数组，跳过解析器
            normalized: true,
            spanGaps: true,
            elements: { point: { radius: 0 } },
            plugins: { legend: { display: false } },
            interaction: { mode: 'nearest', intersect: false }
        };

        var wEl = QH.$('waterChart');
        if (wEl) {
            S.waterChart = new Chart(wEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '水位 (mm)', data: [], borderColor: '#2E7D8C',
                        backgroundColor: 'rgba(46,125,140,0.12)', tension: 0.3, fill: true,
                        pointRadius: 0, borderWidth: 2
                    }]
                },
                options: Object.assign({}, common, {
                    scales: { y: { position: 'left', min: 0, title: { display: true, text: 'mm' } } }
                })
            });
        }

        var sEl = QH.$('soilChart');
        if (sEl) {
            S.soilChart = new Chart(sEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: '土壤湿度 (%)', data: [], borderColor: '#1F6B45',
                        backgroundColor: 'rgba(31,107,69,0.12)', tension: 0.3, fill: true,
                        pointRadius: 0, borderWidth: 2
                    }]
                },
                options: Object.assign({}, common, {
                    scales: { y: { position: 'left', min: 0, max: 100, title: { display: true, text: '%' } } }
                })
            });
        }

        var rEl = QH.$('roriChart');
        if (rEl) {
            S.roriChart = new Chart(rEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'RORI', data: [], borderColor: '#E8A33D',
                        backgroundColor: 'rgba(232,163,61,0.12)', tension: 0.3, fill: true,
                        pointRadius: 0, borderWidth: 2
                    }]
                },
                options: Object.assign({}, common, {
                    scales: { y: { min: 0, max: 100, title: { display: true, text: '指数' } } }
                })
            });
        }
    }

    /** 横轴标签：相邻点跨天时，在新一天的点上标出日期（MM-DD HH:MM） */
    function fmtAxisLabel(ts, prevTs) {
        var d = new Date(ts);
        var hm = QH.pad2(d.getHours()) + ':' + QH.pad2(d.getMinutes());
        var pd = new Date(prevTs);
        var sameDay = pd.getFullYear() === d.getFullYear() && pd.getMonth() === d.getMonth() && pd.getDate() === d.getDate();
        return sameDay ? hm : QH.pad2(d.getMonth() + 1) + '-' + QH.pad2(d.getDate()) + ' ' + hm;
    }

    function axisLabels(list) {
        return list.map(function (p, i) {
            return fmtAxisLabel(p.ts, list[Math.max(0, i - 1)].ts);
        });
    }

    /** 数据多时抽样，避免点过密 */
    function sample(arr) {
        if (arr.length <= CHART_LIMIT) return arr;
        var step = Math.ceil(arr.length / CHART_LIMIT);
        var out = [];
        for (var i = 0; i < arr.length; i += step) out.push(arr[i]);
        return out;
    }

    /** 渲染三张趋势图（只由统一 tick 调用） */
    function renderTrendCharts() {
        if (!S.waterChart || !S.soilChart || !S.roriChart) return;
        var sw = sample(S.trendData);
        var sr = sample(S.roriTrendData);
        var labels = axisLabels(sw);

        S.waterChart.data.labels = labels;
        S.waterChart.data.datasets[0].data = sw.map(function (d) { return d.water; });
        S.waterChart.update('none');

        S.soilChart.data.labels = labels;
        S.soilChart.data.datasets[0].data = sw.map(function (d) { return d.soil; });
        S.soilChart.update('none');

        S.roriChart.data.labels = axisLabels(sr);
        S.roriChart.data.datasets[0].data = sr.map(function (d) { return d.rori; });
        S.roriChart.update('none');

        S.chartDirty = false;
    }

    /** 标记图表需要重绘，由统一 tick 合并到 2s 一次 */
    function markChartDirty() { S.chartDirty = true; }

    /** 追加一个趋势点（超上限 shift 弹出，不整数组重建） */
    function pushChartPoint() {
        if (!S.waterChart || !S.soilChart) return;
        // 只有真正收到过传感器数据才写入趋势，避免离线默认值产生假点
        if (!S.dataReceived || !S.cloudConnected || !S.deviceOnline) return;
        var now = Date.now();
        // 取内存态 RORI，避免读取尚未批量刷写的 DOM 文本
        var rori = (typeof S.currentRori === 'number') ? S.currentRori : 0;
        S.trendData.push({
            ts: now,
            water: parseFloat(S.currentWaterLevel) || 0,
            soil: parseFloat(S.currentSoilMoisture) || 0
        });
        S.roriTrendData.push({ ts: now, rori: rori });
        // 硬上限：超限弹出最旧点（O(1)），而不是过滤重建整个数组
        while (S.trendData.length > QH_STORE.LIMITS.TREND_MAX_POINTS) S.trendData.shift();
        while (S.roriTrendData.length > QH_STORE.LIMITS.TREND_MAX_POINTS) S.roriTrendData.shift();
        // 标记脏；真正的 JSON.stringify 由 30s 节流统一落盘
        QH_STORE.markTrendDirty(S.trendData, S.roriTrendData);
    }

    /** 切换折线/柱状 */
    function toggleChartType() {
        S.chartType = (S.chartType === 'line') ? 'bar' : 'line';
        var btn = QH.$('chartTypeBtn');
        if (btn) btn.textContent = (S.chartType === 'bar') ? '折线图' : '柱状图';
        [S.waterChart, S.soilChart, S.roriChart].forEach(function (c) {
            if (!c) return;
            c.config.type = S.chartType;
            c.update('none');
        });
    }
    root.toggleChartType = toggleChartType;

    /** 载入趋势：优先本地 3 天，兜底拉服务端历史 */
    function loadHistory() {
        var local = QH_STORE.loadTrendStore();
        if (local.water.length > 0) {
            S.trendData = local.water;
            S.roriTrendData = local.rori;
            S.chartDirty = true;
            renderTrendCharts();
            return;
        }
        fetch('/api/history?limit=500').then(function (r) { return r.json(); }).then(function (d) {
            if (!d.data || !d.data.length) return;
            var step = Math.max(1, Math.floor(d.data.length / 300));
            var sampled = d.data.filter(function (_, i) { return i % step === 0; });
            S.trendData = sampled.map(function (h) {
                return {
                    ts: h.ts || Date.now(),
                    water: Math.round(h.water_adc / 4095 * 300),
                    soil: Math.max(0, Math.min(Math.round((4095 - h.soil_adc) / 4095 * 100), 100))
                };
            });
            // RORI 趋势从历史 ADC 计算
            S.roriTrendData = sampled.map(function (h) {
                return { ts: h.ts, rori: root.computeRori(h.water_adc, h.soil_adc) };
            });
            QH_STORE.saveTrendStoreNow(S.trendData, S.roriTrendData);
            S.chartDirty = true;
            renderTrendCharts();
        }).catch(function () { /* 历史接口不可用则静默降级为本地趋势 */ });
    }

    root.QH_CHARTS = {
        initCharts: initCharts,
        renderTrendCharts: renderTrendCharts,
        markChartDirty: markChartDirty,
        pushChartPoint: pushChartPoint,
        toggleChartType: toggleChartType,
        loadHistory: loadHistory,
        CHART_LIMIT: CHART_LIMIT
    };
})(typeof globalThis !== 'undefined' ? globalThis : this);
