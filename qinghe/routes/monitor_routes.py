"""青禾智灌 —— NF1 / NF2 / NF3 的 HTTP 接口（告警中心 + 运行日志 + 设备状态）。

蓝图变量固定为 `bp`，由应用工厂统一注册；所有接口沿用会话登录态
（`session['user_id']`），未登录返回 401 JSON。

路由：
- GET  /api/alerts          服务端告警列表（分页 / 增量拉取）
- POST /api/alerts/ack      确认（已读）一条告警
- GET  /api/logs            运行日志列表（分页 / 增量拉取）
- GET  /api/device_status   设备在线状态（心跳超时判定）
"""

from flask import Blueprint, jsonify, request, session

from qinghe import alert_center, heartbeat, logbook

bp = Blueprint('monitor', __name__)

#: 告警列表默认条数与上限
DEFAULT_ALERT_LIMIT = 100
MAX_ALERT_LIMIT = 500

#: 日志列表默认条数与上限
DEFAULT_LOG_LIMIT = 200
MAX_LOG_LIMIT = 1000


def _current_uid():
    """取当前登录用户 id；未登录返回 None。"""
    try:
        uid = session.get('user_id')
    except Exception:  # noqa: BLE001 - 无请求上下文时 session 访问会抛错
        return None
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def _unauthorized():
    """统一的未登录响应。"""
    return jsonify({'error': '未登录'}), 401


def _json_body() -> dict:
    """安全读取 JSON 请求体，非法 / 为空时返回空 dict。"""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _parse_int(value, default, minimum, maximum):
    """把入参解析成区间内的整数；非法返回 None（便于调用方返回 4xx）。"""
    if value is None or value == '':
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


@bp.get('/api/alerts')
def list_alerts():
    """返回当前用户最近的告警，按时间倒序。

    查询参数：
        limit    1..500，默认 100
        since_ts 只返回不早于该毫秒时间戳的告警，默认 0
    """
    uid = _current_uid()
    if uid is None:
        return _unauthorized()

    limit = _parse_int(request.args.get('limit'), DEFAULT_ALERT_LIMIT, 1, MAX_ALERT_LIMIT)
    if limit is None:
        return jsonify({'status': 'error', 'error': 'limit 必须是 1-500 的整数'}), 400
    since_ts = _parse_int(request.args.get('since_ts'), 0, 0, 2 ** 53)
    if since_ts is None:
        return jsonify({'status': 'error', 'error': 'since_ts 必须是非负整数'}), 400

    items = alert_center.list_alerts(uid, limit=limit, since_ts=since_ts)
    return jsonify({'status': 'success', 'count': len(items), 'alerts': items})


@bp.post('/api/alerts/ack')
def ack_alert():
    """把一条告警标记为已确认（只能确认自己的告警）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()

    payload = _json_body()
    alert_id = _parse_int(payload.get('id'), None, 1, 2 ** 53)
    if alert_id is None:
        return jsonify({'status': 'error', 'error': '缺少合法的告警 id'}), 400

    if not alert_center.ack_alert(uid, alert_id):
        return jsonify({'status': 'error', 'error': '告警不存在或不属于当前用户'}), 404
    return jsonify({'status': 'success', 'id': alert_id, 'acked': True})


@bp.get('/api/logs')
def list_logs():
    """返回当前用户最近的运行日志，按时间倒序。

    查询参数：
        limit    1..1000，默认 200
        since_ts 只返回不早于该毫秒时间戳的日志，默认 0
    """
    uid = _current_uid()
    if uid is None:
        return _unauthorized()

    limit = _parse_int(request.args.get('limit'), DEFAULT_LOG_LIMIT, 1, MAX_LOG_LIMIT)
    if limit is None:
        return jsonify({'status': 'error', 'error': 'limit 必须是 1-1000 的整数'}), 400
    since_ts = _parse_int(request.args.get('since_ts'), 0, 0, 2 ** 53)
    if since_ts is None:
        return jsonify({'status': 'error', 'error': 'since_ts 必须是非负整数'}), 400

    items = logbook.query_logs(uid, limit=limit, since_ts=since_ts)
    return jsonify({'status': 'success', 'count': len(items), 'logs': items})


@bp.get('/api/device_status')
def device_status():
    """返回设备在线状态。

    查询参数：
        offline_seconds 可选，覆盖默认的离线判定阈值（秒），1..86400
    """
    uid = _current_uid()
    if uid is None:
        return _unauthorized()

    offline_seconds = _parse_int(request.args.get('offline_seconds'), None, 1, 86400)
    if offline_seconds is None and request.args.get('offline_seconds'):
        return jsonify({'status': 'error', 'error': 'offline_seconds 必须是 1-86400 的整数'}), 400

    status = heartbeat.get_status(uid, offline_seconds=offline_seconds)
    payload = {'status': 'success'}
    payload.update(status)
    return jsonify(payload)
