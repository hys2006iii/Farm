"""监控类接口测试：/api/alerts、/api/alerts/ack、/api/logs、/api/device_status。

覆盖点：
- 未登录一律 401 JSON；
- 入参校验（limit / since_ts / id / offline_seconds）非法返回 400；
- 越权确认他人告警返回 404；
- 告警与日志按时间倒序返回且带 rid 序号；
- 设备状态在心跳前为离线、心跳后在线、超阈值静默判离线。
"""

import pytest

from helpers import make_user, user_id_of
from qinghe import alert_center, heartbeat, logbook


@pytest.fixture()
def logged_client(client, registered):
    """已通过会话登录的测试客户端（registered 已完成注册 + 登录）。"""
    return client


@pytest.fixture()
def uid(logged_client):
    """当前登录用户的 uid（registered 注册的 farmer01）。"""
    value = user_id_of('farmer01')
    assert value
    return value


@pytest.fixture()
def uid2(flask_app):
    """第二个用户，用于验证越权。"""
    created = make_user('monitor02', 'secret123')
    assert created
    return created


@pytest.fixture(autouse=True)
def _clean_module_state():
    """清掉模块级冷却 / 上下文缓存，避免用例之间互相干扰。"""
    alert_center._reset_dedupe()
    logbook.flush_logs()
    yield
    alert_center._reset_dedupe()
    logbook.flush_logs()


# ============================================================
# /api/alerts
# ============================================================


def test_alerts_requires_login(client):
    """未登录访问告警列表返回 401 JSON。"""
    resp = client.get('/api/alerts')
    assert resp.status_code == 401
    assert resp.get_json()['error'] == '未登录'


def test_alerts_returns_pushed_alert(logged_client, uid):
    """push_alert 落库的告警能被列表接口读出，字段齐全。"""
    pushed = alert_center.push_alert(uid, 'danger', 'soil_low', '土壤湿度过低，请检查滴灌')
    assert pushed['id'] > 0

    resp = logged_client.get('/api/alerts')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success'
    assert body['count'] == len(body['alerts'])
    assert body['count'] >= 1
    item = body['alerts'][0]
    assert item['id'] == pushed['id']
    assert item['rid'] == 1
    assert item['level'] == 'danger'
    assert item['code'] == 'soil_low'
    assert item['content'] == '土壤湿度过低，请检查滴灌'
    assert item['acked'] == 0


def test_alerts_sorted_desc_and_paginated(logged_client, uid):
    """多条告警按时间倒序返回，limit 生效。"""
    for index in range(3):
        pushed = alert_center.push_alert(uid, 'warning', 'rori_medium', '第%d条缺氧告警' % index)
        assert pushed['id'] > 0
        alert_center._reset_dedupe()

    resp = logged_client.get('/api/alerts?limit=2')
    body = resp.get_json()
    assert body['count'] == 2
    stars = [item['ts'] for item in body['alerts']]
    assert stars == sorted(stars, reverse=True)


@pytest.mark.parametrize('query', ['limit=0', 'limit=501', 'limit=abc', 'since_ts=-1', 'since_ts=x'])
def test_alerts_rejects_bad_query(logged_client, query):
    """limit / since_ts 越界或非数字返回 400。"""
    resp = logged_client.get('/api/alerts?' + query)
    assert resp.status_code == 400
    assert resp.get_json()['status'] == 'error'


def test_alerts_isolated_between_users(logged_client, uid, uid2):
    """只能看到自己的告警。"""
    alert_center.push_alert(uid, 'info', 'device_offline', '我的设备离线')
    resp = logged_client.get('/api/alerts')
    assert resp.get_json()['count'] == 1

    alert_center.push_alert(uid2, 'info', 'device_offline', '别人的设备离线')
    resp = logged_client.get('/api/alerts')
    assert resp.get_json()['count'] == 1


# ============================================================
# /api/alerts/ack
# ============================================================


def test_ack_requires_login_and_valid_id(client):
    """未登录 401。"""
    assert client.post('/api/alerts/ack', json={'id': 1}).status_code == 401


