"""配置读写与阈值接口测试：/api/get_config、/api/save_config、/api/thresh_settings。

重点验证：掩码保留逻辑（掩码/None 保留旧值）、iot_port 校验、阈值 clamp。
"""

import pytest

from helpers import fetch_one, set_config, user_id_of

MASK = '••••••••'


@pytest.fixture()
def uid(client, registered):
    return user_id_of('farmer01')


# ============================================================
# /api/get_config
# ============================================================

def test_get_config_requires_login(client):
    resp = client.get('/api/get_config')
    assert resp.status_code == 401
    assert resp.get_json() == {'error': '未授权'}


def test_get_config_returns_all_columns(client, uid):
    body = client.get('/api/get_config').get_json()
    for col in ('user_id', 'farm_name', 'farm_lng', 'farm_lat', 'iot_host', 'iot_port',
                'iot_client_id', 'iot_user', 'iot_pass', 'iot_device_id',
                'iot_target_device_id', 'iot_m2m_topic', 'iot_cmd_topic',
                'weather_domain', 'weather_key', 'ai_domain', 'ai_key', 'webhook_url'):
        assert col in body


def test_get_config_masks_sensitive_fields(client, uid):
    set_config(uid, iot_pass='realpass', weather_key='realkey', ai_key='realaikey')
    body = client.get('/api/get_config').get_json()
    assert body['iot_pass'] == MASK
    assert body['weather_key'] == MASK
    assert body['ai_key'] == MASK


def test_get_config_empty_secret_stays_empty(client, uid):
    set_config(uid, iot_pass='', weather_key='', ai_key='')
    body = client.get('/api/get_config').get_json()
    assert body['iot_pass'] == ''
    assert body['weather_key'] == ''
    assert body['ai_key'] == ''


def test_get_config_no_plaintext_leak(client, uid):
    set_config(uid, iot_pass='supersecret', weather_key='k-123', ai_key='a-456')
    raw = client.get('/api/get_config').get_data(as_text=True)
    assert 'supersecret' not in raw
    assert 'k-123' not in raw
    assert 'a-456' not in raw


# ============================================================
# /api/save_config：掩码保留
# ============================================================

def test_save_config_requires_login(client):
    resp = client.post('/api/save_config', json={'farm_name': 'x'})
    assert resp.status_code == 401
    assert resp.get_json() == {'error': '未授权'}


def test_save_config_basic_fields(client, uid):
    resp = client.post('/api/save_config', json={
        'farm_name': '青禾农场', 'farm_lng': '118.78', 'farm_lat': '31.90',
        'iot_host': 'iot.example.com', 'iot_client_id': 'cid', 'iot_user': 'u',
        'iot_device_id': 'dev-1',
    })
    assert resp.get_json() == {'status': 'success', 'message': '配置已更新'}
    row = fetch_one('SELECT farm_name, farm_lng, iot_host FROM configs WHERE user_id=?', (uid,))
    assert row['farm_name'] == '青禾农场'
    assert row['farm_lng'] == '118.78'
    assert row['iot_host'] == 'iot.example.com'


def test_save_config_mask_keeps_old_value(client, uid):
    """前端回传掩码占位时应保留数据库原值。"""
    set_config(uid, iot_pass='old-pass', weather_key='old-wk', ai_key='old-ak')
    client.post('/api/save_config', json={
        'iot_pass': MASK, 'weather_key': MASK, 'ai_key': MASK,
        'farm_name': '农场A',
    })
    row = fetch_one('SELECT iot_pass, weather_key, ai_key, farm_name FROM configs WHERE user_id=?',
                    (uid,))
    assert row['iot_pass'] == 'old-pass'
    assert row['weather_key'] == 'old-wk'
    assert row['ai_key'] == 'old-ak'
    assert row['farm_name'] == '农场A'


def test_save_config_none_keeps_old_value(client, uid):
    """字段缺失（None）时同样保留旧值。"""
    set_config(uid, iot_pass='old-pass', weather_key='old-wk')
    client.post('/api/save_config', json={'farm_name': '农场B'})
    row = fetch_one('SELECT iot_pass, weather_key FROM configs WHERE user_id=?', (uid,))
    assert row['iot_pass'] == 'old-pass'
    assert row['weather_key'] == 'old-wk'


