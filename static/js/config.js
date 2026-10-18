/* ============================================================
 * config.js — 配置弹窗读写 / 阈值滑块 / 模式切换 / 改密
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var S = root.S;

    /* ---------------- 滑块 ---------------- */
    /**
     * 双滑杆「已选区间」几何：把两个数值换算成轨道上的百分比。
     * 纯函数，无 DOM 依赖，供 QH_CONFIG 导出并被 node 测试直接调用。
     * @param {number|string} lower 下限
     * @param {number|string} upper 上限
     * @param {number} [min=0] 量程最小值
     * @param {number} [max=100] 量程最大值
     * @returns {{left:number,width:number}} left/width 均为 0–100 的百分比
     */
    function dualRangeGeometry(lower, upper, min, max) {
        var lo0 = isFinite(parseFloat(min)) ? parseFloat(min) : 0;
        var hi0 = isFinite(parseFloat(max)) ? parseFloat(max) : 100;
        if (hi0 <= lo0) hi0 = lo0 + 1;
        var span = hi0 - lo0;
        var toPct = function (v, fallback) {
            var n = parseFloat(v);
            if (!isFinite(n)) n = fallback;
            n = Math.min(hi0, Math.max(lo0, n));
            return (n - lo0) / span * 100;
        };
        var a = toPct(lower, lo0);
        var b = toPct(upper, hi0);
        if (b < a) { var t = a; a = b; b = t; }
        return { left: a, width: b - a };
    }

    /**
     * 把「已选区间」高亮条写到对应的 .dual-range-fill 上。
     * 节点缺失时静默返回，便于 node/无 DOM 环境复用。
     * @param {string} downId 下限 input 的 id
     * @param {string} upId 上限 input 的 id
     */
    function updateDualRangeFill(downId, upId) {
        var d = QH.$(downId), u = QH.$(upId);
        if (!d || !u) return;
        var box = d.parentNode;
        var fill = box && box.querySelector ? box.querySelector('.dual-range-fill') : null;
        if (!fill) return;
        var geo = dualRangeGeometry(d.value, u.value, d.min, d.max);
        fill.style.left = geo.left + '%';
        fill.style.width = geo.width + '%';
    }

    /** 土壤湿度双滑块联动（下限不得越过上限） */
    function onHumiditySlider(type) {
        var d = QH.$('humiDownInput'), u = QH.$('humiUpInput');
        if (!d || !u) return;
        var dv = parseInt(d.value, 10);
        var uv = parseInt(u.value, 10);
        if (type === 'down' && dv > uv) { d.value = uv; }
        if (type === 'up' && uv < dv) { u.value = dv; }
        QH.setText(QH.$('humiDownVal'), d.value);
        QH.setText(QH.$('humiUpVal'), u.value);
        updateDualRangeFill('humiDownInput', 'humiUpInput');
        root.updateThresholdFusionHint();
    }

    /** 渠道水位双滑块联动 */
    function onWaterLevelSlider(type) {
        var d = QH.$('waterlevelDownInput'), u = QH.$('waterlevelUpInput');
        if (!d || !u) return;
        var dv = parseInt(d.value, 10);
        var uv = parseInt(u.value, 10);
        if (type === 'down' && dv > uv) { d.value = uv; }
        if (type === 'up' && uv < dv) { u.value = dv; }
        QH.setText(QH.$('waterlevelDownVal'), d.value);
        QH.setText(QH.$('waterlevelUpVal'), u.value);
        updateDualRangeFill('waterlevelDownInput', 'waterlevelUpInput');
        root.updateThresholdFusionHint();
    }

    /* ---------------- 配置弹窗 ---------------- */
    var CONFIG_FIELDS = {
        cfgFarmLng: 'farm_lng', cfgFarmLat: 'farm_lat', cfgFarmName: 'farm_name',
        cfgIotHost: 'iot_host', cfgIotDeviceId: 'iot_device_id',
        cfgTargetDeviceId: 'iot_target_device_id', cfgIotClientId: 'iot_client_id',
        cfgIotUser: 'iot_user', cfgIotPass: 'iot_pass',
        cfgWeatherDomain: 'weather_domain', cfgWeatherKey: 'weather_key',
        cfgAiDomain: 'ai_domain', cfgAiKey: 'ai_key', cfgWebhookUrl: 'webhook_url'
    };
    var CONFIG_DEFAULTS = { cfgM2mTopic: '/esp32e/data', cfgCmdTopic: '/esp32e/cmd' };

    /** 读取后端配置并回填表单，随后刷新天气/预报 */
    function loadConfig() {
        return fetch('/api/get_config').then(function (r) { return r.json(); }).then(function (data) {
            if (data.error) return;
            S.config = data;
            Object.keys(CONFIG_FIELDS).forEach(function (id) {
                var el = QH.$(id);
                if (el) el.value = data[CONFIG_FIELDS[id]] || '';
            });
            Object.keys(CONFIG_DEFAULTS).forEach(function (id) {
                var el = QH.$(id);
                if (el) el.value = data[CONFIG_DEFAULTS[id]] || CONFIG_DEFAULTS[id];
            });
            root.fetchWeather();
            root.fetchForecast();
        }).catch(function () { /* 后端不可用时保留表单默认值 */ });
    }

    /** 保存配置到后端 */
    function saveConfig() {
        var payload = {};
        Object.keys(CONFIG_FIELDS).forEach(function (id) {
            var el = QH.$(id);
            payload[CONFIG_FIELDS[id]] = el ? el.value : '';
        });
        var m2m = QH.$('cfgM2mTopic'), cmd = QH.$('cfgCmdTopic');
        payload.iot_m2m_topic = m2m ? m2m.value : '';
        payload.iot_cmd_topic = cmd ? cmd.value : '';
        return fetch('/api/save_config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (r) { return r.json(); }).then(function (data) {
            alert(data.message);
            if (data.status === 'success') { QH.closeModal('configModal'); loadConfig(); }
        }).catch(function () {
            alert('保存失败，请检查后端是否在线');
        });
    }

    /** 修改密码 */
    function changePassword() {
        var oldEl = QH.$('oldPassword'), newEl = QH.$('newPassword'), cfmEl = QH.$('confirmPassword');
        var oldPw = oldEl ? oldEl.value : '';
        var newPw = newEl ? newEl.value : '';
        var confirmPw = cfmEl ? cfmEl.value : '';
        if (!oldPw || !newPw) { alert('请输入原密码与新密码'); return; }
        if (newPw !== confirmPw) { alert('两次输入的新密码不一致'); return; }
        fetch('/api/change_password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_password: oldPw, new_password: newPw })
        }).then(function (r) { return r.json(); }).then(function (data) {
            alert(data.message);
            if (data.status === 'success') window.location.href = '/api/logout';
        }).catch(function () {
            alert('修改失败，请检查后端是否在线');
        });
    }

    /* ---------------- 阈值与模式 ---------------- */
    /** 页面加载时读取后端保存的阈值与模式设定 */
    function loadThreshSettings() {
        return fetch('/api/thresh_settings').then(function (r) { return r.json(); }).then(function (d) {
            if (d.error) return;
            var setVal = function (id, v) { var el = QH.$(id); if (el) el.value = v; };
            setVal('humiDownInput', d.humi_down);
            setVal('humiUpInput', d.humi_up);
            setVal('waterlevelDownInput', d.waterlevel_down);
            setVal('waterlevelUpInput', d.waterlevel_up);
            QH.setText(QH.$('humiDownVal'), d.humi_down);
            QH.setText(QH.$('humiUpVal'), d.humi_up);
            QH.setText(QH.$('waterlevelDownVal'), d.waterlevel_down);
            QH.setText(QH.$('waterlevelUpVal'), d.waterlevel_up);
            updateDualRangeFill('humiDownInput', 'humiUpInput');
            updateDualRangeFill('waterlevelDownInput', 'waterlevelUpInput');
            root.updateThresholdFusionHint();
            // 恢复模式：若后端存的是手动模式，则进入手动状态
            if (d.manual_mode && !S.manualMode) {
                S.manualMode = true;
                QH.toggleClass(QH.$('manualControlGroup'), 'control-group-disabled', false);
                QH.toggleClass(QH.$('autoThresholdArea'), 'control-group-disabled', false);
                QH.setText(QH.$('modeToggleBtn'), '切换至 全自动接管模式');
                QH.setStyle(QH.$('modeToggleBtn'), 'backgroundColor', '#3B6B4A');
            }
        }).catch(function () { /* 阈值接口不可用时沿用模板默认值 */ });
    }

    /** 保存模式（静默） */
    function saveMode() {
        return fetch('/api/thresh_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                humi_down: parseInt((QH.$('humiDownInput') || {}).value, 10) || 40,
                humi_up: parseInt((QH.$('humiUpInput') || {}).value, 10) || 80,
                waterlevel_down: parseInt((QH.$('waterlevelDownInput') || {}).value, 10) || 30,
                waterlevel_up: parseInt((QH.$('waterlevelUpInput') || {}).value, 10) || 150,
                manual_mode: S.manualMode ? 1 : 0
            })
        }).catch(function () { /* 静默失败，下次切换会重试 */ });
    }

    /** 手动 / 自动模式切换 */
    function toggleMode() {
        S.manualMode = !S.manualMode;
        var groupEl = QH.$('manualControlGroup');
        var threshEl = QH.$('autoThresholdArea');
        var btnEl = QH.$('modeToggleBtn');
        if (S.manualMode) {
            QH.toggleClass(groupEl, 'control-group-disabled', false);
            QH.toggleClass(threshEl, 'control-group-disabled', false);
            QH.setText(btnEl, '切换至 全自动接管模式');
            QH.setStyle(btnEl, 'backgroundColor', '#3B6B4A');
            root.addLog('系统已切换至【手动调控模式】', 'log-info');
        } else {
            QH.toggleClass(groupEl, 'control-group-disabled', true);
            QH.toggleClass(threshEl, 'control-group-disabled', true);
            QH.setText(btnEl, '切换至 手动接管模式');
            QH.setStyle(btnEl, 'backgroundColor', '#C8903F');
            root.addLog('系统已恢复【自动智能调控模式】', 'log-safe');
            // 重置自动状态去重标记，让自动逻辑按当前 RORI/水位把泵调到应有状态
            S.airPumpAutoState = '';
            S.pumpAutoState = '';
            root.updateRori();
        }
        saveMode();
    }

    /** 应用阈值参数（保存在后端，供自动调控逻辑使用） */
    function applyThresholds() {
        var humiUp = parseInt((QH.$('humiUpInput') || {}).value, 10) || 80;
        var humiDown = parseInt((QH.$('humiDownInput') || {}).value, 10) || 40;
        var wlUp = parseInt((QH.$('waterlevelUpInput') || {}).value, 10) || 150;
        var wlDown = parseInt((QH.$('waterlevelDownInput') || {}).value, 10) || 30;

        fetch('/api/thresh_settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                humi_down: humiDown, humi_up: humiUp,
                waterlevel_down: wlDown, waterlevel_up: wlUp,
                manual_mode: S.manualMode ? 1 : 0
            })
        }).then(function (r) { return r.json(); }).then(function () {
            root.addLog('[阈值保存] 湿度: ' + humiDown + '% ~ ' + humiUp + '% | 水位: ' + wlDown + 'mm ~ ' + wlUp + 'mm', 'log-info');
            alert('设定已保存！\n湿度阈值: ' + humiDown + '% ~ ' + humiUp + '%\n水位阈值: ' + wlDown + 'mm ~ ' + wlUp + 'mm');
            // 保存后按当前数据重新评估自动调控
            root.updateRori();
        }).catch(function () {
            alert('保存失败，请检查后端是否在线');
        });
    }

    root.QH_CONFIG = {
        onHumiditySlider: onHumiditySlider,
        onWaterLevelSlider: onWaterLevelSlider,
        dualRangeGeometry: dualRangeGeometry,
        updateDualRangeFill: updateDualRangeFill,
        loadConfig: loadConfig,
        saveConfig: saveConfig,
        changePassword: changePassword,
        loadThreshSettings: loadThreshSettings,
        saveMode: saveMode,
        toggleMode: toggleMode,
        applyThresholds: applyThresholds
    };

    // 模板内联 onclick 需要的全局
    root.onHumiditySlider = onHumiditySlider;
    root.onWaterLevelSlider = onWaterLevelSlider;
    // node 环境（无 window）下直接取用，便于 tests/js/config.test.mjs 单测纯函数
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = { dualRangeGeometry: dualRangeGeometry };
    }
    root.saveConfig = saveConfig;
    root.changePassword = changePassword;
    root.toggleMode = toggleMode;
    root.applyThresholds = applyThresholds;
})(typeof globalThis !== 'undefined' ? globalThis : this);
