"""青禾智灌 —— 页面与应用端指令 HTTP 接口。

覆盖：/ 、/index、/api/app_send_command。端点名（endpoint）保持旧版
函数名，确保 `url_for('app_api.route_root')` 等价于旧版 `url_for('route_root')`。
"""

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from qinghe import auth, iot

bp = Blueprint('app_api', __name__)

#: 只允许白名单内的属性，防止任意下发
PROP_MAP = {
    'water_pump': 'water_pump',
    'air_pump': 'air_pump',
}


@bp.route('/')
def route_root():
    """首页：已登录跳转控制台，未登录渲染登录页。"""
    if 'user_id' in session:
        return redirect(url_for('app_api.route_index'))
    return render_template('login.html')


@bp.route('/index')
def route_index():
    """控制台页面：未登录跳回首页。"""
    if 'user_id' not in session:
        return redirect(url_for('app_api.route_root'))
    return render_template('index.html', username=session.get('username'))


@bp.route('/api/app_send_command', methods=['POST'])
@auth.require_token
def api_app_command(uid):
    """App 端下发控制指令（JWT 鉴权）。"""
    payload = request.json or {}
    prop = PROP_MAP.get(payload.get('device'))
    if not prop:
        return jsonify({'status': 'error', 'message': '未知设备'}), 400
    action = payload.get('action')
    ok = iot.send_property_command(uid, {prop: 'on' if action == 'on' else 'off'})
    if not ok:
        return jsonify({'status': 'error', 'message': '设备未连接'})
    return jsonify({'status': 'success', 'message': '指令已发送'})