def test_save_config_explicit_new_secret_overwrites(client, uid):
    set_config(uid, iot_pass='old-pass')
    client.post('/api/save_config', json={'iot_pass': 'brand-new-pass'})
    row = fetch_one('SELECT iot_pass FROM configs WHERE user_id=?', (uid,))
    assert row['iot_pass'] == 'brand-new-pass'


def test_save_config_empty_string_clears_secret(client, uid):
    """显式传空串视为清空（与掩码不同）。"""
    set_config(uid, iot_pass='old-pass')
    client.post('/api/save_config', json={'iot_pass': ''})
    row = fetch_one('SELECT iot_pass FROM configs WHERE user_id=?', (uid,))
    assert row['iot_pass'] == ''


# ============================================================
# /api/save_config：iot_port 校验
# ============================================================

def test_save_config_valid_iot_port(client, uid):
    client.post('/api/save_config', json={'iot_port': '8883'})
    assert fetch_one('SELECT iot_port FROM configs WHERE user_id=?', (uid,))['iot_port'] == 8883


@pytest.mark.parametrize('bad_port', ['abc', '0', '-1', '65536', '99999', '', '12.5.6'])
def test_save_config_invalid_iot_port_keeps_old(client, uid, bad_port):
    set_config(uid, iot_port=1883)
    resp = client.post('/api/save_config', json={'iot_port': bad_port})
    assert resp.get_json()['status'] == 'success'
    assert fetch_one('SELECT iot_port FROM configs WHERE user_id=?', (uid,))['iot_port'] == 1883


def test_save_config_null_iot_port_keeps_old(client, uid):
    set_config(uid, iot_port=1884)
    client.post('/api/save_config', json={'iot_port': None})
    assert fetch_one('SELECT iot_port FROM configs WHERE user_id=?', (uid,))['iot_port'] == 1884


def test_save_config_float_iot_port_is_truncated(client, uid):
    client.post('/api/save_config', json={'iot_port': 1883.9})
    assert fetch_one('SELECT iot_port FROM configs WHERE user_id=?', (uid,))['iot_port'] == 1883


def test_save_config_invalid_port_does_not_raise(client, uid):
    """非法端口不得导致 500（旧版会在 connect_huawei_iot 里 int() 抛异常）。"""
    set_config(uid, iot_port=1883)
    resp = client.post('/api/save_config', json={'iot_port': 'not-a-number'})
    assert resp.status_code == 200


def test_save_config_does_not_reconnect_without_full_credentials(client, uid):
    """配置不完整时 connect_huawei_iot 应安全返回 False，不建连接。"""
    from qinghe import iot
    resp = client.post('/api/save_config', json={'iot_host': 'h', 'iot_client_id': 'c'})
    assert resp.get_json()['status'] == 'success'
    assert iot.mqtt_clients == {}


def test_save_config_does_not_block_on_slow_broker(client, uid, monkeypatch):
    """华为云不可达（connect 阻塞）时，save_config 必须立刻返回。"""
    import threading
    import time

    from qinghe import iot

    started = threading.Event()
    release = threading.Event()

    def slow_connect(user_id):
        started.set()
        release.wait(3)
        return True

    monkeypatch.setattr(iot, 'connect_huawei_iot', slow_connect)
    begin = time.time()
    resp = client.post('/api/save_config', json={'farm_name': '慢连接农场'})
    elapsed = time.time() - begin
    assert resp.get_json()['status'] == 'success'
    assert elapsed < 1.0, '配置保存被 MQTT 连接阻塞'
    # 后台线程确实被启动了（连接在另一个线程里进行）
    assert started.wait(2)
    release.set()


# ============================================================
# /api/thresh_settings
# ============================================================

def test_get_thresh_requires_login(client):
    assert client.get('/api/thresh_settings').status_code == 401


def test_get_thresh_defaults(client, uid):
    body = client.get('/api/thresh_settings').get_json()
    assert body == {'humi_down': 40, 'humi_up': 80,
                    'waterlevel_down': 30, 'waterlevel_up': 150, 'manual_mode': 0}


