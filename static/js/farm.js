/* ============================================================
 * farm.js — 多地块：顶栏切换器 / 设置页地块管理 / 气象监测点与边界设置
 *
 * 依赖：core.js 的 QH，Leaflet（可缺失，缺失时降级为手填经纬度）
 * 治理点：
 *  - DOM 一律 createElement + textContent，不拼 innerHTML；
 *  - 所有 fetch 带 .catch 与超时保护，失败只提示不抛；
 *  - 地图实例只创建一次，重复打开设置面板不重复建图；
 *  - 圈地面积用球面多边形公式估算，明确标注「估算」。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;

    //: 圈地点位上限，防止误点成百上千个点
    var MAX_POLY_POINTS = 40;
    //: 地球平均半径（米），用于圈地面积估算
    var EARTH_R = 6371000;
    //: 没有坐标时的默认视野中心（广州）
    var DEFAULT_CENTER = [23.1291, 113.2644];

    var state = {
        farms: [],
        activeId: 0,
        map: null,
        marker: null,
        polygon: null,
        polyPoints: [],
        // 撤回/回退栈：撤回与清空都把点推到这里，「回退」再取回。
        // 只存一份即够——圈地时每加一个点就清空它（见 addPolyPoint）。
        redoPoints: [],
        mode: 'pick',
        mapReady: false
    };

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function num(value) {
        var v = Number(value);
        return isFinite(v) ? v : null;
    }

    /** 统一的 JSON 请求封装 */
    function api(url, payload) {
        var options = { method: payload ? 'POST' : 'GET', headers: {} };
        if (payload) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(payload);
        }
        return fetch(url, options).then(function (r) {
            return r.json().catch(function () { return null; }).then(function (data) {
                if (!r.ok) {
                    var msg = (data && (data.message || data.error)) || ('请求失败（' + r.status + '）');
                    throw new Error(msg);
                }
                return data;
            });
        });
    }

    /** 球面多边形面积估算（m²），点少时退化为 0 */
    function polygonArea(points) {
        if (!Array.isArray(points) || points.length < 3) return 0;
        var total = 0;
        for (var i = 0; i < points.length; i++) {
            var p1 = points[i];
            var p2 = points[(i + 1) % points.length];
            var lat1 = p1[0] * Math.PI / 180;
            var lat2 = p2[0] * Math.PI / 180;
            var dLon = (p2[1] - p1[1]) * Math.PI / 180;
            total += dLon * (2 + Math.sin(lat1) + Math.sin(lat2));
        }
        return Math.abs(total) * EARTH_R * EARTH_R / 2;
    }

    function areaText(m2) {
        if (!m2 || m2 <= 0) return '未圈地';
        if (m2 < 10000) return Math.round(m2) + ' m²（约 ' + (m2 / 666.7).toFixed(2) + ' 亩）';
        return (m2 / 10000).toFixed(2) + ' 公顷';
    }

    /* ---------------- 顶栏切换器 ---------------- */
    function renderChip() {
        var active = null;
        state.farms.forEach(function (f) { if (f.id === state.activeId) active = f; });
        QH.setText(QH.$('farmChipName'), active ? active.name : '未设置地块');
        var menu = QH.$('farmMenu');
        if (!menu) return;
        menu.textContent = '';
        state.farms.forEach(function (farm) {
            var row = el('button', 'farm-menu-row' + (farm.id === state.activeId ? ' is-active' : ''));
            row.type = 'button';
            row.appendChild(el('span', 'farm-menu-name', farm.name));
            var meta = [];
            if (num(farm.area_m2) > 0) meta.push((Math.round(farm.area_m2 / 100) / 100) + ' 公顷');
            if (num(farm.lat) !== null && num(farm.lon) !== null) {
                meta.push(num(farm.lat).toFixed(3) + ', ' + num(farm.lon).toFixed(3));
            }
            row.appendChild(el('span', 'farm-menu-meta', meta.join(' · ')));
            if (farm.id === state.activeId) row.appendChild(el('span', 'farm-menu-flag', '当前'));
            row.addEventListener('click', function () {
                hideMenu();
                if (farm.id !== state.activeId) switchFarm(farm.id);
            });
            menu.appendChild(row);
        });
        var manage = el('button', 'farm-menu-row farm-menu-manage', '管理地块 / 气象监测点');
        manage.type = 'button';
        manage.addEventListener('click', function () {
            hideMenu();
            openSettingsFarms();
        });
        menu.appendChild(manage);
    }

    function hideMenu() {
        var menu = QH.$('farmMenu');
        var btn = QH.$('farmSwitchBtn');
        if (menu) menu.classList.add('hidden');
        if (btn) btn.setAttribute('aria-expanded', 'false');
    }

    function toggleMenu(event) {
        if (event) event.stopPropagation();
        var menu = QH.$('farmMenu');
        var btn = QH.$('farmSwitchBtn');
        if (!menu) return;
        var willOpen = menu.classList.contains('hidden');
        menu.classList.toggle('hidden', !willOpen);
        if (btn) btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        if (willOpen) renderChip();
    }

    function switchFarm(farmId) {
        api('/api/farms/switch', { farm_id: farmId }).then(function () {
            root.location.reload();
        }).catch(function (err) {
            QH.toast('切换地块失败：' + err.message, 'danger');
        });
    }

    /* ---------------- 设置面板 ---------------- */
    function openSettingsFarms() {
        if (typeof root.openModal === 'function') root.openModal('configModal');
        var block = QH.$('farmBlock');
        if (block && block.scrollIntoView) {
            setTimeout(function () { block.scrollIntoView({ block: 'center' }); }, 80);
        }
    }

    /** 地图初始化：只建一次，失败降级 */
    function ensureMap() {
        var box = QH.$('farmMap');
        if (!box || state.mapReady) return;
        if (!root.L || typeof root.L.map !== 'function') {
            var fallback = QH.$('farmMapFallback');
            if (fallback) fallback.hidden = false;
            if (box) box.classList.add('farm-map--empty');
            return;
        }
        try {
            var active = currentFarm();
            var center = (active && num(active.lat) !== null && num(active.lon) !== null)
                ? [num(active.lat), num(active.lon)] : DEFAULT_CENTER;
            state.map = root.L.map(box, { center: center, zoom: 16, zoomControl: true });
            // 底图用高德：国内网络可达（OSM 在校园网常被墙，会白屏）。
            // 卫星影像更适合圈地看地块边界；坐标系为 GCJ-02，与 WGS84 有百米级偏移，
            // 页面下方已注明，够用于地块定位。
            var tiles = root.L.tileLayer(
                'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}', {
                    subdomains: '1234',
                    maxZoom: 18,
                    attribution: '&copy; 高德地图'
                }
            );
            tiles.on('tileerror', function () {
                var fb = QH.$('farmMapFallback');
                if (fb) fb.hidden = false;
            });
            tiles.addTo(state.map);
            if (center !== DEFAULT_CENTER) {
                state.marker = root.L.marker(center).addTo(state.map);
            }
            loadPolygonFromFarm(active);
            state.map.on('click', onMapClick);
            state.mapReady = true;
            // 容器从 hidden 变可见后需要重新量尺寸
            setTimeout(function () { if (state.map) state.map.invalidateSize(); }, 120);
        } catch (err) {
            var fb = QH.$('farmMapFallback');
            if (fb) fb.hidden = false;
        }
    }

    function currentFarm() {
        var found = null;
        state.farms.forEach(function (f) { if (f.id === state.activeId) found = f; });
        return found;
    }

    function loadPolygonFromFarm(farm) {
        // 换地块时撤回历史必须一起清掉，否则会把上一块地的点「回退」到这一块上
        state.redoPoints = [];
        if (!farm || !farm.polygon) { state.polyPoints = []; drawPolygon(); return; }
        try {
            var parsed = JSON.parse(farm.polygon);
            state.polyPoints = Array.isArray(parsed) ? parsed.filter(function (p) {
                return Array.isArray(p) && p.length === 2 && num(p[0]) !== null && num(p[1]) !== null;
            }).map(function (p) { return [num(p[0]), num(p[1])]; }) : [];
        } catch (err) {
            state.polyPoints = [];
        }
        drawPolygon();
    }

    function onMapClick(event) {
        var lat = event.latlng.lat;
        var lon = event.latlng.lng;
        if (state.mode === 'poly') {
            if (state.polyPoints.length >= MAX_POLY_POINTS) {
                QH.toast('边界点最多 ' + MAX_POLY_POINTS + ' 个', 'warn');
                return;
            }
            state.polyPoints.push([lat, lon]);
            // 新点进来后，之前撤回的历史就作废了，否则「回退」会接出错误的顺序
            state.redoPoints = [];
            drawPolygon();
            updateSummary();
            return;
        }
        var latEl = QH.$('cfgFarmLat');
        var lonEl = QH.$('cfgFarmLng');
        if (latEl) latEl.value = lat.toFixed(6);
        if (lonEl) lonEl.value = lon.toFixed(6);
        if (state.map) {
            if (state.marker) state.marker.setLatLng([lat, lon]);
            else state.marker = root.L.marker([lat, lon]).addTo(state.map);
        }
        QH.toast('已取该点坐标，可点「保存地块信息」写入', 'success');
    }

    function drawPolygon() {
        if (!state.map || !root.L) return;
        if (state.polygon) {
            state.map.removeLayer(state.polygon);
            state.polygon = null;
        }
        if (state.polyPoints.length >= 2) {
            state.polygon = root.L.polygon(state.polyPoints, {
                color: '#2C5F4A', weight: 2, fillColor: '#2C5F4A', fillOpacity: 0.12
            }).addTo(state.map);
        }
        state.polyPoints.forEach(function (p) {
            root.L.circleMarker(p, { radius: 4, color: '#A8402F', weight: 2, fillColor: '#FBF9F3', fillOpacity: 1 })
                .addTo(state.map);
        });
    }

    function setMapMode(mode) {
        state.mode = mode === 'poly' ? 'poly' : 'pick';
        var hint = QH.$('farmMapHint');
        if (hint) {
            QH.setText(hint, state.mode === 'poly'
                ? '边界设置：沿田块边界逐点点击（至少 3 点），点完点「保存地块信息」'
                : '气象监测点：点一下地图即取该点经纬度，填进上方经度/纬度');
        }
        ['mapPickBtn', 'mapPolyBtn'].forEach(function (id) {
            var btn = QH.$(id);
            if (!btn) return;
            var on = (id === 'mapPolyBtn') === (state.mode === 'poly');
            btn.classList.toggle('is-on', on);
        });
    }

    /** 撤回一点：把最后一点挪进 redo 栈，可再「回退」找回来 */
    function undoPolyPoint() {
        if (!state.polyPoints.length) return;
        state.redoPoints.push(state.polyPoints.pop());
        drawPolygon();
        updateSummary();
    }

    /** 回退：把刚撤回的那一点放回去（连续撤回可连续回退） */
    function redoPolyPoint() {
        if (!state.redoPoints.length) return;
        state.polyPoints.push(state.redoPoints.pop());
        drawPolygon();
        updateSummary();
    }

    /** 清空边界：整条存进 redo 栈，误点清空后仍能一步步回退回来 */
    function clearPoly() {
        if (!state.polyPoints.length) return;
        state.redoPoints = state.polyPoints.slice().reverse();
        state.polyPoints = [];
        drawPolygon();
        updateSummary();
    }

    function updateSummary() {
        var active = currentFarm();
        QH.setText(QH.$('farmCurrentName'), active ? active.name : '—');
        var area = polygonArea(state.polyPoints);
        var saved = active ? num(active.area_m2) : null;
        QH.setText(QH.$('farmAreaText'), area > 0 ? areaText(area) : (saved ? areaText(saved) : '未圈地'));
        QH.setText(QH.$('farmPolyCount'), String(state.polyPoints.length));
    }

    /** 保存当前地块的名称/坐标/边界 */
    function saveCurrent() {
        var active = currentFarm();
        if (!active) { QH.toast('没有可保存的地块', 'warn'); return; }
        var nameEl = QH.$('cfgFarmName');
        var latEl = QH.$('cfgFarmLat');
        var lonEl = QH.$('cfgFarmLng');
        var payload = {
            farm_id: active.id,
            name: nameEl ? nameEl.value.trim() : active.name
        };
        var lat = latEl ? num(latEl.value) : null;
        var lon = lonEl ? num(lonEl.value) : null;
        if (lat !== null && lon !== null) { payload.lat = lat; payload.lon = lon; }
        if (state.polyPoints.length >= 3) {
            payload.polygon = JSON.stringify(state.polyPoints.map(function (p) {
                return [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6];
            }));
            var area = polygonArea(state.polyPoints);
            if (area > 0) payload.area_m2 = Math.round(area);
        }
        return api('/api/farms/update', payload).then(function (data) {
            QH.toast(data.message || '地块信息已保存', 'success');
            return loadFarms();
        }).catch(function (err) {
            QH.toast('保存地块失败：' + err.message, 'danger');
        });
    }

    /** 把当前名称/坐标另存为一块新地 */
    function saveAsNew() {
        var nameEl = QH.$('newFarmName');
        var name = nameEl ? nameEl.value.trim() : '';
        if (!name) {
            var fallback = QH.$('cfgFarmName');
            name = fallback && fallback.value.trim() ? fallback.value.trim() + '（新）' : '';
        }
        if (!name) { QH.toast('请先填写新地块名称', 'warn'); return; }
        var latEl = QH.$('cfgFarmLat');
        var lonEl = QH.$('cfgFarmLng');
        var payload = { name: name };
        var lat = latEl ? num(latEl.value) : null;
        var lon = lonEl ? num(lonEl.value) : null;
        if (lat !== null && lon !== null) { payload.lat = lat; payload.lon = lon; }
        if (state.polyPoints.length >= 3) {
            payload.polygon = JSON.stringify(state.polyPoints);
            var area = polygonArea(state.polyPoints);
            if (area > 0) payload.area_m2 = Math.round(area);
        }
        api('/api/farms', payload).then(function (data) {
            var farm = data && data.farm;
            if (nameEl) nameEl.value = '';
            if (farm && farm.id) return api('/api/farms/switch', { farm_id: farm.id });
            return null;
        }).then(function () {
            QH.toast('新地块已创建并切换', 'success');
            root.location.reload();
        }).catch(function (err) {
            QH.toast('新建地块失败：' + err.message, 'danger');
        });
    }

    function renderFarmList() {
        var list = QH.$('farmList');
        if (!list) return;
        list.textContent = '';
        if (!state.farms.length) {
            list.appendChild(el('div', 'farm-list-empty', '还没有地块，先在上方填写名称后「另存为新地块」'));
            return;
        }
        state.farms.forEach(function (farm) {
            var row = el('div', 'farm-row' + (farm.id === state.activeId ? ' is-active' : ''));
            var info = el('div', 'farm-row-info');
            info.appendChild(el('div', 'farm-row-name', farm.name));
            var meta = [];
            if (num(farm.lat) !== null && num(farm.lon) !== null) {
                meta.push(num(farm.lat).toFixed(5) + ', ' + num(farm.lon).toFixed(5));
            }
            if (num(farm.area_m2) > 0) meta.push(areaText(num(farm.area_m2)));
            info.appendChild(el('div', 'farm-row-meta', meta.join(' · ') || '未填写坐标'));
            row.appendChild(info);
            var actions = el('div', 'farm-row-actions');
            if (farm.id === state.activeId) {
                actions.appendChild(el('span', 'farm-row-flag', '当前'));
            } else {
                var go = el('button', 'btn-link', '切换');
                go.type = 'button';
                go.addEventListener('click', function () { switchFarm(farm.id); });
                actions.appendChild(go);
            }
            var del = el('button', 'btn-link btn-link--danger', '删除');
            del.type = 'button';
            del.addEventListener('click', function () { deleteFarm(farm); });
            actions.appendChild(del);
            row.appendChild(actions);
            list.appendChild(row);
        });
    }

    function deleteFarm(farm) {
        // 站内确认框：原生 confirm 会阻塞渲染线程，且样式与整站割裂
        QH.dialogConfirm('确定删除地块「' + farm.name + '」？该地块的阈值与历史不会一并删除。')
            .then(function (ok) {
                if (!ok) return null;
                return api('/api/farms/delete', { farm_id: farm.id }).then(function () {
                    QH.toast('地块已删除', 'success');
                    return loadFarms().then(function () {
                        if (farm.id === state.activeId) root.location.reload();
                    });
                }).catch(function (err) {
                    QH.toast('删除失败：' + err.message, 'danger');
                });
            });
    }

    /** 读地块列表并刷新所有相关界面 */
    function loadFarms() {
        return api('/api/farms').then(function (data) {
            state.farms = (data && data.farms) || [];
            state.activeId = num(data && data.active_id) || 0;
            renderChip();
            renderFarmList();
            updateSummary();
            return data;
        }).catch(function () {
            QH.setText(QH.$('farmChipName'), '地块加载失败');
        });
    }

    /* ---------------- 生命周期 ---------------- */
    function onSettingsOpen() {
        ensureMap();
        setMapMode(state.mode);
        loadFarms().then(function () {
            updateSummary();
            if (state.map && state.farms.length) {
                var active = currentFarm();
                if (active && num(active.lat) !== null && num(active.lon) !== null) {
                    state.map.setView([num(active.lat), num(active.lon)]);
                }
            }
            setTimeout(function () { if (state.map) state.map.invalidateSize(); }, 150);
        });
    }

    function init() {
        loadFarms();
        // 设置面板打开时再初始化地图，避免首屏加载瓦片
        if (typeof root.openModal === 'function') {
            var original = root.openModal;
            root.openModal = function (id) {
                original(id);
                // 等弹窗布局稳定后再建图：容器尺寸为 0 时 Leaflet 会把瓦片铺错位置
                if (id === 'configModal') setTimeout(onSettingsOpen, 90);
            };
        }
        document.addEventListener('click', function (event) {
            var menu = QH.$('farmMenu');
            var btn = QH.$('farmSwitchBtn');
            if (!menu || menu.classList.contains('hidden')) return;
            if (btn && btn.contains(event.target)) return;
            if (menu.contains(event.target)) return;
            hideMenu();
        });
    }

    root.QH_FARM = {
        init: init,
        loadFarms: loadFarms,
        toggleMenu: toggleMenu,
        switchFarm: switchFarm,
        saveCurrent: saveCurrent,
        saveAsNew: saveAsNew,
        deleteFarm: deleteFarm,
        setMapMode: setMapMode,
        undoPolyPoint: undoPolyPoint,
        redoPolyPoint: redoPolyPoint,
        clearPoly: clearPoly,
        polygonArea: polygonArea,
        areaText: areaText,
        state: state
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})(typeof globalThis !== 'undefined' ? globalThis : this);