def test_ack_marks_alert(logged_client, uid):
    """确认自己的告警后 acked 变为 1。"""
    pushed = alert_center.push_alert(uid, 'warning', 'water_low', '渠道水位偏低')
    resp = logged_client.post('/api/alerts/ack', json={'id': pushed['id']})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success' and body['acked'] is True

    listing = logged_client.get('/api/alerts').get_json()
    assert listing['alerts'][0]['acked'] == 1


@pytest.mark.parametrize('payload', [{}, {'id': 0}, {'id': 'x'}, {'id': None}])
def test_ack_rejects_bad_id(logged_client, payload):
    """缺少或非法 id 返回 400。"""
    resp = logged_client.post('/api/alerts/ack', json=payload)
    assert resp.status_code == 400


def test_ack_other_user_alert_returns_404(logged_client, uid2):
    """确认不属于自己的告警返回 404，且不泄露存在性以外的信息。"""
    pushed = alert_center.push_alert(uid2, 'warning', 'water_high', '渠道水位偏高')
    resp = logged_client.post('/api/alerts/ack', json={'id': pushed['id']})
    assert resp.status_code == 404


def test_ack_missing_alert_returns_404(logged_client, uid):
    """确认不存在的告警返回 404。"""
    resp = logged_client.post('/api/alerts/ack', json={'id': 999999})
    assert resp.status_code == 404


# ============================================================
# /api/logs
# ============================================================


def test_logs_requires_login(client):
    """未登录访问日志列表返回 401。"""
    assert client.get('/api/logs').status_code == 401


def test_logs_returns_written_entries(logged_client, uid):
    """add_log 写入的日志经刷盘后可被查询接口读出。"""
    logbook.add_log(uid, '自动调控开启水泵', level='info', source='auto')
    logbook.flush_logs()

    resp = logged_client.get('/api/logs')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success'
    assert body['count'] >= 1
    item = body['logs'][0]
    assert item['message'] == '自动调控开启水泵'
    assert item['source'] == 'auto'
    assert item['level'] == 'info'
    assert item['rid'] == 1


@pytest.mark.parametrize('query', ['limit=0', 'limit=1001', 'since_ts=-5'])
def test_logs_rejects_bad_query(logged_client, query):
    """limit / since_ts 非法返回 400。"""
    assert logged_client.get('/api/logs?' + query).status_code == 400


# ============================================================
# /api/device_status
# ============================================================


def test_device_status_requires_login(client):
    """未登录返回 401。"""
    assert client.get('/api/device_status').status_code == 401


def test_device_status_offline_before_any_heartbeat(logged_client):
    """从未上报过的用户被判为离线。"""
    body = logged_client.get('/api/device_status').get_json()
    assert body['status'] == 'success'
    assert body['online'] is False
    assert body['last_seen_ts'] == 0


def test_device_status_online_after_heartbeat(logged_client, uid):
    """收到心跳后判为在线。"""
    heartbeat.mark_seen(uid)
    body = logged_client.get('/api/device_status').get_json()
    assert body['online'] is True
    assert body['last_seen_ts'] > 0


def test_device_status_custom_threshold_flips_offline(logged_client, uid):
    """自定义 offline_seconds 用极小值可复现离线判定。"""
    heartbeat.mark_seen(uid)
    body = logged_client.get('/api/device_status?offline_seconds=1').get_json()
    # 心跳刚写入，静默秒数为 0，仍应判在线
    assert body['online'] is True

    import time

    time.sleep(1.1)
    body = logged_client.get('/api/device_status?offline_seconds=1').get_json()
    assert body['online'] is False


@pytest.mark.parametrize('query', ['offline_seconds=0', 'offline_seconds=abc', 'offline_seconds=99999'])
def test_device_status_rejects_bad_threshold(logged_client, query):
    """offline_seconds 越界或非数字返回 400。"""
    assert logged_client.get('/api/device_status?' + query).status_code == 400