def test_save_thresh_requires_login(client):
    assert client.post('/api/thresh_settings', json={}).status_code == 401


def test_save_thresh_roundtrip(client, uid):
    resp = client.post('/api/thresh_settings', json={
        'humi_down': 35, 'humi_up': 75, 'waterlevel_down': 25,
        'waterlevel_up': 160, 'manual_mode': 1,
    })
    assert resp.get_json() == {'status': 'success', 'message': '设定已保存'}
    body = client.get('/api/thresh_settings').get_json()
    assert (body['humi_down'], body['humi_up']) == (35, 75)
    assert (body['waterlevel_down'], body['waterlevel_up']) == (25, 160)
    assert body['manual_mode'] == 1


@pytest.mark.parametrize('bad', ['abc', None, '', [], {}])
def test_save_thresh_non_numeric_falls_back_to_default(client, uid, bad):
    """非数字入参回退默认值，绝不能 500。"""
    resp = client.post('/api/thresh_settings', json={
        'humi_down': bad, 'humi_up': bad, 'waterlevel_down': bad, 'waterlevel_up': bad,
    })
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'success'
    body = client.get('/api/thresh_settings').get_json()
    assert body['humi_down'] == 40 and body['humi_up'] == 80
    assert body['waterlevel_down'] == 30 and body['waterlevel_up'] == 150


@pytest.mark.parametrize('raw,expected', [(-10, 0), (150, 100), ('abc', 40)])
def test_save_thresh_humidity_clamped(client, uid, raw, expected):
    client.post('/api/thresh_settings', json={'humi_down': raw, 'humi_up': raw})
    body = client.get('/api/thresh_settings').get_json()
    assert body['humi_down'] == expected


@pytest.mark.parametrize('raw,expected', [(-5, 0), (999, 300), ('xyz', 30)])
def test_save_thresh_waterlevel_clamped(client, uid, raw, expected):
    client.post('/api/thresh_settings', json={'waterlevel_down': raw, 'waterlevel_up': raw})
    body = client.get('/api/thresh_settings').get_json()
    assert body['waterlevel_down'] == expected


def test_save_thresh_lower_not_above_upper(client, uid):
    client.post('/api/thresh_settings', json={'humi_down': 90, 'humi_up': 50,
                                              'waterlevel_down': 200, 'waterlevel_up': 100})
    body = client.get('/api/thresh_settings').get_json()
    assert body['humi_down'] <= body['humi_up']
    assert body['waterlevel_down'] <= body['waterlevel_up']


def test_save_thresh_manual_mode_flag(client, uid):
    client.post('/api/thresh_settings', json={'manual_mode': 1})
    assert client.get('/api/thresh_settings').get_json()['manual_mode'] == 1
    client.post('/api/thresh_settings', json={'manual_mode': 0})
    assert client.get('/api/thresh_settings').get_json()['manual_mode'] == 0


def test_save_thresh_is_upsert_not_duplicate(client, uid):
    for value in (10, 20, 30):
        client.post('/api/thresh_settings', json={'humi_down': value, 'humi_up': 80})
    rows = fetch_one('SELECT COUNT(*) AS n FROM thresh_settings WHERE user_id=?', (uid,))
    assert rows['n'] == 1


def test_save_thresh_string_numbers_accepted(client, uid):
    client.post('/api/thresh_settings', json={'humi_down': '33', 'humi_up': '77'})
    body = client.get('/api/thresh_settings').get_json()
    assert body['humi_down'] == 33 and body['humi_up'] == 77


# ============================================================
# 安全响应头
# ============================================================

def test_security_headers_present(client):
    resp = client.get('/')
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert resp.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert resp.headers['Referrer-Policy'] == 'no-referrer'


def test_csp_keeps_scripts_same_origin(client):
    """第三方库已本地化到 static/vendor，CSP 不应再放行外网 CDN 脚本/样式。"""
    csp = client.get('/').headers['Content-Security-Policy']
    assert 'cdnjs.cloudflare.com' not in csp
    assert 'cdn.jsdelivr.net' not in csp
    assert "script-src 'self' 'unsafe-inline';" in csp
    assert "style-src 'self' 'unsafe-inline';" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
