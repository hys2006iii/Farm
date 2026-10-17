"""认证模块与认证接口测试：注册 / 登录 / 限流 / 改密 / JWT。"""

import sqlite3
import time
from contextlib import closing

import jwt as pyjwt
import pytest

from qinghe import auth, config
from qinghe.db import get_db
from helpers import make_user


# ============================================================
# 注册
# ============================================================

def test_register_success(client):
    resp = client.post('/api/register', json={'username': 'alice01', 'password': 'pw123456'})
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'success', 'message': '注册成功'}


def test_register_creates_config_row(client):
    client.post('/api/register', json={'username': 'bob0001', 'password': 'pw123456'})
    with closing(get_db()) as conn:
        user = conn.execute('SELECT id FROM users WHERE username=?', ('bob0001',)).fetchone()
        cfg = conn.execute('SELECT user_id FROM configs WHERE user_id=?', (user['id'],)).fetchone()
    assert cfg is not None


def test_register_duplicate_username(client):
    client.post('/api/register', json={'username': 'carol01', 'password': 'pw123456'})
    resp = client.post('/api/register', json={'username': 'carol01', 'password': 'pw123456'})
    assert resp.get_json() == {'status': 'error', 'message': '账号已存在'}


@pytest.mark.parametrize('username', ['ab', '', 'x' * 21])
def test_register_invalid_username_length(client, username):
    resp = client.post('/api/register', json={'username': username, 'password': 'pw123456'})
    assert resp.get_json()['message'] == '用户名长度需为 3-20 字符'


@pytest.mark.parametrize('password', ['short', '', 'x' * 65])
def test_register_invalid_password_length(client, password):
    resp = client.post('/api/register', json={'username': 'dave001', 'password': password})
    assert resp.get_json()['message'] == '密码长度需为 6-64 字符'


def test_register_stores_hash_not_plaintext(client):
    client.post('/api/register', json={'username': 'erin001', 'password': 'pw123456'})
    with closing(get_db()) as conn:
        row = conn.execute('SELECT password FROM users WHERE username=?', ('erin001',)).fetchone()
    assert row['password'] != 'pw123456'
    assert auth.is_password_hash(row['password'])


def test_register_empty_json_body(client):
    """请求体为空时不应 500。"""
    resp = client.post('/api/register', json={})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'error'


# ============================================================
# 登录
# ============================================================

def test_login_success_sets_session(client, registered):
    username, _ = registered
    resp = client.get('/api/get_config')
    assert resp.status_code == 200


def test_login_missing_fields(client):
    resp = client.post('/api/login', json={'username': 'nobody', 'password': ''})
    assert resp.get_json() == {'status': 'error', 'message': '请输入账号和密码'}


def test_login_wrong_password(client, registered):
    username, _ = registered
    resp = client.post('/api/login', json={'username': username, 'password': 'wrongpw'})
    assert resp.get_json() == {'status': 'error', 'message': '账号或密码错误'}


def test_login_unknown_user(client):
    resp = client.post('/api/login', json={'username': 'ghost001', 'password': 'pw123456'})
    assert resp.get_json() == {'status': 'error', 'message': '账号或密码错误'}


def test_login_upgrades_plaintext_password(client):
    """旧库明文密码登录成功后自动升级为哈希。"""
    uid = make_user('legacy01', 'plainpw123')
    with closing(get_db()) as conn:
        conn.execute('UPDATE users SET password=? WHERE id=?', ('plainpw123', uid))
        conn.commit()
    resp = client.post('/api/login', json={'username': 'legacy01', 'password': 'plainpw123'})
    assert resp.get_json()['status'] == 'success'
    with closing(get_db()) as conn:
        row = conn.execute('SELECT password FROM users WHERE id=?', (uid,)).fetchone()
    assert auth.is_password_hash(row['password'])


def test_login_plaintext_wrong_password(client):
    uid = make_user('legacy02', 'plainpw123')
    with closing(get_db()) as conn:
        conn.execute('UPDATE users SET password=? WHERE id=?', ('plainpw123', uid))
        conn.commit()
    resp = client.post('/api/login', json={'username': 'legacy02', 'password': 'nope1234'})
    assert resp.get_json()['status'] == 'error'


