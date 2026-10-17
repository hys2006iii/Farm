"""青禾智灌 —— NF4 / NF5 的 HTTP 接口（决策预案 + 节水减碳看板）。

蓝图变量固定为 `bp`，由应用工厂统一注册；所有接口沿用会话登录态
（`session['user_id']`），未登录返回 401 JSON。

路由：
- POST /api/plan/propose   生成待确认预案
- POST /api/plan/confirm   人工确认并下发
- POST /api/plan/reject    人工拒绝
- GET  /api/plans          预案列表
- GET  /api/metrics        节水减碳估算（含逐日序列）
- GET  /api/auto_control   查询服务端自动调控开关
- POST /api/auto_control   开启 / 关闭服务端自动调控
"""

from flask import Blueprint, jsonify, request, session

from qinghe import autocontrol, metrics, planner

bp = Blueprint('insight', __name__)

#: 预案列表默认条数与上限
DEFAULT_PLAN_LIMIT = 20
MAX_PLAN_LIMIT = 100

#: 看板默认天数与上限
DEFAULT_METRIC_DAYS = 7
MAX_METRIC_DAYS = 90


def _current_uid():
    """取当前登录用户 id；未登录返回 None。"""
    try:
        uid = session.get('user_id')
    except Exception:
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


@bp.post('/api/plan/propose')
def plan_propose():
    """生成一条待人工确认的决策预案（无 AI Key 时自动走规则回退）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    body = _json_body()
    question = body.get('question', '')
    if not isinstance(question, str):
        return jsonify({'error': 'question 必须是字符串'}), 400
    if len(question) > 500:
        return jsonify({'error': 'question 过长（最多 500 字）'}), 400
    try:
        result = planner.propose_plan(uid, question.strip())
    except Exception as exc:
        return jsonify({'error': '预案生成失败：%s' % exc}), 500
    return jsonify(result), 200


@bp.post('/api/plan/confirm')
def plan_confirm():
    """人工确认预案并逐条下发（校验归属、pending 状态与 600 秒 TTL）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    plan_id = _parse_int(_json_body().get('id'), None, 1, 2 ** 31 - 1)
    if plan_id is None:
        return jsonify({'error': '缺少合法的预案 id'}), 400
    try:
        result = planner.confirm_plan(uid, plan_id)
    except Exception as exc:
        return jsonify({'error': '预案确认失败：%s' % exc}), 500
    if result.get('ok'):
        return jsonify(result), 200
    if not result.get('error'):
        result = dict(result, error='预案下发失败（设备可能未连接），请稍后重试')
    return jsonify(result), 400


@bp.post('/api/plan/reject')
def plan_reject():
    """人工拒绝一条预案（可附拒绝原因）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    body = _json_body()
    plan_id = _parse_int(body.get('id'), None, 1, 2 ** 31 - 1)
    if plan_id is None:
        return jsonify({'error': '缺少合法的预案 id'}), 400
    reason = body.get('reason', '')
    if not isinstance(reason, str):
        return jsonify({'error': 'reason 必须是字符串'}), 400
    if len(reason) > 200:
        return jsonify({'error': 'reason 过长（最多 200 字）'}), 400
    try:
        ok = planner.reject_plan(uid, plan_id, reason.strip())
    except Exception as exc:
        return jsonify({'error': '预案拒绝失败：%s' % exc}), 500
    if not ok:
        return jsonify({'ok': False, 'error': '预案不存在、无权操作或状态不允许'}), 400
    return jsonify({'ok': True, 'id': plan_id}), 200


@bp.get('/api/plans')
def plan_list():
    """按时间倒序列出本人预案（`?limit=20`，上限 100）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    limit = _parse_int(request.args.get('limit'), DEFAULT_PLAN_LIMIT, 1, MAX_PLAN_LIMIT)
    if limit is None:
        return jsonify({'error': 'limit 必须是 1~%d 的整数' % MAX_PLAN_LIMIT}), 400
    try:
        plans = planner.list_plans(uid, limit)
    except Exception as exc:
        return jsonify({'error': '预案列表读取失败：%s' % exc}), 500
    return jsonify({'plans': plans, 'count': len(plans)}), 200


@bp.get('/api/metrics')
def metrics_overview():
    """节水减碳估算：返回汇总口径 + 逐日序列（工程估算，非实测）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    days = _parse_int(request.args.get('days'), DEFAULT_METRIC_DAYS, 1, MAX_METRIC_DAYS)
    if days is None:
        return jsonify({'error': 'days 必须是 1~%d 的整数' % MAX_METRIC_DAYS}), 400
    try:
        summary = metrics.estimate(uid, days)
        series = metrics.daily_series(uid, days)
    except Exception as exc:
        return jsonify({'error': '指标估算失败：%s' % exc}), 500
    payload = dict(summary)
    payload['series'] = series
    return jsonify(payload), 200


@bp.get('/api/auto_control')
def auto_control_status():
    """查询服务端自动调控开关与最近一次动作。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    try:
        return jsonify(autocontrol.status(uid)), 200
    except Exception as exc:
        return jsonify({'error': '自动调控状态读取失败：%s' % exc}), 500


@bp.post('/api/auto_control')
def auto_control_toggle():
    """开启 / 关闭服务端自动调控（body `{'enabled': bool}`）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    body = _json_body()
    enabled = body.get('enabled')
    if not isinstance(enabled, bool):
        return jsonify({'error': 'enabled 必须是布尔值'}), 400
    try:
        autocontrol.set_enabled(uid, enabled)
        return jsonify(autocontrol.status(uid)), 200
    except Exception as exc:
        return jsonify({'error': '自动调控开关设置失败：%s' % exc}), 500
