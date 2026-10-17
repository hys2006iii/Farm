"""告警模块测试：webhook 推送、去重冷却、判定表（全部离线）。"""

import threading

import pytest
import requests

from helpers import set_config, user_id_of
from qinghe import alerts, config


class _Resp:
    """假 HTTP 响应。"""

    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture()
def uid(flask_app):
    """已注册用户 uid（配置行随注册自动创建）。"""
    from helpers import make_user
    return make_user('alertuser', 'pw123456')


@pytest.fixture()
def uid_with_webhook(uid):
    set_config(uid, webhook_url='https://example.com/hook')
    return uid


# ============================================================
# notify_webhook
# ============================================================

def test_notify_webhook_no_config_returns_false(flask_app):
    assert alerts.notify_webhook(999999, '标题', '内容') is False


def test_notify_webhook_without_url_returns_false(uid):
    assert alerts.notify_webhook(uid, '标题', '内容') is False


def test_notify_webhook_blank_url_returns_false(uid):
    set_config(uid, webhook_url='   ')
    assert alerts.notify_webhook(uid, '标题', '内容') is False


@pytest.mark.parametrize('bad_url', ['ftp://x/hook', 'example.com/hook', 'javascript:alert(1)'])
def test_notify_webhook_non_http_scheme_returns_false(uid, bad_url, monkeypatch):
    set_config(uid, webhook_url=bad_url)
    monkeypatch.setattr(requests, 'post',
                        lambda *a, **k: pytest.fail('非 http(s) 不应发起请求'))
    assert alerts.notify_webhook(uid, '标题', '内容') is False


def test_notify_webhook_payload_and_keyword(uid_with_webhook, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(url=url, payload=json, timeout=timeout)
        return _Resp(200)

    monkeypatch.setattr(requests, 'post', fake_post)
    assert alerts.notify_webhook(uid_with_webhook, '[青禾智灌] warn 告警', '土壤湿度过低') is True
    assert captured['url'] == 'https://example.com/hook'
    assert captured['payload'] == {
        'msgtype': 'text',
        'text': {'content': '【青禾智灌系统】[青禾智灌] warn 告警\n土壤湿度过低'},
    }
    assert captured['timeout'] == config.TIMEOUT_WEBHOOK


def test_notify_webhook_keyword_prefix_is_fixed():
    assert alerts.ALERT_KEYWORD == '【青禾智灌系统】'


@pytest.mark.parametrize('code,expected', [(200, True), (201, True), (204, False), (400, False)])
def test_notify_webhook_status_handling(uid_with_webhook, monkeypatch, code, expected):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(code))
    assert alerts.notify_webhook(uid_with_webhook, 't', 'c') is expected


def test_notify_webhook_exception_returns_false(uid_with_webhook, monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout('timed out')

    monkeypatch.setattr(requests, 'post', boom)
    assert alerts.notify_webhook(uid_with_webhook, 't', 'c') is False


def test_notify_webhook_strips_whitespace_url(uid, monkeypatch):
    set_config(uid, webhook_url='  https://example.com/hook  ')
    captured = {}
    monkeypatch.setattr(requests, 'post',
                        lambda url, **k: captured.update(url=url) or _Resp(200))
    alerts.notify_webhook(uid, 't', 'c')
    assert captured['url'] == 'https://example.com/hook'


# ============================================================
# AlertDeduper
# ============================================================

def test_deduper_first_emit_allowed():
    assert alerts.AlertDeduper(cooldown=60).should_emit('k', now=1000.0) is True


def test_deduper_within_window_suppressed():
    d = alerts.AlertDeduper(cooldown=60)
    assert d.should_emit('k', now=1000.0) is True
    assert d.should_emit('k', now=1030.0) is False


def test_deduper_after_window_allowed():
    d = alerts.AlertDeduper(cooldown=60)
    d.should_emit('k', now=1000.0)
    assert d.should_emit('k', now=1060.0) is True


def test_deduper_exactly_at_boundary_allowed():
    """边界：now - last == cooldown 应放行（与前端 `< cooldown` 判定一致）。"""
    d = alerts.AlertDeduper(cooldown=60)
    d.should_emit('k', now=1000.0)
    assert d.should_emit('k', now=1060.0) is True


def test_deduper_distinct_keys_independent():
    d = alerts.AlertDeduper(cooldown=60)
    assert d.should_emit('a', now=1000.0) is True
    assert d.should_emit('b', now=1000.0) is True


def test_deduper_suppressed_call_does_not_refresh_timestamp():
    """被抑制的调用不应刷新时间戳，否则高频上报会让告警永久沉默。"""
    d = alerts.AlertDeduper(cooldown=60)
    d.should_emit('k', now=1000.0)
    d.should_emit('k', now=1050.0)      # 被抑制
    assert d.should_emit('k', now=1061.0) is True


def test_deduper_reset_clears_state():
    d = alerts.AlertDeduper(cooldown=60)
    d.should_emit('k', now=1000.0)
    d.reset()
    assert d.should_emit('k', now=1001.0) is True


def test_deduper_default_cooldown_matches_config():
    assert alerts.AlertDeduper().cooldown == config.ALERT_COOLDOWN_SECONDS


def test_deduper_concurrent_use_is_safe():
    """多线程并发调用不得抛异常，且每个 key 只放行一次。"""
    d = alerts.AlertDeduper(cooldown=60)
    results = []
    lock = threading.Lock()

    def worker():
        got = d.should_emit('shared', now=1000.0)
        with lock:
            results.append(got)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert results.count(False) == 15


# ============================================================
# evaluate_alerts（纯函数判定表）
# ============================================================

def _msgs(items):
    return [i['msg'] for i in items]


def test_evaluate_alerts_all_normal_returns_empty():
    assert alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0) == []


