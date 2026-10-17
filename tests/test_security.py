"""安全回归测试：JWT 密钥、类型混淆入参、代理信任边界、MQTT 端口兜底。

对应体检报告 P0-1 / P0-2 / P1-3 / P1-4 / P1-5 五项缺陷，每个缺陷都有独立用例，
确保修复不被后续改动回退。
"""

import time

import jwt as pyjwt
import pytest

from helpers import make_user
from qinghe import auth, config, iot, validators


# ============================================================
# P0-1：JWT 鉴权不可用硬编码常量伪造
# ============================================================

def test_secret_key_is_not_hardcoded_fallback(monkeypatch):
    """未配置 FARM_SECRET_KEY 时不得回落到硬编码常量。"""
    monkeypatch.delenv('FARM_SECRET_KEY', raising=False)
    config.reset_runtime_secret_key()
    key = config.get_secret_key()
    assert key != config.FALLBACK_SECRET_KEY
    assert len(key) >= 32


def test_secret_key_is_stable_within_process(monkeypatch):
    """同一进程内多次取值必须一致（否则会话每次请求都失效）。"""
    monkeypatch.delenv('FARM_SECRET_KEY', raising=False)
    config.reset_runtime_secret_key()
    assert config.get_secret_key() == config.get_secret_key()


def test_secret_key_differs_across_restarts(monkeypatch):
    """模拟进程重启（重置运行时密钥）后密钥必须不同。"""
    monkeypatch.delenv('FARM_SECRET_KEY', raising=False)
    config.reset_runtime_secret_key()
    first = config.get_secret_key()
    config.reset_runtime_secret_key()
    second = config.get_secret_key()
    assert first != second


def test_secret_key_prefers_env(monkeypatch):
    """显式配置时优先用环境变量，且不触发随机密钥。"""
    monkeypatch.setenv('FARM_SECRET_KEY', 'explicit_secret_from_env_0123456789')
    assert config.get_secret_key() == 'explicit_secret_from_env_0123456789'
    assert config.secret_key_is_configured() is True


def test_secret_key_is_random_and_urlsafe(monkeypatch):
    """随机密钥应足够长且不含空白（token_urlsafe 输出）。"""
    monkeypatch.delenv('FARM_SECRET_KEY', raising=False)
    config.reset_runtime_secret_key()
    key = config.get_secret_key()
    assert ' ' not in key
    assert key == key.strip()
    assert len(key) >= 64 - 4  # token_urlsafe(48) 约 64 字符


