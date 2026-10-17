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
        if (S.cloudConnected && S.deviceOnline) {
            QH.toggleClass(sensorPanel, 'panel-disabled', false);
            QH.toggleClass(controlPanel, 'panel-disabled', false);
            QH.setText(roriStatus, '数据同步计算中...');
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
        if (!S.cloudConnected || !S.deviceOnline) {
            QH.setText(QH.$('roriDisplay'), '--');
            QH.setText(QH.$('roriStatus'), '设备离线');
            S.currentRori = null;
            return;
        }
        var roriValue = root.computeRori(S.waterAdc, S.soilAdc, S.ehValue, S.doValue);
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
     * 由统一 tick 每 5s 调用一次（阈值取自 core.js 的 heartbeatMissLimit，默认 4 次）。
     */
    function watchHeartbeat() {
        if (S.dataReceived) {
            S.heartbeatMiss = 0;
            S.deviceOnline = true;
            S.dataReceived = false;
        } else {
            S.heartbeatMiss += 1;
            if (S.heartbeatMiss >= S.heartbeatMissLimit) S.deviceOnline = false;
        }
        refreshStatus();
    }

    /* ---------------- 告警 ---------------- */
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
            var key = it.msg;
            if (S.alertCoolDown[key] && now - S.alertCoolDown[key] < 60000) return;
            S.alertCoolDown[key] = now;
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
                    S.deviceOnline = false;
                    root.addLog('设备断开连接', 'log-danger');
                }
                QH.enqueueFlag('refreshStatus', true);
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

    root.QH_REALTIME = {
        refreshStatus: refreshStatus,
        updateRori: updateRori,
        autoControl: autoControl,
        watchHeartbeat: watchHeartbeat,
        checkAlerts: checkAlerts,
        recordAlert: recordAlert,
        initSocket: initSocket,
        sendAutoCommand: sendAutoCommand,
        sendManualCommand: sendManualCommand
    };

    root.refreshStatus = refreshStatus;
    root.updateRori = updateRori;
    root.checkAlerts = checkAlerts;
    root.recordAlert = recordAlert;
    root.sendManualCommand = sendManualCommand;
})(typeof globalThis !== 'undefined' ? globalThis : this);