def test_evaluate_alerts_soil_too_low():
    items = alerts.evaluate_alerts(30.0, 50.0, 40.0, 80.0, 150.0)
    assert len(items) == 1
    assert items[0]['level'] == 'warn'
    assert '土壤湿度过低' in items[0]['msg']


def test_evaluate_alerts_soil_too_high():
    items = alerts.evaluate_alerts(90.0, 50.0, 40.0, 80.0, 150.0)
    assert len(items) == 1
    assert '土壤湿度过高' in items[0]['msg']


def test_evaluate_alerts_soil_low_and_high_are_mutually_exclusive():
    """土壤越界只产生一条（elif 分支）。"""
    assert len(alerts.evaluate_alerts(30.0, 0.0, 40.0, 80.0, 150.0)) == 1


def test_evaluate_alerts_water_too_high():
    items = alerts.evaluate_alerts(60.0, 200.0, 40.0, 80.0, 150.0)
    assert len(items) == 1
    assert '水位过高' in items[0]['msg']


def test_evaluate_alerts_low_water_produces_no_alert():
    """低水位不产出候选（旧版行为，保持不变）。"""
    assert alerts.evaluate_alerts(60.0, 0.0, 40.0, 80.0, 150.0) == []


def test_evaluate_alerts_rori_moderate():
    items = alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0, rori=40)
    assert len(items) == 1
    assert items[0]['level'] == 'warn'
    assert '中度缺氧' in items[0]['msg']


def test_evaluate_alerts_rori_heavy():
    items = alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0, rori=70)
    assert len(items) == 1
    assert items[0]['level'] == 'danger'
    assert '重度厌氧' in items[0]['msg']


def test_evaluate_alerts_rori_below_threshold_silent():
    assert alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0, rori=39.9) == []


def test_evaluate_alerts_rori_none_silent():
    assert alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0, rori=None) == []


def test_evaluate_alerts_rori_heavy_takes_precedence_over_moderate():
    items = alerts.evaluate_alerts(60.0, 50.0, 40.0, 80.0, 150.0, rori=95)
    assert len(items) == 1
    assert items[0]['level'] == 'danger'


def test_evaluate_alerts_combines_soil_water_rori():
    items = alerts.evaluate_alerts(20.0, 200.0, 40.0, 80.0, 150.0, rori=80)
    assert len(items) == 3
    assert [i['level'] for i in items] == ['warn', 'warn', 'danger']
    assert any('土壤湿度过低' in m for m in _msgs(items))
    assert any('水位过高' in m for m in _msgs(items))
    assert any('重度厌氧' in m for m in _msgs(items))


def test_evaluate_alerts_boundary_equal_lower_no_alert():
    assert alerts.evaluate_alerts(40.0, 50.0, 40.0, 80.0, 150.0) == []


def test_evaluate_alerts_boundary_equal_upper_no_alert():
    assert alerts.evaluate_alerts(80.0, 50.0, 40.0, 80.0, 150.0) == []


def test_evaluate_alerts_boundary_equal_water_upper_no_alert():
    assert alerts.evaluate_alerts(60.0, 150.0, 40.0, 80.0, 150.0) == []


def test_evaluate_alerts_messages_carry_numbers():
    items = alerts.evaluate_alerts(30.5, 50.0, 40.0, 80.0, 150.0)
    assert '30.5%' in items[0]['msg']
    assert '40.0%' in items[0]['msg']


def test_evaluate_alerts_returns_dicts_with_level_and_msg():
    items = alerts.evaluate_alerts(30.0, 200.0, 40.0, 80.0, 150.0)
    for item in items:
        assert set(item) == {'level', 'msg'}
        assert item['level'] in ('warn', 'danger')


# ============================================================
# 接口层：/api/notify_alert
# ============================================================

def test_api_notify_alert_requires_login(client):
    assert client.post('/api/notify_alert', json={'msg': 'x'}).status_code == 401


def test_api_notify_alert_missing_msg(client, auth_headers):
    resp = client.post('/api/notify_alert', json={'level': 'warn'}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'error', 'message': '缺少告警内容'}


def test_api_notify_alert_blank_msg(client, auth_headers):
    resp = client.post('/api/notify_alert', json={'msg': '   '}, headers=auth_headers)
    assert resp.status_code == 400


def test_api_notify_alert_without_webhook_skipped(client, auth_headers):
    resp = client.post('/api/notify_alert', json={'msg': '水位过高'}, headers=auth_headers)
    assert resp.get_json() == {'status': 'skipped', 'sent': False}


def test_api_notify_alert_sent(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), webhook_url='https://example.com/hook')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(200))
    resp = client.post('/api/notify_alert', json={'msg': '水位过高', 'level': 'danger'},
                       headers=auth_headers)
    assert resp.get_json() == {'status': 'success', 'sent': True}


def test_api_notify_alert_truncates_msg(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), webhook_url='https://example.com/hook')
    captured = {}
    monkeypatch.setattr(requests, 'post',
                        lambda url, json=None, **k: captured.update(p=json) or _Resp(200))
    client.post('/api/notify_alert', json={'msg': 'x' * 900}, headers=auth_headers)
    assert captured['p']['text']['content'].endswith('x' * 500)
    assert 'x' * 501 not in captured['p']['text']['content']


def test_api_notify_alert_upstream_failure_still_200(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), webhook_url='https://example.com/hook')

    def boom(*a, **k):
        raise requests.ConnectionError('refused')

    monkeypatch.setattr(requests, 'post', boom)
    resp = client.post('/api/notify_alert', json={'msg': 'x'}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'skipped', 'sent': False}
