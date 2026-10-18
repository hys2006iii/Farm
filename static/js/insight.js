/* ============================================================
   insight.js — 「智能洞察」面板
   5 个 Tab：告警中心 / 运行日志 / 设备状态 / AI 决策预案 / 节水减碳

   设计约束（AGENTS.md 硬性规则）：
   - 所有接口文本一律 textContent 或 esc()，禁止 innerHTML 拼接未转义数据
   - 面板打开才拉数据；关闭时清理定时器，不常驻轮询
   - 所有 fetch 都有 try/catch + toast 失败提示，不因接口失败白屏
   - 纯函数集中在 InsightPure 并导出，供 node --test 直接 import
   ============================================================ */
(function (root) {
    'use strict';

    /* ============================================================
       一、纯函数（可被 node --test 直接 import，无 DOM 依赖）
       ============================================================ */

    /** 告警级别 -> 色点 class（danger=红 / warning=橙 / info=蓝） */
    function levelClass(level) {
        var s = String(level === undefined || level === null ? '' : level).toLowerCase();
        if (s === 'danger' || s === 'error' || s === 'critical') return 'lv-danger';
        if (s === 'warning' || s === 'warn') return 'lv-warning';
        return 'lv-info';
    }

    /** 告警级别 -> 中文名 */
    function levelText(level) {
        var s = String(level === undefined || level === null ? '' : level).toLowerCase();
        if (s === 'danger') return '严重';
        if (s === 'warning') return '警告';
        if (s === 'info') return '提示';
        return '未知';
    }

    /** 日志来源 -> 中文映射 */
    var SOURCE_TEXT = {
        system: '系统',
        device: '设备',
        auto: '自动调控',
        manual: '手动',
        plan: '预案',
        config: '配置'
    };

    /** 日志来源 -> 中文名（未知来源原样返回，不编造） */
    function sourceText(source) {
        var s = String(source === undefined || source === null ? '' : source).toLowerCase();
        if (Object.prototype.hasOwnProperty.call(SOURCE_TEXT, s)) return SOURCE_TEXT[s];
        return s || '未知';
    }

    /** 日志来源 -> 徽标 class */
    function sourceClass(source) {
        var s = String(source === undefined || source === null ? '' : source).toLowerCase();
        return Object.prototype.hasOwnProperty.call(SOURCE_TEXT, s) ? 'src-' + s : 'src-system';
    }

    /** 日志级别 -> 标记 class */
    function logLevelClass(level) {
        var s = String(level === undefined || level === null ? '' : level).toLowerCase();
        if (s === 'error') return 'log-error';
        if (s === 'warning' || s === 'warn') return 'log-warning';
        return 'log-info';
    }

    /** 预案状态 -> 中文名 */
    var PLAN_STATUS_TEXT = {
        pending: '待确认',
        confirmed: '已下发',
        rejected: '已拒绝',
        expired: '已过期',
        failed: '下发失败'
    };

    /** 预案状态 -> 中文名 */
    function planStatusText(status) {
        var s = String(status === undefined || status === null ? '' : status).toLowerCase();
        if (Object.prototype.hasOwnProperty.call(PLAN_STATUS_TEXT, s)) return PLAN_STATUS_TEXT[s];
        return s || '未知';
    }

    /** 预案状态 -> 徽标 class */
    function planStatusClass(status) {
        var s = String(status === undefined || status === null ? '' : status).toLowerCase();
        return Object.prototype.hasOwnProperty.call(PLAN_STATUS_TEXT, s) ? 'st-' + s : 'st-expired';
    }

    /** 设备动作英文 -> 中文 */
    function actionText(action) {
        var s = String(action === undefined || action === null ? '' : action).toLowerCase();
        if (s === 'on' || s === 'start' || s === 'open') return '开启';
        if (s === 'off' || s === 'stop' || s === 'close') return '关闭';
        return s || '—';
    }

    /** 设备键 -> 中文名 */
    var DEVICE_TEXT = {
        air_pump: '气泵',
        water_pump: '水泵'
    };

    /** 设备键 -> 中文名（未知原样返回） */
    function deviceText(device) {
        var s = String(device === undefined || device === null ? '' : device).toLowerCase();
        if (Object.prototype.hasOwnProperty.call(DEVICE_TEXT, s)) return DEVICE_TEXT[s];
        return s || '未知设备';
    }

    /** 补零 */
    function pad2(n) { return String(n).padStart(2, '0'); }

    /**
     * 时间戳（毫秒）-> 'MM-DD HH:MM:SS'
     * 非法值统一返回 '--'，避免 NaN 显示。
     */
    function fmtStamp(ts) {
        var n = Number(ts);
        if (!isFinite(n) || n <= 0) return '--';
        var d = new Date(n);
        if (isNaN(d.getTime())) return '--';
        return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' +
            pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
    }

    /** 静默秒数 -> 人类可读（'刚刚' / '12 秒' / '3 分 5 秒' / '2 小时 10 分'） */
    function fmtSilent(seconds) {
        // null / undefined / '' 表示「无数据」，与数字 0 区分，统一回退 '--'
        if (seconds === null || seconds === undefined || seconds === '') return '--';
        var n = Number(seconds);
        if (!isFinite(n) || n < 0) return '--';
        n = Math.floor(n);
        if (n < 5) return '刚刚';
        if (n < 60) return n + ' 秒';
        if (n < 3600) {
            var m = Math.floor(n / 60);
            var s = n % 60;
            return s ? m + ' 分 ' + s + ' 秒' : m + ' 分钟';
        }
        var h = Math.floor(n / 3600);
        var mm = Math.floor((n % 3600) / 60);
        return mm ? h + ' 小时 ' + mm + ' 分' : h + ' 小时';
    }

    /**
     * 指标数值格式化：保留 1 位小数（metrics 卡片与逐日表格统一口径）。
     * null / undefined / NaN / 非数字 -> '0.0'，避免界面出现 NaN。
     */
    function fmtNum(value, digits) {
        var n = Number(value);
        if (!isFinite(n)) return digits === 0 ? '0' : '0.0';
        var d = typeof digits === 'number' ? digits : 1;
        return n.toFixed(d);
    }

    /** 各 Tab 的空态文案（统一出口，便于测试钉住） */
    var EMPTY_TEXT = {
        alerts: '暂无告警记录',
        logs: '暂无运行日志',
        device: '暂无设备上报记录',
        plans: '暂无历史预案',
        metrics: '所选时段暂无数据'
    };

    /** 取空态文案 */
    function emptyText(kind) {
        return Object.prototype.hasOwnProperty.call(EMPTY_TEXT, kind) ? EMPTY_TEXT[kind] : '暂无数据';
    }

    /**
     * metrics 汇总 -> 4 张指标卡的展示数据。
     * 返回 [{key, label, value, unit}]，value 已格式化为 1 位小数字符串。
     */
    function metricCards(summary) {
        var s = summary && typeof summary === 'object' ? summary : {};
        return [
            { key: 'water_liters', label: '灌溉用水量', value: fmtNum(s.water_liters), unit: 'L' },
            { key: 'air_minutes', label: '增氧时长', value: fmtNum(s.air_minutes), unit: 'min' },
            { key: 'ch4_saved_g', label: 'CH₄ 减排', value: fmtNum(s.ch4_saved_g), unit: 'g' },
            { key: 'co2e_saved_g', label: 'CO₂e 减排', value: fmtNum(s.co2e_saved_g), unit: 'g' }
        ];
    }

    /** 逐日序列 -> 表格行数据（字段缺失一律兜底为 0.0） */
    function metricRows(series) {
        if (!Array.isArray(series)) return [];
        return series.map(function (row) {
            var r = row && typeof row === 'object' ? row : {};
            return {
                day: String(r.day === undefined || r.day === null ? '--' : r.day),
                water_liters: fmtNum(r.water_liters),
                pump_minutes: fmtNum(r.pump_minutes),
                air_minutes: fmtNum(r.air_minutes),
                ch4_saved_g: fmtNum(r.ch4_saved_g),
                co2e_saved_g: fmtNum(r.co2e_saved_g)
            };
        });
    }

    /** 导出：node 测试与浏览器共用同一份纯函数 */
    var InsightPure = {
        levelClass: levelClass, levelText: levelText,
        sourceText: sourceText, sourceClass: sourceClass,
        logLevelClass: logLevelClass, SOURCE_TEXT: SOURCE_TEXT,
        planStatusText: planStatusText, planStatusClass: planStatusClass,
        PLAN_STATUS_TEXT: PLAN_STATUS_TEXT,
        actionText: actionText, deviceText: deviceText, DEVICE_TEXT: DEVICE_TEXT,
        fmtStamp: fmtStamp, fmtSilent: fmtSilent, fmtNum: fmtNum, pad2: pad2,
        emptyText: emptyText, EMPTY_TEXT: EMPTY_TEXT,
        metricCards: metricCards, metricRows: metricRows
    };
    root.InsightPure = InsightPure;
    if (typeof module !== 'undefined' && module.exports) module.exports = InsightPure;

    /* ============================================================
       二、面板逻辑（仅浏览器；node 环境下 document 不存在，直接返回）
       ============================================================ */
    if (typeof document === 'undefined') return;

    /** 统一的 fetch JSON：非 2xx 或非 JSON 都抛出可读错误 */
    function fetchJSON(url, options) {
        var opts = options || {};
        opts.headers = Object.assign({ 'Accept': 'application/json' }, opts.headers || {});
        if (opts.body) opts.headers['Content-Type'] = 'application/json';
        return fetch(url, opts).then(function (res) {
            return res.text().then(function (text) {
                var data = null;
                try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
                if (!res.ok) {
                    var msg = data && data.error ? data.error : ('HTTP ' + res.status);
                    var err = new Error(msg);
                    err.status = res.status;
                    throw err;
                }
                return data;
            });
        });
    }

    /** 失败提示（统一走现有 toast） */
    function fail(msg) {
        if (root.toast) root.toast(msg, 'error');
    }

    /** 生成一个带文本的元素 */
    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = String(text);
        return node;
    }

    /** 清空容器并放入空态 / 加载 / 错误提示 */
    function setState(host, text, kind) {
        host.textContent = '';
        var cls = 'insight-empty' + (kind === 'error' ? ' error' : '');
        host.appendChild(el('div', cls, text));
    }

    /** 切换 Tab 的 active 高亮（按钮与内容面板） */
    function activateTab(name) {
        var tabs = document.querySelectorAll('.insight-tab');
        for (var i = 0; i < tabs.length; i++) {
            tabs[i].classList.toggle('active', tabs[i].getAttribute('data-tab') === name);
        }
        var panes = document.querySelectorAll('.insight-pane');
        for (var j = 0; j < panes.length; j++) {
            panes[j].classList.toggle('active', panes[j].id === 'insightPane-' + name);
        }
    }

    /* ---------- Tab 1：告警中心 ---------- */
    function loadAlerts() {
        var host = document.getElementById('insightAlertList');
        if (!host) return Promise.resolve();
        setState(host, '加载中...');
        return fetchJSON('/api/alerts?limit=100').then(function (data) {
            var items = data && Array.isArray(data.alerts) ? data.alerts : [];
            if (!items.length) { setState(host, emptyText('alerts')); return; }
            host.textContent = '';
            var list = el('div', 'insight-list');
            items.forEach(function (a) { list.appendChild(alertRow(a)); });
            host.appendChild(list);
        }).catch(function (e) {
            setState(host, '告警加载失败：' + e.message, 'error');
            fail('告警加载失败：' + e.message);
        });
    }

    /** 一键确认全部未确认告警（值守场景：积压几十条时逐条点不现实） */
    function ackAllAlerts(btn) {
        if (btn) { btn.disabled = true; btn.textContent = '确认中...'; }
        fetchJSON('/api/alerts/ack_all', {
            method: 'POST',
            body: JSON.stringify({})
        }).then(function (data) {
            var count = (data && typeof data.acked === 'number') ? data.acked : 0;
            if (root.toast) {
                root.toast(count ? ('已确认 ' + count + ' 条告警') : '没有待确认的告警', 'success');
            }
            loadAlerts();
            refreshUnackedKpi();
        }).catch(function (e) {
            if (btn) { btn.disabled = false; btn.textContent = '全部确认'; }
            fail('批量确认失败：' + e.message);
        });
    }

    /** 概览带的「未确认告警」计数：批量确认后立刻同步，不必等 5 分钟轮询 */
    function refreshUnackedKpi() {
        if (root.QH_ADVICE && typeof root.QH_ADVICE.refreshAlerts === 'function') {
            root.QH_ADVICE.refreshAlerts();
        }
    }

    /** 单条告警行（时间 / 级别色点 / 类型 / 内容 / 确认按钮） */
    function alertRow(a) {
        var item = a && typeof a === 'object' ? a : {};
        var row = el('div', 'insight-row');
        row.setAttribute('data-alert-id', item.id === undefined ? '' : String(item.id));
        if (item.acked) row.classList.add('is-acked');

        row.appendChild(el('span', 'row-time', fmtStamp(item.ts)));
        row.appendChild(el('span', 'lv-dot ' + levelClass(item.level)));

        var main = el('div', 'row-main');
        main.appendChild(el('div', null, String(item.content === undefined ? '' : item.content)));
        var meta = el('div', 'row-meta',
            levelText(item.level) + ' · ' + String(item.code === undefined || item.code === null ? '' : item.code));
        main.appendChild(meta);
        row.appendChild(main);

        var btn = el('button', 'insight-btn ghost sm', item.acked ? '已确认' : '确认');
        btn.type = 'button';
        if (item.acked) {
            btn.disabled = true;
        } else {
            btn.addEventListener('click', function () { ackAlert(item.id, row, btn); });
        }
        row.appendChild(btn);
        return row;
    }

    /** 确认一条告警：成功后本行置灰并标「已确认」 */
    function ackAlert(id, row, btn) {
        if (id === undefined || id === null) return;
        btn.disabled = true;
        fetchJSON('/api/alerts/ack', {
            method: 'POST',
            body: JSON.stringify({ id: Number(id) })
        }).then(function () {
            row.classList.add('is-acked');
            btn.textContent = '已确认';
            if (root.toast) root.toast('告警已确认', 'success');
        }).catch(function (e) {
            btn.disabled = false;
            fail('确认失败：' + e.message);
        });
    }

    /* ---------- Tab 2：运行日志 ---------- */
    function loadLogs() {
        var host = document.getElementById('insightLogList');
        if (!host) return Promise.resolve();
        setState(host, '加载中...');
        return fetchJSON('/api/logs?limit=200').then(function (data) {
            var items = data && Array.isArray(data.logs) ? data.logs : [];
            if (!items.length) { setState(host, emptyText('logs')); return; }
            host.textContent = '';
            var list = el('div', 'insight-list');
            // 接口已按 ts DESC 返回；再排一次以防后端顺序变动
            items.slice().sort(function (x, y) { return Number(y.ts) - Number(x.ts); })
                .forEach(function (l) { list.appendChild(logRow(l)); });
            host.appendChild(list);
        }).catch(function (e) {
            setState(host, '日志加载失败：' + e.message, 'error');
            fail('日志加载失败：' + e.message);
        });
    }

    /** 单条日志行（时间 / 来源徽标 / 级别 / 内容） */
    function logRow(l) {
        var item = l && typeof l === 'object' ? l : {};
        var row = el('div', 'insight-row');
        row.appendChild(el('span', 'row-time', fmtStamp(item.ts)));
        row.appendChild(el('span', 'src-badge ' + sourceClass(item.source), sourceText(item.source)));
        row.appendChild(el('span', 'log-level ' + logLevelClass(item.level), String(item.level || 'info')));
        row.appendChild(el('div', 'row-main', String(item.message === undefined ? '' : item.message)));
        return row;
    }

    /* ---------- Tab 3：设备状态 ---------- */
    function loadDeviceStatus() {
        var host = document.getElementById('insightDeviceBody');
        if (!host) return Promise.resolve();
        setState(host, '加载中...');
        return fetchJSON('/api/device_status').then(function (data) {
            var d = data && typeof data === 'object' ? data : {};
            var online = !!d.online;
            host.textContent = '';

            var hero = el('div', 'device-hero');
            // 从未上报过时 last_seen_ts 为空，别把它说成「刚刚」，那样会误导
            var neverSeen = d.last_seen_ts === null || d.last_seen_ts === undefined;
            hero.appendChild(el('div', 'device-state ' + (online ? 'online' : 'offline'),
                online ? '在线' : '离线'));
            hero.appendChild(el('div', 'device-hint',
                online
                    ? '设备上报正常，数据实时同步中'
                    : (neverSeen ? '尚未收到该设备的心跳，请确认设备已上电并连网' : '设备已停止上报数据')));
            if (!online) {
                hero.appendChild(el('div', 'device-offline-warn', '设备已离线，请检查供电与网络'));
            }

            var meta = el('div', 'device-meta');
            meta.appendChild(metaCell('最近上报时间', fmtStamp(d.last_seen_ts)));
            meta.appendChild(metaCell('静默时长', neverSeen ? '--' : fmtSilent(d.silent_seconds)));
            meta.appendChild(metaCell('判定', online ? '在线' : '离线'));
            hero.appendChild(meta);

            host.appendChild(hero);
        }).catch(function (e) {
            setState(host, '设备状态加载失败：' + e.message, 'error');
            fail('设备状态加载失败：' + e.message);
        });
    }

    /** 设备状态的一个信息格 */
    function metaCell(label, value) {
        var cell = el('div', 'meta-cell');
        cell.appendChild(el('div', 'meta-label', label));
        cell.appendChild(el('div', 'meta-value', value));
        return cell;
    }

    /* ---------- Tab 4：AI 决策预案 ---------- */
    var currentPlan = null;   // 当前展示的待确认预案

    function loadPlans() {
        var host = document.getElementById('insightPlanHistory');
        if (!host) return Promise.resolve();
        setState(host, '加载中...');
        return fetchJSON('/api/plans?limit=20').then(function (data) {
            var items = data && Array.isArray(data.plans) ? data.plans : [];
            if (!items.length) { setState(host, emptyText('plans')); return; }
            host.textContent = '';
            var list = el('div', 'insight-list');
            items.forEach(function (p) { list.appendChild(planHistoryRow(p)); });
            host.appendChild(list);
        }).catch(function (e) {
            setState(host, '预案列表加载失败：' + e.message, 'error');
        });
    }

    /** 历史预案的一行 */
    function planHistoryRow(p) {
        var item = p && typeof p === 'object' ? p : {};
        var row = el('div', 'insight-row');
        row.appendChild(el('span', 'row-time', fmtStamp(item.ts)));
        row.appendChild(el('span', 'plan-badge ' + planStatusClass(item.status),
            planStatusText(item.status)));
        var main = el('div', 'row-main');
        main.appendChild(el('div', null, String(item.summary || '（无摘要）')));
        main.appendChild(el('div', 'row-meta', '预案 #' + String(item.id === undefined ? '--' : item.id)));
        row.appendChild(main);
        return row;
    }

    /** 生成预案 */
    function proposePlan() {
        var btn = document.getElementById('insightProposeBtn');
        var host = document.getElementById('insightPlanCurrent');
        if (!host) return Promise.resolve();
        if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }
        setState(host, 'AI 正在结合当前感知数据推理，请稍候...');

        return fetchJSON('/api/plan/propose', {
            method: 'POST',
            body: JSON.stringify({})
        }).then(function (data) {
            currentPlan = data && typeof data === 'object' ? data : {};
            renderCurrentPlan(currentPlan);
            loadPlans();
        }).catch(function (e) {
            setState(host, '预案生成失败：' + e.message, 'error');
            fail('预案生成失败：' + e.message);
        }).then(function () {
            if (btn) { btn.disabled = false; btn.textContent = '生成预案'; }
        });
    }

    /** 渲染当前预案（reasoning 可折叠 + actions 表格 + summary + risk） */
    function renderCurrentPlan(plan) {
        var host = document.getElementById('insightPlanCurrent');
        if (!host) return;
        host.textContent = '';

        var card = el('div', 'plan-card');
        var head = el('div', 'plan-head');
        head.appendChild(el('h4', null, '预案 #' + String(plan.plan_id === undefined ? '--' : plan.plan_id)));
        head.appendChild(el('span', 'plan-badge ' + planStatusClass(plan.status),
            planStatusText(plan.status)));
        if (plan.ai_used) head.appendChild(el('span', 'plan-badge ai-used', 'AI 生成'));
        else head.appendChild(el('span', 'plan-badge', '规则回退'));
        card.appendChild(head);

        // 可折叠的推理依据
        var details = document.createElement('details');
        details.className = 'plan-reason';
        var summary = document.createElement('summary');
        summary.textContent = '推理依据';
        details.appendChild(summary);
        details.appendChild(el('div', 'reason-body', String(plan.reasoning || '（无推理文本）')));
        card.appendChild(details);

        // 动作表格
        var actions = Array.isArray(plan.actions) ? plan.actions : [];
        if (actions.length) {
            card.appendChild(actionsTable(actions));
        } else {
            card.appendChild(el('div', 'row-meta', '本次预案没有需要下发的动作'));
        }

        if (plan.summary) card.appendChild(el('div', 'plan-summary', String(plan.summary)));
        if (plan.risk) card.appendChild(el('div', 'plan-risk', '风险提示：' + String(plan.risk)));

        // 人工确认 / 拒绝
        var acts = el('div', 'plan-actions');
        var okBtn = el('button', 'insight-btn', '确认下发');
        okBtn.type = 'button';
        var noBtn = el('button', 'insight-btn danger', '拒绝');
        noBtn.type = 'button';

        if (plan.status && plan.status !== 'pending') {
            okBtn.disabled = true;
            noBtn.disabled = true;
        } else {
            okBtn.addEventListener('click', function () { confirmPlan(plan.plan_id, okBtn, noBtn); });
            noBtn.addEventListener('click', function () { rejectPlan(plan.plan_id, okBtn, noBtn); });
        }
        acts.appendChild(okBtn);
        acts.appendChild(noBtn);
        card.appendChild(acts);

        host.appendChild(card);
    }

    /** 动作表格：设备 / 动作 / 理由 */
    function actionsTable(actions) {
        var table = el('table', 'insight-table');
        var thead = document.createElement('thead');
        var htr = document.createElement('tr');
        ['设备', '动作', '理由'].forEach(function (h) { htr.appendChild(el('th', null, h)); });
        thead.appendChild(htr);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        actions.forEach(function (a) {
            var item = a && typeof a === 'object' ? a : {};
            var tr = document.createElement('tr');
            tr.appendChild(el('td', null, deviceText(item.device)));
            tr.appendChild(el('td', null, actionText(item.action)));
            tr.appendChild(el('td', null, String(item.reason === undefined ? '' : item.reason)));
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        return table;
    }

    /** 确认下发预案 */
    function confirmPlan(id, okBtn, noBtn) {
        if (id === undefined || id === null) return;
        okBtn.disabled = true;
        noBtn.disabled = true;
        okBtn.textContent = '下发中...';
        fetchJSON('/api/plan/confirm', {
            method: 'POST',
            body: JSON.stringify({ id: Number(id) })
        }).then(function (data) {
            var applied = data && Array.isArray(data.applied) ? data.applied : [];
            var failed = data && Array.isArray(data.failed) ? data.failed : [];
            if (failed.length) {
                if (root.toast) root.toast('部分下发失败（' + failed.length + ' 项）', 'error');
            } else {
                if (root.toast) root.toast('预案已下发（' + applied.length + ' 项动作）', 'success');
            }
            okBtn.textContent = '已下发';
            if (currentPlan) currentPlan.status = 'confirmed';
            loadPlans();
        }).catch(function (e) {
            okBtn.disabled = false;
            noBtn.disabled = false;
            okBtn.textContent = '确认下发';
            fail('下发失败：' + e.message);
        });
    }

    /** 拒绝预案 */
    function rejectPlan(id, okBtn, noBtn) {
        if (id === undefined || id === null) return;
        var reason = root.prompt ? (root.prompt('请输入拒绝原因（可留空）', '') || '') : '';
        okBtn.disabled = true;
        noBtn.disabled = true;
        fetchJSON('/api/plan/reject', {
            method: 'POST',
            body: JSON.stringify({ id: Number(id), reason: reason })
        }).then(function () {
            if (root.toast) root.toast('预案已拒绝', 'success');
            noBtn.textContent = '已拒绝';
            if (currentPlan) currentPlan.status = 'rejected';
            loadPlans();
        }).catch(function (e) {
            okBtn.disabled = false;
            noBtn.disabled = false;
            fail('拒绝失败：' + e.message);
        });
    }

    /* ---------- Tab 5：节水减碳 ---------- */
    function loadMetrics() {
        var host = document.getElementById('insightMetricsBody');
        if (!host) return Promise.resolve();
        setState(host, '加载中...');
        return fetchJSON('/api/metrics?days=7').then(function (data) {
            var d = data && typeof data === 'object' ? data : {};
            host.textContent = '';

            // 4 张指标卡
            var cards = el('div', 'metric-cards');
            metricCards(d).forEach(function (c) {
                var card = el('div', 'metric-card');
                card.appendChild(el('div', 'metric-label', c.label));
                card.appendChild(el('div', 'metric-value', c.value));
                card.appendChild(el('div', 'metric-unit', c.unit));
                cards.appendChild(card);
            });
            host.appendChild(cards);

            // 逐日表格
            var rows = metricRows(d.series);
            if (rows.length) {
                host.appendChild(metricsTable(rows));
            } else {
                host.appendChild(el('div', 'insight-empty', emptyText('metrics')));
            }

            // 必须显示接口返回的 method 原文（工程估算，非实测）
            host.appendChild(el('div', 'metric-method',
                '估算口径（接口 method 原文）：' + String(d.method || '（接口未返回 method）')));

            // CSV 导出
            var exp = el('div', 'insight-export');
            exp.appendChild(exportLink('/api/export/history.csv', '导出历史数据 CSV'));
            exp.appendChild(exportLink('/api/export/alerts.csv', '导出告警记录 CSV'));
            host.appendChild(exp);
        }).catch(function (e) {
            setState(host, '指标加载失败：' + e.message, 'error');
            fail('指标加载失败：' + e.message);
        });
    }

    /** 逐日指标表格 */
    function metricsTable(rows) {
        var table = el('table', 'insight-table');
        var cols = [
            ['day', '日期'], ['water_liters', '用水量 L'], ['pump_minutes', '水泵 min'],
            ['air_minutes', '增氧 min'], ['ch4_saved_g', 'CH₄ 减排 g'], ['co2e_saved_g', 'CO₂e 减排 g']
        ];
        var thead = document.createElement('thead');
        var htr = document.createElement('tr');
        cols.forEach(function (c) { htr.appendChild(el('th', null, c[1])); });
        thead.appendChild(htr);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        rows.forEach(function (r) {
            var tr = document.createElement('tr');
            cols.forEach(function (c, i) {
                tr.appendChild(el('td', i === 0 ? null : 'num', r[c[0]]));
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        return table;
    }

    /** CSV 导出链接（<a download> 直接触发，浏览器带会话 Cookie） */
    function exportLink(href, text) {
        var a = document.createElement('a');
        a.href = href;
        a.setAttribute('download', '');
        a.textContent = text;
        return a;
    }

    /* ---------- Tab 切换与开关 ---------- */
    /* plans Tab 只拉历史列表，生成预案由「生成预案」按钮显式触发 */
    var LOADERS = {
        alerts: loadAlerts,
        logs: loadLogs,
        device: loadDeviceStatus,
        plans: loadPlans,
        metrics: loadMetrics
    };

    var loaded = {};   // 记录本次打开已加载过的 Tab，避免重复拉取

    /** 切到某个 Tab 并（首次）拉数据 */
    function showTab(name) {
        if (!Object.prototype.hasOwnProperty.call(LOADERS, name)) return;
        activateTab(name);
        if (!loaded[name]) {
            loaded[name] = true;
            LOADERS[name]();
        }
    }

    /** 手动刷新当前 Tab */
    function refreshCurrent() {
        var active = document.querySelector('.insight-tab.active');
        var name = active ? active.getAttribute('data-tab') : 'alerts';
        if (Object.prototype.hasOwnProperty.call(LOADERS, name)) LOADERS[name]();
    }

    /** 打开面板：重置状态并拉第一个 Tab */
    function openInsight() {
        loaded = {};
        currentPlan = null;
        var cur = document.getElementById('insightPlanCurrent');
        if (cur) setState(cur, '点击「生成预案」，AI 会结合当前水位、土壤湿度、RORI 与降雨预报给出调控建议。');
        showTab('alerts');
        if (root.openModal) root.openModal('insightModal');
    }

    /** 关闭面板：清理状态（无定时器常驻，故无需 clearInterval） */
    function closeInsight() {
        loaded = {};
        currentPlan = null;
        if (root.closeModal) root.closeModal('insightModal');
    }

    /** 绑定 Tab 点击、生成按钮、关闭按钮 */
    function bind() {
        var tabs = document.querySelectorAll('.insight-tab');
        for (var i = 0; i < tabs.length; i++) {
            (function (btn) {
                btn.addEventListener('click', function () {
                    showTab(btn.getAttribute('data-tab'));
                });
            })(tabs[i]);
        }
        var propose = document.getElementById('insightProposeBtn');
        if (propose) propose.addEventListener('click', proposePlan);
        var ackAll = document.getElementById('insightAckAllBtn');
        if (ackAll) ackAll.addEventListener('click', function () { ackAllAlerts(ackAll); });
        var refresh = document.getElementById('insightRefreshBtn');
        if (refresh) refresh.addEventListener('click', refreshCurrent);
        var close = document.getElementById('insightCloseBtn');
        if (close) close.addEventListener('click', closeInsight);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }

    // 供模板内联 onclick 调用
    root.openInsight = openInsight;
    root.closeInsight = closeInsight;
    root.Insight = {
        open: openInsight, close: closeInsight, showTab: showTab,
        loadAlerts: loadAlerts, loadLogs: loadLogs, loadDeviceStatus: loadDeviceStatus,
        loadMetrics: loadMetrics, loadPlans: loadPlans, proposePlan: proposePlan,
        ackAllAlerts: ackAllAlerts,
        refreshCurrent: refreshCurrent
    };
})(typeof globalThis !== 'undefined' ? globalThis : this);
