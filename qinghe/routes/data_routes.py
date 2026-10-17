"""青禾智灌 —— 数据类 HTTP 接口。

覆盖：/api/history、/api/forecast、/api/reverse_geocode、/api/notify_alert。
修复点：history 的 limit clamp 到 1~5000；geo_cache 建表已移出请求路径。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import alerts, config, db, validators, weather

bp = Blueprint('data_api', __name__)


def _parse_limit(raw, default=None):
    """解析并 clamp 历史查询 limit；非法值回退默认值。"""
    default = config.HISTORY_DEFAULT_LIMIT if default is None else default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(config.HISTORY_MIN_LIMIT, min(value, config.HISTORY_MAX_LIMIT))


@bp.route('/api/history', methods=['GET'])
def api_history():
    """取当前用户最近的传感器历史（按时间升序返回）。

    每行含 `ts` / `water_adc` / `soil_adc` / `do_mgl` / `eh_mv`；后两项是
    D-01 迁移新增的列，早期数据为 `None`（JSON `null`），前端据此回退。
    排序与 limit 语义保持不变。
    """
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    uid = session['user_id']
    limit = _parse_limit(request.args.get('limit'))
    rows = db.query_history(uid, limit, farm_id=db.get_active_farm_id(uid))
    result = [
        {
            'ts': r['ts'],
            'water_adc': r['water_adc'],
            'soil_adc': r['soil_adc'],
            'do_mgl': r['do_mgl'],
            'eh_mv': r['eh_mv'],
        }
        for r in rows
    ]
    result.reverse()
    return jsonify({'data': result})


@bp.route('/api/forecast', methods=['GET'])
def api_forecast():
    """降雨预报代理：从配置读取和风天气域名与 Key，转发 7 日预报，避免前端跨域。

    失败（未配置 Key / 上游异常 / 上游非 JSON）返回 **502**，响应体仍是
    `{'code': 'ERR', 'error': ...}` 原样不变，前端 `static/js/weather.js` 只读
    body 不读状态码，故降级分支照常走通。
    """
    if 'user_id' not in session:
        return jsonify({'error': '未授权访问'}), 401
    cfg = db.load_weather_config(session['user_id'])
    if not cfg or not cfg['weather_key']:
        return jsonify({'code': 'ERR', 'error': '未配置天气 API Key'}), 502
    domain = (cfg['weather_domain'] or config.DEFAULT_WEATHER_DOMAIN).strip()
    lng = request.args.get('lng') or cfg['farm_lng'] or '118.78'
    lat = request.args.get('lat') or cfg['farm_lat'] or '31.90'
    payload = weather.fetch_forecast(domain, lng, lat, cfg['weather_key'])
    if weather.forecast_failed(payload):
        return jsonify(payload), 502
    return jsonify(payload)


@bp.route('/api/reverse_geocode')
def api_reverse_geocode():
    """逆地理编码：返回具体位置（市·区·街道·社区，简体）。

    唯一反查源 Photon(komoot/OSM)，结果按坐标缓存到 DB（表在启动时已建），
    重复刷新不再打外部接口，避免浏览器跨域与免费额度限流。
    """
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    if not lat or not lng:
        return jsonify({'error': '缺少坐标'}), 400
    try:
        flat_lat = float(lat)
        flat_lng = float(lng)
    except Exception:
        return jsonify({'error': '坐标格式错误'}), 400

    name, _cached = weather.geo_lookup(flat_lat, flat_lng)
    if name:
        return jsonify({'name': name})
    # 都没解析到：按坐标兜底（不缓存，便于下次重试）
    return jsonify({'name': weather.geo_fallback_text(flat_lat, flat_lng)})


@bp.route('/api/notify_alert', methods=['POST'])
def api_notify_alert():
    """前端检测到设备告警后调用，转发到用户配置的 webhook。

    `msg` / `level` 类型错误返回 400（不 500）；`msg` 截断到 500 字符、
    `level` 截断到 20 字符；空 `msg` 返回 400。
    """
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    data = request.json or {}
    try:
        msg = validators.truncated(data, 'msg', '', config.ALERT_CONTENT_MAX_LEN).strip()
        level = validators.truncated(data, 'level', 'warn', config.ALERT_LEVEL_MAX_LEN).strip()
    except validators.ValidationError as exc:
        return jsonify({'status': 'error', 'message': exc.message}), exc.status
    if not msg:
        return jsonify({'status': 'error', 'message': '缺少告警内容'}), 400
    ok = alerts.notify_webhook(session['user_id'], '[青禾智灌] %s 告警' % level, msg)
    return jsonify({'status': 'success' if ok else 'skipped', 'sent': ok})
