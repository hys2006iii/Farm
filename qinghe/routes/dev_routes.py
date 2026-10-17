"""青禾智灌 —— 设备模拟器 HTTP 接口（无实物主板时演示用）。

只在环境变量 `FARM_DEV_SIM=1` 时开放；未开放时按 404 处理（不暴露功能存在，
避免生产环境被误用）。所有接口都要求登录会话。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import config, simulate, validators

bp = Blueprint('dev_api', __name__)


def _disabled():
    """模拟器未开放时统一返回 404，与「路由不存在」表现一致。"""
    return jsonify({'error': '未找到资源'}), 404


def _uid():
    """取当前会话用户 id，未登录返回 None。"""
    return session.get('user_id')


@bp.route('/api/dev/scenarios', methods=['GET'])
def api_dev_scenarios():
    """列出可用模拟场景（供前端按钮与帮助文案）。"""
    if not config.dev_sim_enabled():
        return _disabled()
    if _uid() is None:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    return jsonify({'status': 'success', 'scenarios': simulate.describe_scenarios()})


@bp.route('/api/dev/simulate', methods=['POST'])
def api_dev_simulate():
    """灌入一段模拟遥测（走与 MQTT 相同的处理链路）。"""
    if not config.dev_sim_enabled():
        return _disabled()
    uid = _uid()
    if uid is None:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    data = request.json or {}
    try:
        scenario = validators.as_str(data, 'scenario', 'normal')
        samples = validators.as_int(data, 'samples', simulate.DEFAULT_SAMPLES)
        interval = validators.as_int(data, 'interval', simulate.DEFAULT_INTERVAL_SECONDS)
    except validators.ValidationError as exc:
        return jsonify({'status': 'error', 'message': exc.message}), exc.status
    if scenario not in simulate.SCENARIOS:
        return jsonify({
            'status': 'error',
            'message': '未知场景，可选：%s' % '、'.join(simulate.SCENARIOS),
        }), 400
    result = simulate.run_simulation(uid, scenario, samples, interval)
    return jsonify({
        'status': 'success',
        'message': '已注入模拟数据',
        'scenario': result['scenario'],
        'scenario_name': simulate.SCENARIO_META[result['scenario']]['name'],
        'samples': result['samples'],
        'interval': result['interval'],
        'first_ts': result['first_ts'],
        'last_ts': result['last_ts'],
    })
