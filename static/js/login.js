/* ============================================================
 * login.js — 登录页：登录 / 注册 / 面板切换 / 登录后地块选择
 * 治理点：fetch 补 .catch（网络异常不再静默无反馈）；
 *         提交按钮点击后禁用，防重复提交；
 *         地块列表一律 createElement + textContent，不用 innerHTML。
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

    /**
     * 站内提示条：替代浏览器原生 alert。
     *
     * 登录页不加载 core.js（那边是看板的 15KB 依赖），所以这里自带一个最小实现。
     * 原生 alert 有三个问题：样式与纸质配色割裂、阻塞渲染线程、标题栏写着
     * 「127.0.0.1:5000 显示」这种和业务无关的地址。
     *
     * @param {string} message 提示正文
     * @param {string} [kind] 'warn' 用朱红强调，其余走墨绿
     */
    function notice(message, kind) {
        var box = document.getElementById('loginNotice');
        if (!box) {
            // 兜底：模板里没有提示条时退化成原生弹窗，总比静默无反馈好
            window.alert(message);
            return;
        }
        box.textContent = String(message);
        box.className = 'login-notice' + (kind === 'warn' ? ' login-notice--warn' : '');
        box.hidden = false;
        // 自动收起，避免上一条提示一直挂在表单上方
        if (noticeTimer) clearTimeout(noticeTimer);
        noticeTimer = setTimeout(function () { box.hidden = true; }, 6000);
    }

    var noticeTimer = null;

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

    /* ------------------------------------------------------------
     * 地块选择（多地块账号登录后先选田块）
     * ---------------------------------------------------------- */

    /** 当前选中地块 id（null = 尚未确定） */
    var selectedFarmId = null;
    /** 登录响应里的生效地块 id，用于判断是否需要调切换接口 */
    var activeFarmId = null;

    /**
     * 归一化地块列表：只保留 id 为正整数的项。
     *
     * 后端 `_farm_dict` 返回的 id 是 int，但这里仍做一次防御性转换，
     * 避免脏数据导致列表渲染出无法切换的行。
     */
    function normalizeFarms(raw) {
        if (!Array.isArray(raw)) return [];
        var out = [];
        for (var i = 0; i < raw.length; i++) {
            var f = raw[i];
            if (!f || typeof f !== 'object') continue;
            var id = Number(f.id);
            if (!Number.isFinite(id) || id <= 0) continue;
            out.push({ id: id, name: f.name, lat: f.lat, lon: f.lon, area_m2: f.area_m2 });
        }
        return out;
    }

    /**
     * 地块摘要文案：优先「面积 · 坐标」，两者都缺时退回「面积与坐标待标定」。
     *
     * 坐标用 `!= null` 判空而非 `Number(...)`：`Number(null) === 0`、
     * `Number(undefined) === NaN` 都是真值陷阱，直接用 Number 会把
     * 「坐标未标定」渲染成 `0.0000, 0.0000`（几内亚湾），是明确的错数据。
     * 注意 0 是合法经纬度（赤道/本初子午线），所以只判 null/undefined，
     * 不能用 `!lat` 这种假值判断。
     */
    function farmMetaText(farm) {
        var parts = [];
        var area = Number(farm && farm.area_m2);
        if (Number.isFinite(area) && area > 0) {
            parts.push(area >= 10000
                ? (area / 10000).toFixed(2) + ' 公顷'
                : Math.round(area) + ' m²');
        }
        var latRaw = farm ? farm.lat : null;
        var lonRaw = farm ? farm.lon : null;
        if (latRaw != null && lonRaw != null && latRaw !== ''
            && lonRaw !== '' && Number.isFinite(Number(latRaw)) && Number.isFinite(Number(lonRaw))) {
            parts.push(Number(latRaw).toFixed(4) + ', ' + Number(lonRaw).toFixed(4));
        }
        if (!parts.length) return '面积与坐标待标定';
        return parts.join(' · ');
    }

    /**
     * 决定登录后的去向。
     *
     * 抽成纯函数是为了让三条分支可被单独核对：
     *   - 地块数 ≤ 1 或数据缺失 → 直接进监控台（保持旧行为）
     *   - 地块数 > 1            → 弹地块选择层
     */
    function decideAfterLogin(data) {
        var farms = normalizeFarms(data && data.farms);
        if (farms.length <= 1) return { action: 'enter', farms: farms };
        return { action: 'choose', farms: farms };
    }

    /** 兼容 active_farm_id（登录响应）与 active_id（/api/farms）两种字段名 */
    function pickActiveFarmId(data) {
        if (!data) return null;
        var raw = data.active_farm_id !== undefined ? data.active_farm_id : data.active_id;
        var id = Number(raw);
        return Number.isFinite(id) && id > 0 ? id : null;
    }

    /** 高亮选中的地块行 */
    function markSelected(farmId) {
        selectedFarmId = farmId;
        var list = document.getElementById('farmChooserList');
        if (!list) return;
        var rows = list.children;
        for (var i = 0; i < rows.length; i++) {
            var rowId = Number(rows[i].getAttribute('data-farm-id'));
            if (rowId === farmId) {
                rows[i].classList.add('is-selected');
                rows[i].setAttribute('aria-selected', 'true');
            } else {
                rows[i].classList.remove('is-selected');
                rows[i].setAttribute('aria-selected', 'false');
            }
        }
    }

    /**
     * 渲染地块列表（createElement + textContent，杜绝 innerHTML 注入）。
     * 每行：序号 + 地块名 + 面积/坐标摘要，默认选中生效地块。
     */
    function renderFarmList(farms, activeId) {
        var list = document.getElementById('farmChooserList');
        if (!list) return;
        while (list.firstChild) list.removeChild(list.firstChild);

        farms.forEach(function (farm, idx) {
            var row = document.createElement('div');
            row.className = 'chooser-row';
            row.setAttribute('data-farm-id', String(farm.id));
            row.setAttribute('role', 'option');
            row.setAttribute('aria-selected', 'false');
            row.tabIndex = 0;

            var no = document.createElement('span');
            no.className = 'chooser-no';
            no.textContent = String(idx + 1).padStart(2, '0');

            var body = document.createElement('div');
            body.className = 'chooser-body';

            var name = document.createElement('div');
            name.className = 'chooser-name';
            name.textContent = farm.name || ('地块 ' + farm.id);

            var meta = document.createElement('div');
            meta.className = 'chooser-meta';
            meta.textContent = farmMetaText(farm);

            body.appendChild(name);
            body.appendChild(meta);
            row.appendChild(no);
            row.appendChild(body);

            row.addEventListener('click', function () { markSelected(farm.id); });
            row.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    markSelected(farm.id);
                }
            });

            list.appendChild(row);
        });

        // 生效地块不在列表里（异常数据）时回落到第一块
        var initial = activeId;
        var found = farms.some(function (f) { return f.id === initial; });
        if (!found) initial = farms.length ? farms[0].id : null;
        markSelected(initial);
    }

    /** 展示地块选择层，隐藏登录/注册卡片 */
    function showFarmChooser(farms, activeId) {
        var chooser = document.getElementById('farmChooser');
        if (!chooser) { window.location.href = '/'; return; }
        activeFarmId = activeId;
        renderFarmList(farms, activeId);
        var loginPanel = document.getElementById('loginPanel');
        var registerPanel = document.getElementById('registerPanel');
        if (loginPanel) loginPanel.style.display = 'none';
        if (registerPanel) registerPanel.style.display = 'none';
        chooser.classList.remove('hidden');
        chooser.setAttribute('aria-hidden', 'false');
        lockButton('loginBtn', false, '登录中...', '登 录');
    }

    /**
     * 「进入监控台」：选中的地块与生效地块不同则先切换，再跳转。
     * 切换失败给出提示但仍继续进入（看板会展示原生效地块，不至于卡死）。
     */
    function enterFarm() {
        if (selectedFarmId === null) { notice('请先选择一块地', 'warn'); return; }
        if (selectedFarmId === activeFarmId) { window.location.href = '/'; return; }

        lockButton('farmEnterBtn', true, '切换中...', '进入监控台');
        fetch('/api/farms/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ farm_id: selectedFarmId })
        }).then(function (r) {
            return r.json().catch(function () { return {}; });
        }).then(function (data) {
            if (!data || data.status !== 'success') {
                notice((data && (data.message || data.error)) || '地块切换失败，仍将进入监控台', 'warn');
            }
            // 切换失败时 activeFarmId 仍是旧值，把选择同步回去，
            // 避免用户点了「返回」后再进来看到高亮与实际生效地块不一致。
            activeFarmId = (data && data.status === 'success') ? selectedFarmId : activeFarmId;
            window.location.href = '/';
        }).catch(function () {
            notice('地块切换请求异常，仍将进入监控台', 'warn');
            window.location.href = '/';
        });
    }

    /** 登录：提交后禁用按钮，异常统一提示 */
    function handleLogin() {
        var userEl = document.getElementById('loginUsername');
        var passEl = document.getElementById('loginPassword');
        var username = userEl ? userEl.value.trim() : '';
        var password = passEl ? passEl.value : '';
        if (!username || !password) { notice('请输入用户名和密码', 'warn'); return; }

        lockButton('loginBtn', true, '登录中...', '登 录');
        fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password })
        }).then(function (r) {
            // 非 JSON 响应（如网关 502 的 HTML 页）不应被当成「网络异常」误导用户
            return r.json().catch(function () { return {}; });
        }).then(function (data) {
            if (data && data.status === 'success') {
                var decision = decideAfterLogin(data);
                console.log('[login] 登录成功，分支=' + decision.action
                    + '，地块数=' + decision.farms.length
                    + '，生效地块=' + pickActiveFarmId(data));
                if (decision.action === 'choose') {
                    showFarmChooser(decision.farms, pickActiveFarmId(data));
                    return;
                }
                window.location.href = '/';
                return;
            }
            notice((data && data.message) || '登录失败', 'warn');
            lockButton('loginBtn', false, '登录中...', '登 录');
        }).catch(function () {
            notice('网络异常，请检查后端服务是否在线', 'warn');
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
        if (!username || !password) { notice('请填写用户名和密码', 'warn'); return; }
        if (password !== confirmPw) { notice('两次输入的密码不一致', 'warn'); return; }

        lockButton('registerBtn', true, '注册中...', '注 册');
        fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password })
        }).then(function (r) {
            // 同上：注册接口异常时也要给出可读提示而不是「网络异常」
            return r.json().catch(function () { return {}; });
        }).then(function (data) {
            if (data && data.status === 'success') {
                notice('注册成功，请登录');
                switchPanel('login');
                var loginUser = document.getElementById('loginUsername');
                if (loginUser) loginUser.value = username;
                return;
            }
            notice((data && data.message) || '注册失败', 'warn');
        }).catch(function () {
            notice('网络异常，请检查后端服务是否在线', 'warn');
        }).then(function () {
            lockButton('registerBtn', false, '注册中...', '注 册');
        });
    }

    // 纯函数导出：供 node --test 直接核对分支判定，浏览器侧不依赖
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = {
            normalizeFarms: normalizeFarms,
            farmMetaText: farmMetaText,
            decideAfterLogin: decideAfterLogin,
            pickActiveFarmId: pickActiveFarmId
        };
    }

    // 无 DOM 环境（node 单测）到此为止，不再挂 window
    if (typeof document === 'undefined') return;

    // 模板内联 onclick 需要
    window.handleLogin = handleLogin;
    window.handleRegister = handleRegister;
    window.switchPanel = switchPanel;
    window.enterFarm = enterFarm;
    window.showManageHint = function () {
        notice('进入监控台后，可在「地块管理」中新增、编辑或删除地块');
    };
})();