def test_forged_token_with_fallback_key_rejected(flask_app, monkeypatch):
    """用旧硬编码常量自签的 token 必须 401（P0-1 核心回归）。"""
    monkeypatch.setenv('FARM_SECRET_KEY', 'real_secret_key_0123456789abcdefghij')
    forged = pyjwt.encode(
        {'user_id': 1, 'exp': time.time() + 3600},
        config.FALLBACK_SECRET_KEY,
        algorithm='HS256',
    )
    client = flask_app.test_client()
    resp = client.post('/api/app_send_command',
                       json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer %s' % forged})
    assert resp.status_code == 401
    assert resp.get_json() == {'status': 'error', 'message': 'Token无效或过期'}


@pytest.mark.parametrize('uid', [1, 2, 22])
def test_forged_token_cannot_impersonate_any_user(flask_app, monkeypatch, uid):
    """用兜底常量伪造任意 user_id 都不能通过鉴权。"""
    monkeypatch.setenv('FARM_SECRET_KEY', 'another_real_secret_0123456789abc')
    forged = pyjwt.encode({'user_id': uid, 'exp': time.time() + 3600},
                          config.FALLBACK_SECRET_KEY, algorithm='HS256')
    client = flask_app.test_client()
    resp = client.post('/api/app_send_command',
                       json={'device': 'air_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer %s' % forged})
    assert resp.status_code == 401


def test_real_token_still_works(flask_app, monkeypatch):
    """用真实密钥签发的 token 仍然可用（修复不能误伤正常流程）。"""
    monkeypatch.setenv('FARM_SECRET_KEY', 'real_secret_key_0123456789abcdefghij')
    make_user('jwtuser1', 'pw123456')
    client = flask_app.test_client()
    resp = client.post('/api/app_login', json={'username': 'jwtuser1', 'password': 'pw123456'})
    token = resp.get_json()['token']
    resp = client.post('/api/app_send_command',
                       json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer %s' % token})
    # 设备未连接 -> 200 + 设备未连接（说明已通过鉴权）
    assert resp.status_code == 200
    assert resp.get_json()['message'] == '设备未连接'


def test_issue_token_uses_app_secret(flask_app):
    """issue_token 签出的 token 能被同一 app 的 require_token 接受。"""
    make_user('jwtuser2', 'pw123456')
    client = flask_app.test_client()
    resp = client.post('/api/app_login', json={'username': 'jwtuser2', 'password': 'pw123456'})
    token = resp.get_json()['token']
    claims = pyjwt.decode(token, flask_app.secret_key, algorithms=['HS256'])
    assert claims['user_id'] > 0


# ============================================================
# P0-2 / P1-5：JSON 字段类型混淆不得 500
# ============================================================

BAD_TYPES = [12345, 12.5, True, False, ['a'], {'k': 'v'}, []]


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_register_rejects_non_string_username(client, bad):
    """username 为非字符串 -> 400，不 500。"""
    resp = client.post('/api/register', json={'username': bad, 'password': 'pw123456'})
    assert resp.status_code == 400
    assert resp.get_json()['status'] == 'error'


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_register_rejects_non_string_password(client, bad):
    """password 为非字符串 -> 400，不 500。"""
    resp = client.post('/api/register', json={'username': 'okuser01', 'password': bad})
    assert resp.status_code == 400
    assert resp.get_json()['status'] == 'error'


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_login_rejects_non_string_username(client, bad):
    """登录 username 类型错误 -> 400。"""
    resp = client.post('/api/login', json={'username': bad, 'password': 'pw123456'})
    assert resp.status_code == 400


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_login_rejects_non_string_password(client, registered, bad):
    """登录 password 类型错误 -> 400。"""
    username, _ = registered
    resp = client.post('/api/login', json={'username': username, 'password': bad})
    assert resp.status_code == 400


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_app_login_rejects_non_string(client, registered, bad):
    """app_login 类型错误 -> 400。"""
    resp = client.post('/api/app_login', json={'username': bad, 'password': 'pw123456'})
    assert resp.status_code == 400


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_change_password_rejects_non_string(client, registered, bad):
    """改密字段类型错误 -> 400。"""
    resp = client.post('/api/change_password',
                       json={'old_password': bad, 'new_password': 'newpw1234'})
    assert resp.status_code == 400
    resp = client.post('/api/change_password',
                       json={'old_password': 'secret123', 'new_password': bad})
    assert resp.status_code == 400


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_notify_alert_rejects_non_string(client, registered, bad):
    """P1-5：告警 msg / level 类型错误 -> 400，不 500。"""
    resp = client.post('/api/notify_alert', json={'msg': bad, 'level': 'warn'})
    assert resp.status_code == 400
    resp = client.post('/api/notify_alert', json={'msg': 'hello', 'level': bad})
    assert resp.status_code == 400


def test_notify_alert_accepts_valid_strings(client, registered):
    """合法字符串仍正常走通（无 webhook 时 skipped）。"""
    resp = client.post('/api/notify_alert', json={'msg': '水位偏低', 'level': 'warn'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] in ('success', 'skipped')
    assert 'sent' in body


def test_notify_alert_missing_msg_still_400(client, registered):
    """缺少 msg 仍返回固定文案（行为未变）。"""
    resp = client.post('/api/notify_alert', json={})
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'error', 'message': '缺少告警内容'}


def test_notify_alert_truncates_long_fields(client, registered, monkeypatch):
    """msg 截断 500、level 截断 20（长度语义未变）。"""
    captured = {}

    def fake_notify(uid, title, content):
        captured['title'] = title
        captured['content'] = content
        return True

    monkeypatch.setattr('qinghe.alerts.notify_webhook', fake_notify)
    resp = client.post('/api/notify_alert', json={'msg': 'x' * 900, 'level': 'y' * 60})
    assert resp.status_code == 200
    assert len(captured['content']) == 500
    assert len(captured['title']) == len('[青禾智灌] ') + 20 + len(' 告警')


def test_json_array_body_does_not_500(client):
    """整个请求体是数组时不应 500。"""
    for path in ('/api/register', '/api/login', '/api/notify_alert'):
        resp = client.post(path, json=[1, 2, 3])
        assert resp.status_code < 500, path


# ============================================================
# validators 单元测试
# ============================================================

def test_as_str_returns_default_for_missing_and_none():
    """缺失 / None 返回默认值。"""
    assert validators.as_str({}, 'k', 'd') == 'd'
    assert validators.as_str({'k': None}, 'k', 'd') == 'd'


@pytest.mark.parametrize('bad', BAD_TYPES)
def test_as_str_rejects_non_string(bad):
    """非字符串抛 ValidationError。"""
    with pytest.raises(validators.ValidationError):
        validators.as_str({'k': bad}, 'k')


def test_as_stripped_trims_whitespace():
    """as_stripped 去除首尾空白。"""
    assert validators.as_stripped({'k': '  a b  '}, 'k') == 'a b'


def test_as_str_accepts_empty_string():
    """空字符串是合法 str，不是类型错误。"""
    assert validators.as_str({'k': ''}, 'k') == ''


def test_as_int_accepts_int_and_numeric_string():
    """as_int 接受 int 与纯数字字符串。"""
    assert validators.as_int({'k': 5}, 'k') == 5
    assert validators.as_int({'k': '7'}, 'k') == 7
    assert validators.as_int({'k': ' 8 '}, 'k') == 8


def test_as_int_rejects_bool_and_bad_types():
    """as_int 拒绝 bool / 列表 / 字典 / 非数字串。"""
    for bad in (True, False, ['1'], {'a': 1}, 'abc', 1.5):
        with pytest.raises(validators.ValidationError):
            validators.as_int({'k': bad}, 'k')


def test_as_int_returns_default_for_none_and_missing():
    """None / 缺失 / 空串返回默认值。"""
    assert validators.as_int({}, 'k', 9) == 9
    assert validators.as_int({'k': None}, 'k', 9) == 9
    assert validators.as_int({'k': ''}, 'k', 9) == 9


def test_as_int_accepts_integral_float():
    """整数值的 float 可接受，非整数 float 拒绝。"""
    assert validators.as_int({'k': 3.0}, 'k') == 3
    with pytest.raises(validators.ValidationError):
        validators.as_int({'k': 3.5}, 'k')


def test_as_bool_accepts_only_bool():
    """as_bool 只接受真正的 bool。"""
    assert validators.as_bool({'k': True}, 'k') is True
    assert validators.as_bool({'k': False}, 'k') is False
    assert validators.as_bool({}, 'k', True) is True
    with pytest.raises(validators.ValidationError):
        validators.as_bool({'k': 'true'}, 'k')


def test_truncated_caps_length():
    """truncated 按 max_len 截断。"""
    assert validators.truncated({'k': 'abcdef'}, 'k', max_len=3) == 'abc'
    assert validators.truncated({'k': 'ab'}, 'k', max_len=5) == 'ab'


def test_validation_error_carries_status_and_message():
    """ValidationError 带 status 与 message，路由层可直接返回。"""
    exc = validators.ValidationError('boom')
    assert exc.status == 400
    assert exc.message == 'boom'


def test_validators_do_not_import_qinghe_submodules():
    """validators 不得依赖其他子模块（防循环依赖）。"""
    import pathlib
    source = pathlib.Path(validators.__file__).read_text(encoding='utf-8')
    assert 'from qinghe' not in source
    assert 'import qinghe' not in source


# ============================================================
# P1-3：代理信任开关
# ============================================================

def test_trust_proxy_defaults_off(monkeypatch):
    """默认不信任代理。"""
    monkeypatch.delenv('FARM_TRUST_PROXY', raising=False)
    assert config.trust_proxy() is False


def test_trust_proxy_enabled_by_env(monkeypatch):
    """FARM_TRUST_PROXY=1 时开启。"""
    monkeypatch.setenv('FARM_TRUST_PROXY', '1')
    assert config.trust_proxy() is True


@pytest.mark.parametrize('value', ['0', '', 'yes', 'true', '2'])
def test_trust_proxy_only_accepts_exact_one(monkeypatch, value):
    """只有精确的 '1' 才算开启，避免误配。"""
    monkeypatch.setenv('FARM_TRUST_PROXY', value)
    assert config.trust_proxy() is False


# ============================================================
# P1-4：iot_port 脏数据兜底
# ============================================================

@pytest.mark.parametrize('raw,expected', [
    ('abc', config.IOT_PORT_DEFAULT),
    (None, config.IOT_PORT_DEFAULT),
    ('', config.IOT_PORT_DEFAULT),
    (0, config.IOT_PORT_DEFAULT),
    (-1, config.IOT_PORT_DEFAULT),
    (65536, config.IOT_PORT_DEFAULT),
    (99999, config.IOT_PORT_DEFAULT),
    ('   ', config.IOT_PORT_DEFAULT),
    ([], config.IOT_PORT_DEFAULT),
    ({}, config.IOT_PORT_DEFAULT),
    (1883, 1883),
    ('8883', 8883),
    (1, 1),
    (65535, 65535),
])
def test_safe_iot_port(raw, expected):
    """connect_huawei_iot 的端口归一：非法回退默认，不抛 ValueError。"""
    assert iot._safe_iot_port(raw) == expected


def test_connect_huawei_iot_survives_bad_port(flask_app):
    """脏 iot_port 不能让 connect_huawei_iot 抛异常（应返回 False 或成功降级）。"""
    from helpers import set_config
    uid = make_user('portuser1', 'pw123456')
    set_config(uid, iot_port='abc', iot_host='', iot_client_id='')
    # host 为空 -> 直接 False；关键是不抛 ValueError
    assert iot.connect_huawei_iot(uid) is False


def test_connect_huawei_iot_returns_false_without_config(flask_app):
    """配置不存在时返回 False 而不是抛异常。"""
    assert iot.connect_huawei_iot(999999) is False
