"""青禾智灌 —— 认证相关 HTTP 接口。

覆盖：/api/register、/api/login、/api/logout、/api/change_password、/api/app_login。
响应体字段与状态码与旧版 app.py 逐字一致。
"""

from flask import Blueprint, jsonify, redirect, request, session, url_for

from qinghe import auth, config, db, iot

bp = Blueprint('auth_api', __name__)


@bp.route('/api/register', methods=['POST'])
def api_register():
    """注册新账号：校验用户名/密码长度，成功后同时初始化 configs 行。"""
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    # 输入校验：长度限制，防注入/超大请求
    if not (config.USERNAME_MIN_LEN <= len(username) <= config.USERNAME_MAX_LEN):
        return jsonify({'status': 'error', 'message': '用户名长度需为 3-20 字符'})
    if not (config.PASSWORD_MIN_LEN <= len(password) <= config.PASSWORD_MAX_LEN):
        return jsonify({'status': 'error', 'message': '密码长度需为 6-64 字符'})
    uid = db.create_user(username, auth.hash_password(password))
    if uid is None:
        return jsonify({'status': 'error', 'message': '账号已存在'})
    return jsonify({'status': 'success', 'message': '注册成功'})


@bp.route('/api/login', methods=['POST'])
def api_login():
    """网页登录：限流 → 校验密码 → 写入 session。"""
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'status': 'error', 'message': '请输入账号和密码'})
    if auth.login_throttle(username):
        return jsonify({'status': 'error', 'message': '尝试次数过多，请 10 分钟后再试'}), 429
    user, ok = auth.authenticate(username, password)
    if ok:
        auth.clear_login_failures(username)
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'status': 'success', 'message': '登录成功'})
    auth.record_login_failure(username)
    return jsonify({'status': 'error', 'message': '账号或密码错误'})


@bp.route('/api/logout')
def api_logout():
    """登出：清空会话并跳回首页。"""
    session.clear()
    return redirect(url_for('app_api.route_root'))


@bp.route('/api/change_password', methods=['POST'])
def api_change_password():
    """修改密码：校验原密码与新密码长度，成功后需重新登录。"""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    data = request.json or {}
    uid = session['user_id']
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''
    if not (config.PASSWORD_MIN_LEN <= len(new_password) <= config.PASSWORD_MAX_LEN):
        return jsonify({'status': 'error', 'message': '新密码长度需为 6-64 字符'})
    user = db.get_user_by_id(uid)
    if not user or not auth.verify_password(user['password'], old_password):
        return jsonify({'status': 'error', 'message': '原密码错误'})
    db.update_password(uid, auth.hash_password(new_password))
    return jsonify({'status': 'success', 'message': '密码修改成功，请重新登录'})


@bp.route('/api/app_login', methods=['POST'])
def api_app_login():
    """App 登录：返回 7 天 JWT，并顺带建立该用户的 MQTT 连接。"""
    payload = request.json or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    if auth.login_throttle(username):
        return jsonify({'status': 'error', 'message': '尝试次数过多，请 10 分钟后再试'}), 429
    user, ok = auth.authenticate(username, password)
    if ok:
        auth.clear_login_failures(username)
        token = auth.issue_token(user['id'])
        iot.connect_huawei_iot(user['id'])
        return jsonify({
            'status': 'success',
            'message': '登录成功',
            'token': token,
            'username': user['username'],
        })
    auth.record_login_failure(username)
    return jsonify({'status': 'error', 'message': '账号或密码错误'})
