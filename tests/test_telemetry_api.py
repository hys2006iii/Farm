"""新增接口 /api/telemetry 的测试：刷新页面后看板恢复读数的服务端快照。

覆盖点：
- 未登录返回 401 JSON；
- 没有遥测时 `has_telemetry` 为 False，且不返回 ADC 字段（前端据此保持占位）；
- 灌入一帧遥测后四路读数、RORI、泵状态都能取到，ADC 反算与原始值一致；
- 不同用户之间互相隔离，不会读到别人的地块数据。
"""

import pytest

from helpers import make_user, user_id_of
from qinghe import planner


@pytest.fixture(autouse=True)
def _reset_planner_cache(flask_app):
    """planner 的遥测缓存是模块级字典，用例之间必须清掉。"""
    from qinghe import db

    with db.get_db() as conn:
        rows = conn.execute('SELECT id FROM users').fetchall()
    for row in rows:
        planner.reset_telemetry(int(row[0]))
    yield


@pytest.fixture()
def logged_client(client, registered):
    """已登录的测试客户端。"""
    return client


@pytest.fixture()
def uid(logged_client):
    """当前登录用户 id。"""
    value = user_id_of('farmer01')
    assert value
    return value


def test_telemetry_requires_login(client):
    """未登录不能读快照。"""
    assert client.get('/api/telemetry').status_code == 401


def test_telemetry_empty_before_any_report(logged_client):
    """还没上报过时返回 has_telemetry=False，不伪造 0 读数。"""
    body = logged_client.get('/api/telemetry').get_json()
    assert body['status'] == 'success'
    assert body['has_telemetry'] is False
    assert 'water_adc' not in body
    assert 'soil_adc' not in body


def test_telemetry_after_report_roundtrip(logged_client, uid):
    """上报水 1500 / 土 2200 / DO 6.0 / Eh 120 后能读回同样的物理量。"""
    planner.update_telemetry(
        uid, waterlevel=1500, humidity=2200, do=6.0, eh=120,
        air_pump='on', water_pump='off',
    )

    body = logged_client.get('/api/telemetry').get_json()
    assert body['has_telemetry'] is True
    assert body['water_adc'] == 1500
    assert body['soil_adc'] == 2200
    assert body['do_mgl'] == pytest.approx(6.0)
    assert body['eh_mv'] == pytest.approx(120.0)
    assert body['water_mm'] == pytest.approx(1500 / 4095 * 300, rel=1e-3)
    assert body['soil_pct'] == pytest.approx((4095 - 2200) / 4095 * 100, rel=1e-3)
    assert body['rori'] is not None
    assert body['rori_level']['code'] in (0, 1, 2)
    assert body['air_pump'] == 'on'
    assert body['water_pump'] == 'off'


def test_telemetry_isolated_between_users(logged_client, flask_app):
    """另一个用户的快照读不到当前用户的数据。"""
    other = make_user('telemetry02', 'secret123')
    planner.update_telemetry(
        user_id_of('farmer01'), waterlevel=1500, humidity=2200, do=6.0, eh=120,
    )
    planner.update_telemetry(other, waterlevel=800, humidity=1000)

    other_client = flask_app.test_client()
    resp = other_client.post('/api/login', json={'username': 'telemetry02', 'password': 'secret123'})
    assert resp.status_code == 200
    body = other_client.get('/api/telemetry').get_json()
    assert body['water_adc'] == 800
    assert body['soil_adc'] == 1000

    mine = logged_client.get('/api/telemetry').get_json()
    assert mine['water_adc'] == 1500


def test_telemetry_does_not_leak_secrets(logged_client, uid):
    """快照只含遥测字段，不应带出账户或密钥。"""
    planner.update_telemetry(uid, waterlevel=1200, humidity=1800)
    body = logged_client.get('/api/telemetry').get_json()
    for key in ('user_id', 'password', 'iot_pass', 'ai_key', 'weather_key'):
        assert key not in body
