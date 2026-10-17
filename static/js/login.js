/* ============================================================
 * login.js — 登录页：登录 / 注册 / 面板切换
 * 治理点：fetch 补 .catch（网络异常不再静默无反馈）；
 *         提交按钮点击后禁用，防重复提交。
 * ============================================================ */
(function () {
    'use strict';

    /** 按钮禁用/恢复（防重复提交） */
    function lockButton(id, locked, lockedText, normalText) {
        var btn = document.getElementById(id);
        if (!btn) return;
        btn.disabled = locked;
        btn.textContent = locked ? lockedText : normalText;
    }

    /** 切换登录 / 注册面板 */
    function switchPanel(panel) {
        var loginPanel = document.getElementById('loginPanel');
        var registerPanel = document.getElementById('registerPanel');
        if (!loginPanel || !registerPanel) return;
        if (panel === 'register') {
            loginPanel.style.display = 'none';
            registerPanel.style.display = 'block';
        } else {
            loginPanel.style.display = 'block';
            registerPanel.style.display = 'none';
        }
    }

    /** 登录：提交后禁用按钮，异常统一提示 */
    function handleLogin() {
        var userEl = document.getElementById('loginUsername');
        var passEl = document.getElementById('loginPassword');
        var username = userEl ? userEl.value.trim() : '';
        var password = passEl ? passEl.value : '';
        if (!username || !password) { alert('请输入用户名和密码'); return; }

        lockButton('loginBtn', true, '登录中...', '登 录');
        fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data && data.status === 'success') {
                window.location.href = '/';
                return;
            }
            alert((data && data.message) || '登录失败');
            lockButton('loginBtn', false, '登录中...', '登 录');
        }).catch(function () {
            alert('网络异常，请检查后端服务是否在线');
            lockButton('loginBtn', false, '登录中...', '登 录');
        });
    }

    /** 注册：校验 + .catch 兜底 + 防重复提交 */
    function handleRegister() {
        var userEl = document.getElementById('regUsername');
        var passEl = document.getElementById('regPassword');
        var cfmEl = document.getElementById('regConfirmPassword');
        var username = userEl ? userEl.value.trim() : '';
        var password = passEl ? passEl.value : '';
        var confirmPw = cfmEl ? cfmEl.value : '';
        if (!username || !password) { alert('请填写用户名和密码'); return; }
        if (password !== confirmPw) { alert('两次输入的密码不一致'); return; }

        lockButton('registerBtn', true, '注册中...', '注 册');
        fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password })
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (data && data.status === 'success') {
                alert('注册成功，请登录');
                switchPanel('login');
                var loginUser = document.getElementById('loginUsername');
                if (loginUser) loginUser.value = username;
                return;
            }
            alert((data && data.message) || '注册失败');
        }).catch(function () {
            alert('网络异常，请检查后端服务是否在线');
        }).then(function () {
            lockButton('registerBtn', false, '注册中...', '注 册');
        });
    }

    // 模板内联 onclick 需要
    window.handleLogin = handleLogin;
    window.handleRegister = handleRegister;
    window.switchPanel = switchPanel;
})();
