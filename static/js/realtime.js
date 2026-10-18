/* ============================================================
 * realtime.js — SocketIO 连接 / 消息分发 / 状态刷新 / RORI 与告警巡检
 * 治理点：
 *   1) 每条 MQTT 消息不再直接写 DOM + updateRori + pushChartPoint，
 *      而是解析后只更新内存态 + 入 DOM 队列，由统一 tick 合并刷写；
 *   2) 心跳检测并入统一 tick（5s 分频），不再单独 setInterval。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var S = root.S;

    /* ---------------- 状态刷新 ---------------- */
    /** 顶栏连接状态 + 面板可用性 */
    function refreshStatus() {
        var cloudEl = QH.$('cloudStatus');
        var deviceEl = QH.$('deviceStatusPill');
        if (cloudEl) {
            cloudEl.textContent = '';
            var d1 = document.createElement('span');
            d1.className = 'status-dot ' + (S.cloudConnected ? 'dot-green' : 'dot-red');
            cloudEl.appendChild(d1);
            cloudEl.appendChild(document.createTextNode('华为云：' + (S.cloudConnected ? '已连接' : '未连接')));
        }
        if (deviceEl) {
            deviceEl.textContent = '';
            var d2 = document.createElement('span');
            d2.className = 'status-dot ' + (S.deviceOnline ? 'dot-green' : 'dot-red');
            deviceEl.appendChild(d2);
            deviceEl.appendChild(document.createTextNode('传感器：' + (S.deviceOnline ? '已连接' : '未连接')));
        }

        var sensorPanel = QH.$('sensorPanel');
        var controlPanel = QH.$('controlPanel');
        var roriStatus = QH.$('roriStatus');

        // 面板可用性：socket 已连接即可操作（命令经 MQTT 真实下发到设备）
        var wsConnected = !!(S.socket && S.socket.connected);
        if (S.deviceOnline) {
            QH.toggleClass(sensorPanel, 'panel-disabled', false);
            QH.toggleClass(controlPanel, 'panel-disabled', false);
            // roriStatus 的等级文案由 updateRori() 统一写；若上一帧离线时留下的旧文案
            // 还在，这里补算一次，避免出现「有 RORI 数值却写着设备未连接」。
            if (roriStatus && /未连接|离线|同步计算中/.test(roriStatus.textContent || '')) updateRori();
        } else if (wsConnected) {
            QH.toggleClass(sensorPanel, 'panel-disabled', false);
            QH.toggleClass(controlPanel, 'panel-disabled', false);
            QH.setText(roriStatus, '设备未连接，等待 MQTT 数据');
        } else {
            QH.toggleClass(sensorPanel, 'panel-disabled', true);
            QH.toggleClass(controlPanel, 'panel-disabled', true);
            QH.setText(QH.$('waterDisplay'), '--');
            QH.setText(QH.$('soilDisplay'), '--');
            QH.setText(QH.$('doDisplay'), '--');
            QH.setText(QH.$('ehDisplay'), '--');
            QH.setText(QH.$('deviceStatus'), '无信号');
            QH.setText(QH.$('waterPumpStatus'), '无信号');
            QH.setText(QH.$('roriDisplay'), '--');
            QH.setText(roriStatus, '设备离线');
            QH.toggleClass(QH.$('ongoingAlertBanner'), 'hidden', true);
        }
    }

    /* ---------------- RORI ---------------- */
    /** 计算并展示 RORI，同时在自动模式下执行调控决策 */
    function updateRori() {
        // 只要有设备数据就算得出 RORI；华为云 MQTT 链路状态不参与此判断，
        // 否则「服务端有遥测但 broker 未连」时刷新页面会看不到风险值。
        if (!S.deviceOnline) {
            QH.setText(QH.$('roriDisplay'), '--');
            QH.setText(QH.$('roriStatus'), '设备离线');
            S.currentRori = null;
            return;
        }
        // 参数顺序与后端 compute_rori 一致：(水位, 土壤, 溶解氧, 氧化还原电位)
        var roriValue = root.computeRori(S.waterAdc, S.soilAdc, S.doValue, S.ehValue);
        var level = root.classifyRori(roriValue);
        S.currentRori = roriValue;

        var roriEl = QH.$('roriDisplay');
        var statusEl = QH.$('roriStatus');
        var alertBanner = QH.$('ongoingAlertBanner');
        QH.setText(roriEl, roriValue.toFixed(2));
        var levelName = level.name, cmdCode = level.code, strategy = level.strategy;

        if (cmdCode >= 2) {
            QH.setStyle(roriEl, 'color', '#B84A4A');
            QH.setStyle(statusEl, 'color', '#B84A4A');
        } else if (cmdCode >= 1) {
            QH.setStyle(roriEl, 'color', '#C8903F');
            QH.setStyle(statusEl, 'color', '#C8903F');
        } else {
            QH.setStyle(roriEl, 'color', '#1F6B45');
            QH.setStyle(statusEl, 'color', '#6B7A72');
        }

        // 状态说明：等级名 + 策略（DOM 节点构建，避免 innerHTML 拼接）
        if (statusEl) {
            var prev = statusEl.getAttribute('data-level');
            if (prev !== String(cmdCode)) {
                statusEl.setAttribute('data-level', String(cmdCode));
                statusEl.textContent = '';
                statusEl.appendChild(document.createTextNode(levelName));
                statusEl.appendChild(document.createElement('br'));
                var sp = document.createElement('span');
                sp.style.fontSize = '12px';
                sp.style.fontWeight = '400';
                sp.textContent = strategy;
                statusEl.appendChild(sp);
            }
        }

        if (cmdCode > 0) {
            QH.setText(alertBanner, 'RORI 预警：当前【' + levelName + '】，' + strategy);
            QH.toggleClass(alertBanner, 'hidden', false);
            QH.setStyle(alertBanner, 'backgroundColor', (cmdCode === 2) ? '#B84A4A' : '#C8903F');
        } else if (alertBanner && (alertBanner.textContent || '').indexOf('RORI') >= 0) {
            QH.toggleClass(alertBanner, 'hidden', true);
        }

        if (!S.manualMode) autoControl(cmdCode);
    }

    /** 自动调控：气泵按 RORI 分级 + 水泵按水位/降雨前馈 */
    function autoControl(cmdCode) {
        var dt = root.computeDynamicThreshold();

        // 气泵按 RORI 分级自动开关；预测有降雨前馈时提前一级增氧（前馈防御性加气）
        // 状态去重：仅状态变化才下发，避免高频事件下重复刷指令
        var effCmd = cmdCode;
        if (dt.rainComing && effCmd < 2) effCmd += 1;
        var airNew = (effCmd >= 1) ? 'ON' : 'OFF';
        if (S.airPumpAutoState !== airNew) {
            S.airPumpAutoState = airNew;
            sendAutoCommand('air_pump', airNew);
        }

        // 水泵：降雨前馈控水等雨 —— 预测有雨时暂缓补水，留存天然降雨（说明书 3.4）
        var wlDown = parseInt((QH.$('waterlevelDownInput') || {}).value, 10) || 30;
        var wlUp = parseInt((QH.$('waterlevelUpInput') || {}).value, 10) || 150;
        var water = parseFloat(S.currentWaterLevel) || 0;
        var pumpCmd = '';
        if (water < wlDown) {
            if (dt.rainComing) {
                if (S.pumpAutoState !== 'hold') {
                    S.pumpAutoState = 'hold';
                    root.addLog('[前馈] 预测 6 日降雨 P6d=' + dt.P6d.toFixed(1) + 'mm，暂缓水泵补水以留存天然降雨', 'log-info');
                    root.recordAlert('warn', '预测降雨 ' + dt.P6d.toFixed(1) + 'mm，暂缓补水留存降雨');
                }
            } else if (S.pumpAutoState !== 'on') {
                S.pumpAutoState = 'on';
                pumpCmd = 'ON';
                root.addLog('[自动] 水位 ' + water + 'mm < 下限 ' + wlDown + 'mm，自动开启水泵灌水', 'log-info');
                root.recordAlert('warn', '水位偏低 ' + water + 'mm，自动开启水泵灌水');
            }
        } else if (water > wlUp) {
            if (S.pumpAutoState !== 'off') {
                S.pumpAutoState = 'off';
                pumpCmd = 'OFF';
                root.addLog('[自动] 水位 ' + water + 'mm > 上限 ' + wlUp + 'mm，自动关闭水泵', 'log-safe');
                root.recordAlert('warn', '水位偏高 ' + water + 'mm，自动关闭水泵');
            }
        } else {
            if (S.pumpAutoState !== 'ok') S.pumpAutoState = 'ok';
        }
        if (pumpCmd) sendAutoCommand('water_pump', pumpCmd);
    }

    /* ---------------- 心跳 ---------------- */
    /**
     * 在线检测增加冗余：连续丢心跳达 S.heartbeatMissLimit 次才判离线，单次/偶发丢包不误判。
     * 由统一 tick 每 5s 调用一次，阈值取自 core.js 的 heartbeatMissLimit（6 次 = 30s），
     * 与后端 heartbeat.DEVICE_OFFLINE_SECONDS = 30 对齐，前后端离线判定一致。
     */
    /** 最近一次服务端快照是否还新鲜（秒） */
    function snapshotFresh(seconds) {
        return !!S.lastSnapshotAt && (Date.now() - S.lastSnapshotAt) < (seconds || 25) * 1000;
    }

    function watchHeartbeat() {
        // 刷新后没有 MQTT 事件流，靠服务端快照维持在线态；快照过期就再拉一次，
        // 这样「设备有数据、只是没连 MQTT」时不会误报离线。
        if (snapshotFresh()) {
            S.heartbeatMiss = 0;
            S.deviceOnline = true;
            refreshStatus();
            return;
        }
        if (S.dataReceived) {
            S.heartbeatMiss = 0;
            S.deviceOnline = true;
            S.dataReceived = false;
        } else {
            S.heartbeatMiss += 1;
            if (S.heartbeatMiss >= S.heartbeatMissLimit) S.deviceOnline = false;
            if (!S.deviceOnline) loadLatest();
        }
        refreshStatus();
    }

    /* ---------------- 告警 ---------------- */
    /**
     * 告警降噪：把「同一条事实」的连续重复压成一条。
     *
     * 原实现按 `msg` 全文去重，而告警正文里带着实时数值（水位 29.8mm / 30.1mm），
     * 阈值附近抖动时每条都算「新消息」，60 秒冷却形同虚设——极短时间内就会
     * 刷出一屏相似告警并反复弹 toast。
     *
     * 现在把正文里的数字统一抹成 `#` 再作指纹，并叠加两道闸门：
     *   1) 冷却窗口 `ALERT_COOLDOWN_MS`（同一指纹内只放行一次）；
     *   2) 全局最小间隔 `ALERT_MIN_GAP_MS`（任何告警之间都要拉开，防连环刷屏）。
     */
    var ALERT_COOLDOWN_MS = 60000;   // 同一指纹 60s 内只报一次
    var ALERT_MIN_GAP_MS = 3000;     // 任意两条告警之间至少间隔 3s

    /** 正文归一化：压空白 + 抹掉数字，得到「同一件事」的指纹 */
    function alertFingerprint(msg) {
        return String(msg === undefined || msg === null ? '' : msg)
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/\d+(?:\.\d+)?/g, '#')
            .slice(0, 120);
    }

    /**
     * 是否应当把这条告警呈现给用户。
     *
     * 纯函数式地读写传入的冷却表，便于单测；返回 false 表示本次被抑制。
     * @param {string} msg 告警正文
     * @param {number} now 当前毫秒时间戳
     * @param {Object} table 冷却表（会被就地更新）
     */
    function shouldEmitAlert(msg, now, table) {
        var store = table || S.alertCoolDown;
        var key = alertFingerprint(msg);
        if (!key) return false;
        var lastSame = store[key];
        if (lastSame && now - lastSame < ALERT_COOLDOWN_MS) return false;
        var lastAny = store.__last || 0;
        if (lastAny && now - lastAny < ALERT_MIN_GAP_MS) return false;
        store[key] = now;
        store.__last = now;
        return true;
    }

    /** 阈值越限与告警检测（统一 tick 5s 一次） */
    function checkAlerts() {
        if (!S.deviceOnline) return;
        var items = [];
        var now = Date.now();
        // 水位阈值（渠道水位 mm）
        var wlUp = parseInt((QH.$('waterlevelUpInput') || {}).value, 10) || 150;
        // 土壤湿度阈值（%RH）—— 与降雨前馈动态阈值融合
        var dt = root.computeDynamicThreshold();
        var humiDown = dt.hasForecast ? dt.effLower : (parseInt((QH.$('humiDownInput') || {}).value, 10) || 40);
        var humiUp = dt.hasForecast ? dt.effUpper : (parseInt((QH.$('humiUpInput') || {}).value, 10) || 80);
        var soil = parseFloat(S.currentSoilMoisture) || 0;
        var water = parseFloat(S.currentWaterLevel) || 0;

        if (soil < humiDown) {
            items.push({
                level: 'warn',
                msg: '土壤湿度过低 ' + soil + '% < 动态下限 ' + humiDown.toFixed(1) + '%'
                    + (dt.rainComing ? '（降雨前馈控水等雨）' : '') + '，建议补灌'
            });
        } else if (soil > humiUp) {
            items.push({ level: 'warn', msg: '土壤湿度过高 ' + soil + '% > 动态上限 ' + humiUp.toFixed(1) + '%，注意排湿' });
        }
        if (water > wlUp) {
            items.push({ level: 'warn', msg: '水位过高 ' + water + 'mm > 上限 ' + wlUp + 'mm，注意排水' });
        }

        // RORI 预警：读内存态，避免依赖尚未刷写的 DOM 文本
        var rori = (typeof S.currentRori === 'number') ? S.currentRori : 0;
        if (rori >= 70) items.push({ level: 'danger', msg: 'RORI ' + rori.toFixed(0) + ' 重度厌氧，强制增氧' });
        else if (rori >= 40) items.push({ level: 'warn', msg: 'RORI ' + rori.toFixed(0) + ' 中度缺氧，脉冲加气' });

        items.forEach(function (it) {
            if (!shouldEmitAlert(it.msg, Date.now(), S.alertCoolDown)) return;
            root.recordAlert(it.level, it.msg);
        });
    }

    /** 记录一条告警：内存态追加 + 增量渲染 + webhook 转发 */
    function recordAlert(level, msg) {
        root.QH_STORE.pushAlert(level, msg);
        if (root.renderAlerts) root.renderAlerts(true);
        QH.toast('⚠ ' + msg, level);
        // 通过后端转发到用户配置的 webhook（钉钉/企业微信等）
        try {
            fetch('/api/notify_alert', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ level: level, msg: msg })
            }).catch(function () { /* 告警转发失败不影响页面 */ });
        } catch (e) { /* fetch 不可用时忽略 */ }
    }
    /* ---------------- SocketIO ---------------- */
    function initSocket() {
        if (typeof io === 'undefined') return;
        S.socket = io();

        S.socket.on('connect', function () {
            root.addLog('云服务连接成功');
            QH.enqueueFlag('refreshStatus', true);
        });

        S.socket.on('hw_data', function (d) {
            if (!d || typeof d !== 'object') return;

            if (d.type === 'device_status') {
                if (d.status === 'online') {
                    S.cloudConnected = true;
                } else {
                    S.cloudConnected = false;
                    // 服务端心跳判定与前端快照可能有时差：快照还新鲜就只标记 broker 断开，
                    // 不把「有数据」误判成设备离线。
                    if (!snapshotFresh()) S.deviceOnline = false;
                    root.addLog('设备断开连接', 'log-danger');
                }
                refreshStatus();
                updateRori();
                return;
            }

            if (d.type !== 'data' || !S.cloudConnected) return;

            var topic = d.topic;
            var payload = d.payload;
            var jsonObj = null;
            try { jsonObj = JSON.parse(payload); } catch (e) { /* payload 可能是纯数字 */ }

            /** payload 可能是纯数字，也可能是一整个 JSON 对象，两种情况都兼容 */
            function pickValue(key) {
                if (jsonObj && typeof jsonObj === 'object' && jsonObj[key] !== undefined) return jsonObj[key];
                return payload;
            }
            function markAlive() {
                S.dataReceived = true;
                S.deviceOnline = true;
            }

            if (topic === 'waterlevel' || (jsonObj && jsonObj.waterlevel !== undefined)) {
                // 探针式水位，ADC 越高水越深，满量程 4095 对应约 300mm
                var adc = parseFloat(pickValue('waterlevel')) || 0;
                S.waterAdc = adc;
                S.currentWaterLevel = Math.max(0, Math.min(Math.round(adc / 4095 * 300), 300));
                QH.enqueueField('waterDisplay', String(S.currentWaterLevel));
                markAlive();
            } else if (topic === 'humidity' || (jsonObj && jsonObj.humidity !== undefined)) {
                // 电容式土壤湿度，ADC 越高越干，换算成 0~100% 湿润度
                var sadc = parseFloat(pickValue('humidity')) || 0;
                S.soilAdc = sadc;
                S.currentSoilMoisture = Math.max(0, Math.min(Math.round((4095 - sadc) / 4095 * 100), 100));
                QH.enqueueField('soilDisplay', String(S.currentSoilMoisture));
                markAlive();
            } else if (topic === 'do' || (jsonObj && jsonObj.do !== undefined)) {
                // 根区溶解氧含量：固件上报 mg/L 数值，范围 0~20mg/L
                var doRaw = parseFloat(pickValue('do')) || 0;
                S.doValue = Math.max(0, Math.min(doRaw, 20));
                QH.enqueueField('doDisplay', S.doValue.toFixed(1));
                markAlive();
            } else if (topic === 'eh' || (jsonObj && jsonObj.eh !== undefined)) {
                // 根区氧化还原电位：固件上报 mV 数值，范围 -150~300mV
                var ehRaw = parseFloat(pickValue('eh')) || 0;
                S.ehValue = Math.max(-150, Math.min(ehRaw, 300));
                QH.enqueueField('ehDisplay', String(Math.round(S.ehValue)));
                markAlive();
            } else if (topic === 'water_pump' || (jsonObj && jsonObj.water_pump !== undefined)) {
                QH.enqueuePump('waterPumpStatus', pickValue('water_pump'));
                markAlive();
            } else if (topic === 'air_pump' || (jsonObj && jsonObj.air_pump !== undefined)) {
                QH.enqueuePump('deviceStatus', pickValue('air_pump'));
                markAlive();
            } else if (topic === 'humi_up' || (jsonObj && jsonObj.humi_up !== undefined)) {
                QH.enqueueSlider('humi', 'up', pickValue('humi_up'));
            } else if (topic === 'humi_down' || (jsonObj && jsonObj.humi_down !== undefined)) {
                QH.enqueueSlider('humi', 'down', pickValue('humi_down'));
            } else if (topic === 'waterlevel_up' || (jsonObj && jsonObj.waterlevel_up !== undefined)) {
                QH.enqueueSlider('waterlevel', 'up', pickValue('waterlevel_up'));
            } else if (topic === 'waterlevel_down' || (jsonObj && jsonObj.waterlevel_down !== undefined)) {
                QH.enqueueSlider('waterlevel', 'down', pickValue('waterlevel_down'));
            } else if (topic === 'log') {
                var text = String(payload);
                if (text.indexOf('QB_ON') >= 0) {
                    QH.enqueuePump('deviceStatus', 'on');
                } else if (text.indexOf('QB_OFF') >= 0) {
                    QH.enqueuePump('deviceStatus', 'off');
                } else if (text.indexOf('SB_ON') >= 0) {
                    QH.enqueuePump('waterPumpStatus', 'on');
                } else if (text.indexOf('SB_OFF') >= 0) {
                    QH.enqueuePump('waterPumpStatus', 'off');
                } else {
                    root.addLog('[设备] ' + text, 'log-info');
                }
            }

            // 合并到统一 tick：状态刷新 / RORI / 图表 / 告警，全部去抖批量执行
            QH.enqueueFlag('refreshStatus', true);
            QH.enqueueFlag('rori', true);
            QH.enqueueFlag('chart', true);
            QH.enqueueFlag('alerts', true);
        });

        S.socket.on('disconnect', function () {
            S.cloudConnected = false;
            S.deviceOnline = false;
            root.addLog('服务器断开', 'log-danger');
            QH.enqueueFlag('refreshStatus', true);
        });
    }

    /* ---------------- 指令下发 ---------------- */
    function sendAutoCommand(device, action) {
        if (S.socket && S.socket.connected) {
            S.socket.emit('send_command', { device: device, action: action.toLowerCase() });
        }
    }

    /** 手动指令（模板内联 onclick 调用） */
    function sendManualCommand(device, action) {
        if (S.socket && S.socket.connected) {
            S.socket.emit('send_command', { device: device, action: action.toLowerCase() });
            root.addLog('[手动] 指令: ' + (device === 'air_pump' ? '气泵' : '水泵') + ' ➡️ ' + action.toLowerCase(), 'log-info');
        } else {
            alert('设备未在线，无法发送指令');
        }
    }

    /**
     * 用服务端最新遥测快照恢复看板读数。
     *
     * 刷新页面 / 手机切回前台时，SocketIO 不会重放历史事件，若不补这一帧，
     * 四路读数会停在「--」，而下方图表与七日建议却已有数据，看起来像设备掉线。
     */
    function applySnapshot(data) {
        if (!data || data.status !== 'success' || !data.has_telemetry) return false;
        var applied = false;
        if (typeof data.water_adc === 'number') {
            S.waterAdc = data.water_adc;
            S.currentWaterLevel = Math.max(0, Math.min(Math.round(data.water_mm), 300));
            QH.enqueueField('waterDisplay', String(S.currentWaterLevel));
            applied = true;
        }
        if (typeof data.soil_adc === 'number') {
            S.soilAdc = data.soil_adc;
            S.currentSoilMoisture = Math.max(0, Math.min(Math.round(data.soil_pct), 100));
            QH.enqueueField('soilDisplay', String(S.currentSoilMoisture));
            applied = true;
        }
        if (typeof data.do_mgl === 'number') {
            S.doValue = Math.max(0, Math.min(data.do_mgl, 20));
            QH.enqueueField('doDisplay', S.doValue.toFixed(1));
            applied = true;
        }
        if (typeof data.eh_mv === 'number') {
            S.ehValue = Math.max(-150, Math.min(data.eh_mv, 300));
            QH.enqueueField('ehDisplay', String(Math.round(S.ehValue)));
            applied = true;
        }
        if (data.air_pump) QH.enqueuePump('deviceStatus', data.air_pump);
        if (data.water_pump) QH.enqueuePump('waterPumpStatus', data.water_pump);
        if (applied) {
            // 记录快照时间：服务端有新鲜数据即视为设备在线（MQTT 链路状态单独看顶部胶囊）
            S.lastSnapshotAt = Date.now();
            S.dataReceived = true;
            S.deviceOnline = true;
            S.heartbeatMiss = 0;
            // 先刷连接状态再算 RORI：refreshStatus 会把离线文案写回状态位，
            // 顺序反了会把刚算出的等级名覆盖掉。
            refreshStatus();
            updateRori();
        }
        return applied;
    }

    /** 拉一次服务端快照并套用；失败静默（等 MQTT 首帧即可） */
    function loadLatest() {
        return fetch('/api/telemetry').then(function (r) {
            if (!r.ok) throw new Error('http ' + r.status);
            return r.json();
        }).then(applySnapshot).catch(function () { return false; });
    }

    root.QH_REALTIME = {
        refreshStatus: refreshStatus,
        updateRori: updateRori,
        autoControl: autoControl,
        watchHeartbeat: watchHeartbeat,
        checkAlerts: checkAlerts,
        recordAlert: recordAlert,
        initSocket: initSocket,
        sendAutoCommand: sendAutoCommand,
        sendManualCommand: sendManualCommand,
        applySnapshot: applySnapshot,
        loadLatest: loadLatest,
        alertFingerprint: alertFingerprint,
        shouldEmitAlert: shouldEmitAlert,
        ALERT_COOLDOWN_MS: ALERT_COOLDOWN_MS,
        ALERT_MIN_GAP_MS: ALERT_MIN_GAP_MS
    };

    root.refreshStatus = refreshStatus;
    root.updateRori = updateRori;
    root.checkAlerts = checkAlerts;
    root.recordAlert = recordAlert;
    root.sendManualCommand = sendManualCommand;

    // node 单测出口：浏览器下无 module，静默跳过
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            alertFingerprint: alertFingerprint,
            shouldEmitAlert: shouldEmitAlert,
            ALERT_COOLDOWN_MS: ALERT_COOLDOWN_MS,
            ALERT_MIN_GAP_MS: ALERT_MIN_GAP_MS
        };
    }
})(typeof globalThis !== 'undefined' ? globalThis : this);