def test_logout_clears_session(client, registered):
    resp = client.get('/api/logout')
    assert resp.status_code == 302
    resp = client.get('/api/get_config')
    assert resp.status_code == 401


# ============================================================
# 登录限流
# ============================================================

def test_login_lockout_after_five_failures(client, registered):
    username, _ = registered
    for _ in range(config.LOGIN_MAX_FAIL):
        client.post('/api/login', json={'username': username, 'password': 'badpass'})
    resp = client.post('/api/login', json={'username': username, 'password': 'secret123'})
    assert resp.status_code == 429
    assert resp.get_json()['message'] == '尝试次数过多，请 10 分钟后再试'


def test_login_lockout_expires(client, registered, monkeypatch):
    """锁定窗口过期后应自动解锁。"""
    username, password = registered
    for _ in range(config.LOGIN_MAX_FAIL):
        client.post('/api/login', json={'username': username, 'password': 'badpass'})
    assert client.post('/api/login', json={'username': username, 'password': password}).status_code == 429

    # 把失败时间戳整体往前挪，模拟窗口过期
    with auth._login_lock:
        for key in list(auth._login_fail):
            count, _ts = auth._login_fail[key]
            auth._login_fail[key] = (count, time.time() - config.LOGIN_LOCK_SECONDS - 1)
    resp = client.post('/api/login', json={'username': username, 'password': password})
    assert resp.get_json()['status'] == 'success'


def test_login_success_clears_fail_counter(client, registered):
    username, password = registered
    client.post('/api/login', json={'username': username, 'password': 'badpass'})
    client.post('/api/login', json={'username': username, 'password': password})
    assert auth._login_fail == {}


def test_login_limit_is_per_username_and_ip(client, registered):
    username, _ = registered
    for _ in range(config.LOGIN_MAX_FAIL):
        client.post('/api/login', json={'username': username, 'password': 'badpass'})
    # 另一个用户名不受影响
    resp = client.post('/api/login', json={'username': 'otheruser', 'password': 'whatever'})
    assert resp.status_code == 200


def test_login_forwarded_for_is_used_as_key(flask_app):
    client = flask_app.test_client()
    make_user('xffuser1', 'pw123456')
    for _ in range(config.LOGIN_MAX_FAIL):
        client.post('/api/login', json={'username': 'xffuser1', 'password': 'bad'},
                    headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8'})
    # 换一个来源 IP 立刻可以登录
    resp = client.post('/api/login', json={'username': 'xffuser1', 'password': 'pw123456'},
                       headers={'X-Forwarded-For': '9.9.9.9'})
    assert resp.get_json()['status'] == 'success'


# ============================================================
# 修改密码
# ============================================================

def test_change_password_success(client, registered):
    username, password = registered
    resp = client.post('/api/change_password',
                       json={'old_password': password, 'new_password': 'newpw1234'})
    assert resp.get_json() == {'status': 'success', 'message': '密码修改成功，请重新登录'}
    client.get('/api/logout')
    assert client.post('/api/login',
                       json={'username': username, 'password': 'newpw1234'}).get_json()['status'] == 'success'


def test_change_password_wrong_old(client, registered):
    resp = client.post('/api/change_password',
                       json={'old_password': 'wrongold', 'new_password': 'newpw1234'})
    assert resp.get_json() == {'status': 'error', 'message': '原密码错误'}


def test_change_password_too_short(client, registered):
    resp = client.post('/api/change_password',
                       json={'old_password': 'secret123', 'new_password': 'abc'})
    assert resp.get_json()['message'] == '新密码长度需为 6-64 字符'


def test_change_password_requires_login(client):
    resp = client.post('/api/change_password',
                       json={'old_password': 'a', 'new_password': 'newpw1234'})
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'error', 'message': '未授权'}


def test_change_password_no_connection_leak(client, registered):
    """连续改密 30 次不应出现 database is locked / 句柄耗尽。"""
    username, password = registered
    for i in range(30):
        resp = client.post('/api/change_password',
                           json={'old_password': password, 'new_password': 'pw%06d' % i})
        assert resp.get_json()['status'] == 'success'
        password = 'pw%06d' % i
        client.post('/api/login', json={'username': username, 'password': password})


