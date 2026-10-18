"""青禾智灌 —— 页面与应用端指令 HTTP 接口。

覆盖：/ 、/index、/api/app_send_command。端点名（endpoint）保持旧版
函数名，确保 `url_for('app_api.route_root')` 等价于旧版 `url_for('route_root')`。
"""

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from qinghe import auth, iot, validators
from qinghe.iot import PROP_MAP

bp = Blueprint('app_api', __name__)


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


@bp.route('/knowledge')
def route_knowledge():
    """知识库页面（灌溉科普 + 系统内核说明）：未登录跳回首页。"""
    if 'user_id' not in session:
        return redirect(url_for('app_api.route_root'))
    return render_template('knowledge.html', username=session.get('username'))


@bp.route('/api/app_send_command', methods=['POST'])
@auth.require_token
def api_app_command(uid):
    """App 端下发控制指令（JWT 鉴权）。"""
    try:
        payload = validators.get_json_object(request)
    except validators.ValidationError as exc:
        return jsonify({'status': 'error', 'message': exc.message}), exc.status
    prop = PROP_MAP.get(payload.get('device'))
    if not prop:
        return jsonify({'status': 'error', 'message': '未知设备'}), 400
    action = payload.get('action')
    # 只接受 on/off：旧版把任意值都当 off，容易把拼写错误当成功下发
    if action not in ('on', 'off'):
        return jsonify({'status': 'error', 'message': 'action 仅支持 on / off'}), 400
    ok = iot.send_property_command(uid, {prop: 'on' if action == 'on' else 'off'})
    if not ok:
        return jsonify({'status': 'error', 'message': '设备未连接'})
    return jsonify({'status': 'success', 'message': '指令已发送'})
