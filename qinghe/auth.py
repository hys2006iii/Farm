"""青禾智灌 —— 认证模块。

覆盖：注册 / 登录 / 登出 / 改密 / JWT 下发与校验 / 登录限流（线程安全）。
对外函数签名与旧版 app.py 的行为保持一致，仅修复连接泄漏与入参校验。
"""

import datetime
import threading
import time
from functools import wraps

import jwt
from flask import jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from qinghe import config, db

#: 登录失败计数 {f"{username}:{ip}": (fail_count, last_fail_ts)}
_login_fail = {}
_login_lock = threading.Lock()

#: 密码哈希前缀（用于兼容旧库明文密码的自动升级）
_HASH_PREFIXES = ('pbkdf2:', 'scrypt:', 'sha256:')


def _client_ip() -> str:
    """取用于限流的来源 IP。

    **默认不信任** `X-Forwarded-For`：直连部署时该头由客户端完全控制，
    换一个头即可重置失败计数、无限爆破密码。只有显式设置
    `FARM_TRUST_PROXY=1`（确认服务在 nginx / waitress 反向代理之后）时，
    才取 XFF 的第一跳（最靠近客户端的地址）。
    """
    if config.trust_proxy():
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _login_key(username: str) -> str:
    """限流键：用户名 + 来源 IP。"""
    return '%s:%s' % (username, _client_ip())


def _login_locked(username: str) -> bool:
    """该 用户名+IP 是否已被锁定。锁定窗口过期则自动重置。"""
    key = _login_key(username)
    with _login_lock:
        entry = _login_fail.get(key)
        if not entry:
            return False
        count, ts = entry
        if time.time() - ts > config.LOGIN_LOCK_SECONDS:
            _login_fail.pop(key, None)
            return False
        return count >= config.LOGIN_MAX_FAIL


def _record_login_fail(username: str) -> None:
    """记录一次登录失败（窗口内累加，窗口外重新计数）。"""
    key = _login_key(username)
    with _login_lock:
        entry = _login_fail.get(key)
        if entry and time.time() - entry[1] <= config.LOGIN_LOCK_SECONDS:
            _login_fail[key] = (entry[0] + 1, time.time())
        else:
            _login_fail[key] = (1, time.time())


def _clear_login_fail(username: str) -> None:
    """登录成功后清空失败计数。"""
    key = _login_key(username)
    with _login_lock:
        _login_fail.pop(key, None)


def reset_login_failures() -> None:
    """清空全部限流状态（测试用）。"""
    with _login_lock:
        _login_fail.clear()


# ------------------------------------------------------------
# 公开限流 API：供路由层调用，避免跨模块依赖下划线私有函数
# ------------------------------------------------------------

def login_throttle(username: str) -> bool:
    """该「用户名 + 来源 IP」当前是否已被限流锁定。

    路由层统一调用本函数，不要直接依赖 `_login_locked`。
    """
    return _login_locked(username)


def record_login_failure(username: str) -> None:
    """记录一次登录失败（路由层统一入口）。"""
    _record_login_fail(username)


def clear_login_failures(username: str) -> None:
    """登录成功后清空该「用户名 + 来源 IP」的失败计数。"""
    _clear_login_fail(username)


def is_password_hash(stored: str) -> bool:
    """判断库中存的是否已是哈希（否则视为旧库明文密码）。"""
    return bool(stored) and stored.startswith(_HASH_PREFIXES)


def verify_password(stored: str, password: str) -> bool:
    """校验密码，兼容旧库明文。"""
    if is_password_hash(stored):
        return check_password_hash(stored, password)
    return stored == password


def upgrade_plaintext_password(uid: int, password: str) -> None:
    """旧库明文密码命中后自动升级为哈希。"""
    db.update_password(uid, generate_password_hash(password))


def hash_password(password: str) -> str:
    """生成密码哈希。"""
    return generate_password_hash(password)


def issue_token(uid: int, days: int = 7) -> str:
    """签发 7 天有效期的 HS256 JWT（payload 仅含 user_id 与 exp）。"""
    from flask import current_app
    return jwt.encode(
        {
            'user_id': uid,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=days),
        },
        current_app.secret_key,
        algorithm='HS256',
    )


def authenticate(username: str, password: str):
    """校验账号密码。

    返回: (user_row, ok)。user_row 为 None 表示用户不存在。
    """
    user = db.get_user_by_username(username)
    if not user:
        return None, False
    stored = user['password']
    ok = verify_password(stored, password)
    if ok and not is_password_hash(stored):
        upgrade_plaintext_password(user['id'], password)
    return user, ok


def require_token(f):
    """装饰器：校验 `Authorization: Bearer <jwt>`，把 user_id 作为首个参数注入。"""

    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import current_app
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'status': 'error', 'message': '未授权访问'}), 401

        try:
            claims = jwt.decode(token, current_app.secret_key, algorithms=['HS256'])
            uid = claims['user_id']
        except Exception:
            return jsonify({'status': 'error', 'message': 'Token无效或过期'}), 401

        return f(uid, *args, **kwargs)

    return wrapper


def current_uid():
    """取当前会话用户 id，未登录返回 None。"""
    return session.get('user_id')
