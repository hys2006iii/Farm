/**
 * diag.js — 设置页「测试连接」按钮。
 *
 * 四块外部接入（物联网 / 气象 / AI / 告警推送）填完参数后无法就地判断通不通，
 * 只能等设备没数据、预报为空、AI 不回话才发现填错。这里给每块一个按钮，
 * 调 `POST /api/diag/<target>` 真连一次，把结果就地显示在按钮右侧。
 *
 * 约定：
 * - 后端始终返回 200 + `{ok, message, detail}`，失败也走同一套渲染；
 * - 探测期间按钮禁用并显示「测试中…」，避免连点产生重复请求；
 * - 结果用 textContent 写入（不走 innerHTML），错误详情也不当 HTML 解析。
 */
(function (root) {
    'use strict';

    var QH = root.QH;

    /** 目标名 → [按钮 id, 结果 id]。新增目标时同步补这里与后端 diag.TARGETS。 */
    var TARGETS = {
        iot: ['diagIotBtn', 'diagIotResult'],
        weather: ['diagWeatherBtn', 'diagWeatherResult'],
        ai: ['diagAiBtn', 'diagAiResult'],
        webhook: ['diagWebhookBtn', 'diagWebhookResult']
    };

    /** 正在请求中的目标集合，用于挡住连点 */
    var busy = {};

    /** 把结果渲染到按钮右侧的小字上 */
    function render(ids, ok, message, detail) {
        var el = QH.$(ids[1]);
        if (!el) return;
        el.hidden = false;
        el.textContent = (ok ? '✓ ' : '✗ ') + message + (detail ? '（' + detail + '）' : '');
        el.classList.toggle('is-ok', !!ok);
        el.classList.toggle('is-bad', !ok);
    }

    /** 请求失败（网络层）时也要给出可读反馈，不能让按钮一直停在「测试中…」 */
    function renderNetworkError(ids, err) {
        render(ids, false, '请求失败', err && err.message ? err.message : '未知错误');
    }

    /**
     * 执行一次连通性测试。
     * @param {string} target iot / weather / ai / webhook
     */
    function run(target) {
        var ids = TARGETS[target];
        if (!ids) return;
        if (busy[target]) return;
        var btn = QH.$(ids[0]);
        var label = btn ? btn.textContent : '';
        busy[target] = true;
        if (btn) {
            btn.disabled = true;
            btn.textContent = '测试中…';
        }
        var done = function () {
            busy[target] = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = label;
            }
        };
        // 先保存再测试：用户常常刚改完参数就点测试，不先落库会拿旧配置去连，
        // 测出来的结果和他刚填的内容对不上。
        var save = (target === 'iot' && typeof root.saveConfig === 'function')
            ? Promise.resolve(root.saveConfig(true)) : Promise.resolve();
        save.then(function () {
            return fetch('/api/diag/' + target, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        }).then(function (resp) {
            return resp.json().catch(function () { return null; }).then(function (data) {
                done();
                if (!data) {
                    render(ids, false, '服务返回了无法解析的内容（HTTP ' + resp.status + '）', '');
                    return;
                }
                if (data.error) {
                    render(ids, false, data.error, '');
                    return;
                }
                render(ids, data.ok, data.message || '', data.detail || '');
            });
        }).catch(function (err) {
            done();
            renderNetworkError(ids, err);
        });
    }

    root.QH_DIAG = { run: run, TARGETS: TARGETS };
})(typeof globalThis !== 'undefined' ? globalThis : this);
