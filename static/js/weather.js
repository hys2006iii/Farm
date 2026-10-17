/* ============================================================
 * weather.js — 天气 / 6 日降雨预报 / 逆地理 / 降雨前馈动态阈值提示
 * 治理点：所有插入 DOM 的外部数据（预报日期、接口错误、逆地理名称）
 *         一律走 textContent 或 esc()，不再裸拼 innerHTML。
 * ============================================================ */
(function (root) {
    'use strict';

    var QH = root.QH;
    var S = root.S;
    var IRR = root.QH_IRRIGATION;

    /** 当前气象（Open-Meteo，免 Key、跨域友好） */
    function fetchWeatherData(latNum, lonNum) {
        fetch('https://api.open-meteo.com/v1/forecast?latitude=' + latNum + '&longitude=' + lonNum
            + '&current=temperature_2m,relative_humidity_2m&timezone=Asia%2FShanghai')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.current) {
                    QH.setText(QH.$('tempDisplay'), d.current.temperature_2m + '°C');
                    QH.setText(QH.$('humidityDisplay'), d.current.relative_humidity_2m);
                }
            })
            .catch(function () { /* 第三方气象不可用时保留占位符 */ });
    }

    /** 顶栏位置显示：农场名 / 反查地名 / 坐标 */
    function fetchWeather() {
        var cfg = S.config || {};
        var lng = cfg.farm_lng;
        var lat = cfg.farm_lat;
        var locDisplay = QH.$('locDisplay');
        var locSubDisplay = QH.$('locSubDisplay');
        var farmName = cfg.farm_name ? String(cfg.farm_name).trim() : '';

        // 未配置经纬度：直接显示农场名称（来自设置），不显示坐标
        if (!lng || !lat) {
            QH.setText(locDisplay, farmName || '未命名农场');
            QH.setText(locSubDisplay, '');
            return;
        }
        var lonNum = parseFloat(lng);
        var latNum = parseFloat(lat);
        var coordText = 'E: ' + lonNum.toFixed(2) + '°, N: ' + latNum.toFixed(2) + '°';

        // 已设置农场名称：主显示农场名，副显示经纬度
        if (farmName) {
            QH.setText(locDisplay, farmName);
            QH.setText(locSubDisplay, coordText);
            fetchWeatherData(latNum, lonNum);
            return;
        }

        // 未设置农场名称：主显示反查地名，副显示经纬度；反查失败时主行保持“位置解析中…”
        QH.setText(locSubDisplay, coordText);
        QH.setText(locDisplay, '位置解析中…');
        fetchWeatherData(latNum, lonNum);
        var cacheKey = 'loc_' + latNum.toFixed(4) + '_' + lonNum.toFixed(4);
        var cachedName = '';
        try { cachedName = localStorage.getItem(cacheKey) || ''; } catch (e) { /* 隐私模式忽略 */ }
        if (cachedName) QH.setText(locDisplay, cachedName);
        fetch('/api/reverse_geocode?lat=' + latNum + '&lng=' + lonNum)
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var name = (d && d.name) ? String(d.name) : '';
                if (name && name !== coordText) {
                    QH.setText(locDisplay, name);
                    try { localStorage.setItem(cacheKey, name); } catch (e) { /* 配额忽略 */ }
                }
            })
            .catch(function () {
                if (!cachedName) QH.setText(locDisplay, '具体位置暂不可用');
            });
    }

    /** 降雨前馈动态阈值（说明书 3.3）：委托纯函数，读取当前滑块基础阈值 */
    function computeDynamicThreshold() {
        var lo = parseInt((QH.$('humiDownInput') || {}).value, 10) || 40;
        var hi = parseInt((QH.$('humiUpInput') || {}).value, 10) || 80;
        return IRR.computeDynamicThreshold(S.forecastData, lo, hi);
    }

    /** 阈值融合提示条（使用 DOM 节点构建，不拼 HTML 字符串） */
    function updateThresholdFusionHint() {
        var hint = QH.$('thresholdFusionHint');
        if (!hint) return;
        var dt = computeDynamicThreshold();
        if (!dt.hasForecast) { hint.style.display = 'none'; return; }
        hint.style.display = 'block';
        hint.textContent = '';
        var parts;
        if (dt.rainComing) {
            parts = [
                ['降雨前馈：6日降雨 ', 0], ['P6d=' + dt.P6d.toFixed(1) + 'mm', 1],
                ['，α=', 0], [String(dt.alpha), 1],
                ['；动态土壤湿度阈值 下限 ', 0], [dt.effLower.toFixed(1) + '%', 1],
                [' / 上限 ', 0], [dt.effUpper.toFixed(1) + '%', 1],
                ['，已与 RORI 风险联动。', 0]
            ];
        } else {
            parts = [
                ['无降雨前馈：阈值维持 下限 ', 0], [dt.baseLower + '%', 0],
                [' / 上限 ', 0], [dt.baseUpper + '%', 0], ['。', 0]
            ];
        }
        parts.forEach(function (p) {
            if (p[1]) {
                var b = document.createElement('b');
                b.textContent = p[0];
                hint.appendChild(b);
            } else {
                hint.appendChild(document.createTextNode(p[0]));
            }
        });
    }

    /** 6 日降雨预报（经后端代理，避免跨域/CSP） */
    function fetchForecast() {
        var gridEl = QH.$('forecastGrid');
        if (!gridEl) return;
        var cfg = S.config || {};
        if (!cfg.weather_key) {
            renderForecastMessage('未配置天气 API Key，请在设置中填写', true);
            return;
        }
        var lng = cfg.farm_lng || '118.78';
        var lat = cfg.farm_lat || '31.90';
        renderForecastMessage('模型加载中...', false);

        fetch('/api/forecast?lng=' + encodeURIComponent(lng) + '&lat=' + encodeURIComponent(lat))
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || d.code !== '200' || !d.daily) {
                    renderForecastMessage((d && d.error) ? String(d.error) : '天气接口返回异常，请检查 API Key/域名', true);
                    return;
                }
                var days = d.daily.slice(1, 7);
                S.forecastData = days;
                renderForecastGrid(days);
                // 降雨前馈动态阈值（说明书 3.3）
                var dt = computeDynamicThreshold();
                S.dynamicThreshold = dt;
                renderForecastSummary(dt);
                updateThresholdFusionHint();
            })
            .catch(function () {
                renderForecastMessage('天气接口请求失败，请检查网络或稍后重试', true);
            });
    }

    /** 预报区占位/错误提示（纯文本节点，无 HTML 注入面） */
    function renderForecastMessage(text, isError) {
        var gridEl = QH.$('forecastGrid');
        if (!gridEl) return;
        gridEl.textContent = '';
        var div = document.createElement('div');
        div.className = 'fc-empty';
        if (isError) div.style.color = '#8C6B33';
        div.textContent = text;
        gridEl.appendChild(div);
    }

    /** 预报卡片列表：日期/雨量全部走 textContent */
    function renderForecastGrid(days) {
        var gridEl = QH.$('forecastGrid');
        if (!gridEl) return;
        var frag = document.createDocumentFragment();
        days.forEach(function (day) {
            var precip = parseFloat(day.precip);
            if (!isFinite(precip)) precip = 0;
            var fxDate = String(day.fxDate || '');
            var displayDate = fxDate.indexOf('-') >= 0 ? fxDate.substring(5) : fxDate;

            var item = document.createElement('div');
            item.className = 'fc-item';

            var dateEl = document.createElement('div');
            dateEl.className = 'fc-date';
            dateEl.textContent = displayDate;

            var valueEl = document.createElement('div');
            valueEl.className = 'fc-value';
            valueEl.appendChild(document.createTextNode(precip.toFixed(1) + ' '));
            var unitEl = document.createElement('span');
            unitEl.className = 'unit';
            unitEl.textContent = 'mm';
            valueEl.appendChild(unitEl);

            var tagEl = document.createElement('div');
            tagEl.className = 'fc-tag';
            tagEl.textContent = '预报降雨';

            item.appendChild(dateEl);
            item.appendChild(valueEl);
            item.appendChild(tagEl);
            frag.appendChild(item);
        });
        gridEl.textContent = '';
        gridEl.appendChild(frag);
    }

    /** 预报摘要条（DOM 节点构建） */
    function renderForecastSummary(dt) {
        var summary = QH.$('forecastSummary');
        if (!summary) return;
        summary.style.display = 'block';
        summary.textContent = '';
        function text(s) { summary.appendChild(document.createTextNode(s)); }
        function bold(s) { var b = document.createElement('b'); b.textContent = s; summary.appendChild(b); }
        function span(s, color) {
            var sp = document.createElement('span');
            sp.style.color = color;
            sp.textContent = s;
            summary.appendChild(sp);
        }
        text('6日滚动降雨 '); bold('P6d = ' + dt.P6d.toFixed(1) + ' mm');
        text('，衰减系数 '); bold('α = ' + dt.alpha);
        text('；动态土壤湿度阈值：下限 '); bold(dt.effLower.toFixed(1) + '%');
        text('（基础 ' + dt.baseLower + '%）');
        if (dt.effUpper > dt.baseUpper) {
            text(' / 上限 '); bold(dt.effUpper.toFixed(1) + '%'); text('（蓄雨放宽）');
        } else {
            text(' / 上限 ' + dt.effUpper + '%');
        }
        if (dt.rainComing) {
            text('；'); span('降雨前馈：暂缓补水、留存天然降雨', '#2E7D8C');
        } else {
            text('；当前无降雨前馈');
        }
    }

    root.QH_WEATHER = {
        fetchWeatherData: fetchWeatherData,
        fetchWeather: fetchWeather,
        computeDynamicThreshold: computeDynamicThreshold,
        updateThresholdFusionHint: updateThresholdFusionHint,
        fetchForecast: fetchForecast,
        renderForecastMessage: renderForecastMessage,
        renderForecastGrid: renderForecastGrid,
        renderForecastSummary: renderForecastSummary
    };

    root.fetchWeather = fetchWeather;
    root.fetchForecast = fetchForecast;
    root.updateThresholdFusionHint = updateThresholdFusionHint;
    root.computeDynamicThreshold = computeDynamicThreshold;
})(typeof globalThis !== 'undefined' ? globalThis : this);