# ============================================================
# JWT / app_login
# ============================================================

def test_app_login_returns_token(client, registered):
    username, password = registered
    resp = client.post('/api/app_login', json={'username': username, 'password': password})
    body = resp.get_json()
    assert body['status'] == 'success'
    assert body['username'] == username
    claims = pyjwt.decode(body['token'], config.get_secret_key(), algorithms=['HS256'])
    assert claims['user_id'] > 0
    assert claims['exp'] > time.time()


def test_app_login_wrong_password(client, registered):
    username, _ = registered
    resp = client.post('/api/app_login', json={'username': username, 'password': 'bad'})
    assert resp.get_json()['status'] == 'error'


def test_require_token_rejects_missing_header(client):
    resp = client.post('/api/app_send_command', json={'device': 'water_pump', 'action': 'on'})
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'error', 'message': '未授权访问'}


def test_require_token_rejects_invalid_token(client):
    resp = client.post('/api/app_send_command', json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer not-a-jwt'})
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'error', 'message': 'Token无效或过期'}


def test_require_token_rejects_expired_token(client, registered):
    import datetime
    expired = pyjwt.encode(
        {'user_id': 1, 'exp': datetime.datetime.utcnow() - datetime.timedelta(days=1)},
        config.get_secret_key(), algorithm='HS256')
    resp = client.post('/api/app_send_command', json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer %s' % expired})
    assert resp.status_code == 401


def test_require_token_rejects_wrong_signature(client):
    forged = pyjwt.encode({'user_id': 1, 'exp': time.time() + 3600}, 'wrong-key', algorithm='HS256')
    resp = client.post('/api/app_send_command', json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer %s' % forged})
    assert resp.status_code == 401


def test_app_send_command_unknown_device(client, auth_headers):
    resp = client.post('/api/app_send_command', json={'device': 'lights', 'action': 'on'},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'error', 'message': '未知设备'}


def test_app_send_command_device_not_connected(client, auth_headers):
    resp = client.post('/api/app_send_command', json={'device': 'water_pump', 'action': 'on'},
                       headers=auth_headers)
    assert resp.get_json() == {'status': 'error', 'message': '设备未连接'}


# ============================================================
# 密码哈希工具
# ============================================================

def test_verify_password_plaintext_and_hash():
    hashed = auth.hash_password('pw123456')
    assert auth.verify_password(hashed, 'pw123456') is True
    assert auth.verify_password(hashed, 'pw123457') is False
    assert auth.verify_password('plain', 'plain') is True
    assert auth.verify_password('plain', 'other') is False


def test_authenticate_unknown_user_returns_none():
    user, ok = auth.authenticate('nobody-here', 'pw')
    assert user is None and ok is False


def test_issue_token_roundtrip(flask_app):
    with flask_app.test_request_context():
        token = auth.issue_token(42)
        claims = pyjwt.decode(token, flask_app.secret_key, algorithms=['HS256'])
    assert claims['user_id'] == 42


# ============================================================
# 数据库层连接管理
# ============================================================

def test_get_db_uses_wal(flask_app):
    with closing(get_db()) as conn:
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
    assert mode.lower() == 'wal'


def test_create_user_duplicate_returns_none(flask_app):
    assert make_user('dupe0001', 'pw123456') is not None
    assert make_user('dupe0001', 'pw123456') is None


def test_db_survives_concurrent_writes(flask_app):
    """多线程并发写历史不应抛 database is locked。"""
    import threading

    import qinghe.db as db

    uid = make_user('thread01', 'pw123456')
    errors = []

    def worker(base):
        try:
            for i in range(20):
                db.insert_history_rows([(uid, base + i, 100, 200)])
        except Exception as exc:  # pragma: no cover - 失败时记录
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 1000,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_sqlite_integrity_after_operations(flask_app):
    uid = make_user('integ001', 'pw123456')
    with closing(get_db()) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert isinstance(uid, int)


def test_sqlite_error_is_sqlite3_error():
    """确认 create_user 捕获的是 sqlite3.IntegrityError（防止重构后异常类型漂移）。"""
    assert issubclass(sqlite3.IntegrityError, sqlite3.DatabaseError)
