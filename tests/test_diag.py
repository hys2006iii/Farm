"""连通性自检（qinghe/diag.py）与 /api/diag/<target> 的测试。

设置页四块外部接入各有一个「测试连接」按钮。这里锁住三件事：

1. **不联网也要能测**：所有出网调用都 monkeypatch 掉，断言的是「参数校验 +
   结果翻译」这套逻辑，而不是上游服务可用性；
2. **失败不抛异常**：上游超时、返回非 JSON、返回错误码，都必须变成
   `{'ok': False, 'message': ...}`，接口本身仍返回 200；
3. **掩码不当真值**：`config.MASK` 是「已设置但不回显」的占位，不能拿它去请求。
"""

import json

import pytest

from helpers import set_config, user_id_of

from qinghe import config, diag


@pytest.fixture()
def uid(registered):
    """已登录用户的 uid。"""
    username, _password = registered
    return user_id_of(username)


# ============================================================
# 一、参数校验（不触网）
# ============================================================

def test_run_test_rejects_unknown_target():
    """未知目标不抛异常，返回可读失败。"""
    result = diag.run_test(1, 'no-such-target')
    assert result['ok'] is False
    assert '未知的测试目标' in result['message']


@pytest.mark.parametrize('target', diag.TARGETS)
def test_run_test_handles_missing_config(client, registered, target):
    """用户没有任何配置时，四个目标都要给出可读失败而不是异常。"""
    result = diag.run_test(user_id_of(registered[0]), target)
    assert result['ok'] is False
    assert result['message']


def test_iot_reports_every_missing_field(uid):
    """物联网参数缺失时，逐项列出缺什么（而不是笼统的「参数错误」）。"""
    set_config(uid, iot_host='', iot_device_id='', iot_client_id='', iot_user='', iot_pass='')
    result = diag.test_iot(_cfg(uid))
    assert result['ok'] is False
    for label in ('接入地址', '设备 ID', '客户端 ID', '用户名', '口令'):
        assert label in result['message']


def test_iot_rejects_mask_placeholder(uid):
    """掩码占位必须当成「未填写」，否则会拿 •••••••• 去连。"""
    set_config(uid, iot_host='example.com', iot_device_id='dev', iot_client_id='cid',
               iot_user='usr', iot_pass=config.MASK)
    result = diag.test_iot(_cfg(uid))
    assert result['ok'] is False
    assert '口令' in result['message']


def test_weather_requires_key(uid):
    """没填天气 Key 时直接说明，不去请求上游。"""
    set_config(uid, weather_key='')
    result = diag.test_weather(_cfg(uid))
    assert result['ok'] is False
    assert 'API Key' in result['message']


def test_weather_requires_coords(uid, monkeypatch):
    """有 Key 但没经纬度时给出「先设地块」的指引。"""
    set_config(uid, weather_key='k' * 16, farm_lat=None, farm_lng=None)
    called = []
    monkeypatch.setattr('qinghe.weather.fetch_forecast',
                        lambda *a, **kw: called.append(a) or {})
    result = diag.test_weather(_cfg(uid))
    assert result['ok'] is False
    assert '经纬度' in result['message']
    assert called == [], '缺少经纬度时不应该发请求'


def test_ai_rejects_private_host(uid):
    """AI 域名指向内网时直接拦掉（防 SSRF），不发出请求。"""
    set_config(uid, ai_domain='http://127.0.0.1:8080', ai_key='sk-test')
    result = diag.test_ai(_cfg(uid))
    assert result['ok'] is False
    assert '本机或内网' in result['message']


def test_webhook_requires_http_scheme(uid):
    """Webhook 地址必须带协议头。"""
    set_config(uid, webhook_url='oapi.dingtalk.com/robot/send')
    result = diag.test_webhook(_cfg(uid))
    assert result['ok'] is False
    assert 'http' in result['message']


def test_webhook_rejects_private_host(uid):
    """Webhook 同样防 SSRF。"""
    set_config(uid, webhook_url='http://169.254.169.254/latest/meta-data')
    result = diag.test_webhook(_cfg(uid))
    assert result['ok'] is False
    assert '本机或内网' in result['message']


def _cfg(uid):
    """按 uid 取配置字典（diag 内部用的就是这一份）。"""
    from qinghe import db
    return dict(db.load_config(uid))


# ============================================================
# 二、成功路径（monkeypatch 掉网络）
# ============================================================

class _FakeResponse:
    """最小的 requests 响应替身。"""

    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


def test_weather_success_reports_day_count(uid, monkeypatch):
    """成功时回报拿到几天预报，让人一眼看出接口对不对。"""
    set_config(uid, weather_key='k' * 16, weather_domain='api.example.com',
               farm_lat=30.1, farm_lng=120.2)
    daily = [{'date': '2026-10-%02d' % d} for d in range(1, 8)]
    monkeypatch.setattr('qinghe.weather.fetch_forecast',
                        lambda *a, **kw: {'code': '200', 'daily': daily})
    result = diag.test_weather(_cfg(uid))
    assert result['ok'] is True
    assert '7 天' in result['message']


def test_weather_upstream_error_code_is_failure(uid, monkeypatch):
    """上游返回非 200 业务码要判失败，并带上错误码。"""
    set_config(uid, weather_key='k' * 16, farm_lat=30.1, farm_lng=120.2)
    monkeypatch.setattr('qinghe.weather.fetch_forecast',
                        lambda *a, **kw: {'code': '401', 'message': 'invalid key'})
    result = diag.test_weather(_cfg(uid))
    assert result['ok'] is False
    assert '401' in result['message']


def test_weather_network_failure_is_failure(uid, monkeypatch):
    """网络层失败（fetch_forecast 回 ERR）也走同一条失败路径。"""
    set_config(uid, weather_key='k' * 16, farm_lat=30.1, farm_lng=120.2)
    monkeypatch.setattr('qinghe.weather.fetch_forecast',
                        lambda *a, **kw: {'code': 'ERR', 'error': '天气接口请求失败: Timeout'})
    result = diag.test_weather(_cfg(uid))
    assert result['ok'] is False
    assert 'Timeout' in result['detail']


def test_ai_success(uid, monkeypatch):
    """AI 正常应答判成功。"""
    set_config(uid, ai_key='sk-test', ai_domain='https://api.deepseek.com')
    monkeypatch.setattr('qinghe.diag.requests.post',
                        lambda *a, **kw: _FakeResponse(200, {'choices': [{'message': {}}]}))
    result = diag.test_ai(_cfg(uid))
    assert result['ok'] is True


def test_ai_401_means_bad_key(uid, monkeypatch):
    """401 单独翻译成「API Key 无效」，比「HTTP 401」更可操作。"""
    set_config(uid, ai_key='sk-bad', ai_domain='https://api.deepseek.com')
    monkeypatch.setattr('qinghe.diag.requests.post',
                        lambda *a, **kw: _FakeResponse(401, None, 'unauthorized'))
    result = diag.test_ai(_cfg(uid))
    assert result['ok'] is False
    assert 'Key 无效' in result['message']


def test_ai_non_json_is_failure(uid, monkeypatch):
    """返回 HTML 错误页时要判失败而不是 500。"""
    set_config(uid, ai_key='sk-test', ai_domain='https://api.deepseek.com')
    monkeypatch.setattr('qinghe.diag.requests.post',
                        lambda *a, **kw: _FakeResponse(200, None, '<html>502</html>'))
    result = diag.test_ai(_cfg(uid))
    assert result['ok'] is False
    assert '非 JSON' in result['message']


def test_ai_timeout_is_failure_not_exception(uid, monkeypatch):
    """上游超时必须被吞掉，翻译成可读失败。"""
    set_config(uid, ai_key='sk-test', ai_domain='https://api.deepseek.com')

    def boom(*_a, **_kw):
        raise TimeoutError('timed out')

    monkeypatch.setattr('qinghe.diag.requests.post', boom)
    result = diag.test_ai(_cfg(uid))
    assert result['ok'] is False
    assert 'TimeoutError' in result['detail']


def test_webhook_success(uid, monkeypatch):
    """钉钉返回 errcode=0 判成功。"""
    set_config(uid, webhook_url='https://oapi.dingtalk.com/robot/send?access_token=x')
    monkeypatch.setattr('qinghe.diag.requests.post',
                        lambda *a, **kw: _FakeResponse(200, {'errcode': 0, 'errmsg': 'ok'}))
    result = diag.test_webhook(_cfg(uid))
    assert result['ok'] is True
    assert '推送成功' in result['message']


def test_webhook_carries_keyword_prefix(uid, monkeypatch):
    """测试消息必须带关键词前缀，否则钉钉会以 310000 拒绝。"""
    set_config(uid, webhook_url='https://oapi.dingtalk.com/robot/send?access_token=x')
    seen = {}

    def capture(url, **kwargs):
        seen['payload'] = kwargs.get('json')
        return _FakeResponse(200, {'errcode': 0})

    monkeypatch.setattr('qinghe.diag.requests.post', capture)
    diag.test_webhook(_cfg(uid))
    assert config.ALERT_KEY_PREFIX in seen['payload']['text']['content']


def test_webhook_business_error_code_is_failure(uid, monkeypatch):
    """钉钉即使业务失败也回 HTTP 200，真正的结果在 body 的 errcode 里。"""
    set_config(uid, webhook_url='https://oapi.dingtalk.com/robot/send?access_token=x')
    monkeypatch.setattr(
        'qinghe.diag.requests.post',
        lambda *a, **kw: _FakeResponse(200, {'errcode': 310000, 'errmsg': 'keywords not in content'}))
    result = diag.test_webhook(_cfg(uid))
    assert result['ok'] is False
    assert '310000' in result['message']


def test_webhook_empty_body_is_success(uid, monkeypatch):
    """有的机器人回空 body，HTTP 200 即视为成功。"""
    set_config(uid, webhook_url='https://oapi.dingtalk.com/robot/send?access_token=x')
    monkeypatch.setattr('qinghe.diag.requests.post', lambda *a, **kw: _FakeResponse(200, None))
    result = diag.test_webhook(_cfg(uid))
    assert result['ok'] is True


def test_iot_success_connects_socket(uid, monkeypatch):
    """物联网探测走 socket：能连上就说明域名与端口没填错。"""
    set_config(uid, iot_host='iot.example.com', iot_device_id='dev', iot_client_id='cid',
               iot_user='usr', iot_pass='pwd', iot_port=8883)
    import socket

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: _FakeSocket())
    result = diag.test_iot(_cfg(uid))
    assert result['ok'] is True
    assert '8883' in result['message']


def test_iot_dns_failure_is_readable(uid, monkeypatch):
    """域名解析失败要单独翻译，提示去查接入地址。"""
    set_config(uid, iot_host='nope.invalid', iot_device_id='dev', iot_client_id='cid',
               iot_user='usr', iot_pass='pwd')
    import socket

    def boom(*_a, **_kw):
        raise socket.gaierror('name resolution failed')

    monkeypatch.setattr(socket, 'create_connection', boom)
    result = diag.test_iot(_cfg(uid))
    assert result['ok'] is False
    assert '域名解析失败' in result['message']


def test_detail_is_truncated():
    """上游可能回整页 HTML，detail 必须截断，不能把响应体整个塞回去。"""
    result = diag._result(False, 'x', 'y' * 5000)
    assert len(result['detail']) == diag.DETAIL_MAX_LEN


# ============================================================
# 三、HTTP 接口
# ============================================================

def test_diag_endpoint_requires_login(client):
    """未登录 401，不能让人拿接口去探测内网。"""
    assert client.post('/api/diag/iot').status_code == 401


def test_diag_endpoint_rejects_unknown_target(client, registered):
    """未知目标 400（而不是 500）。"""
    resp = client.post('/api/diag/no-such')
    assert resp.status_code == 400
    assert '未知的测试目标' in resp.get_json()['error']


@pytest.mark.parametrize('target', diag.TARGETS)
def test_diag_endpoint_returns_ok_flag(client, registered, target):
    """四个目标都要回 200 + ok 字段：探测失败不是接口错误。"""
    resp = client.post('/api/diag/%s' % target)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is False, '本用例没有配置任何外部接入，应为失败'
    assert isinstance(body['message'], str) and body['message']


def test_diag_endpoint_success_path(client, registered, monkeypatch):
    """配置齐全且上游正常时接口回 ok=True。"""
    uid = user_id_of(registered[0])
    set_config(uid, webhook_url='https://oapi.dingtalk.com/robot/send?access_token=x')
    monkeypatch.setattr('qinghe.diag.requests.post',
                        lambda *a, **kw: _FakeResponse(200, {'errcode': 0}))
    body = client.post('/api/diag/webhook').get_json()
    assert body['ok'] is True


def test_diag_endpoint_never_returns_500_on_internal_error(client, registered, monkeypatch):
    """探测函数内部出意外时也要回结构化失败，不能 500。"""
    def boom(*_a, **_kw):
        raise RuntimeError('内部炸了')

    monkeypatch.setattr('qinghe.diag._HANDLERS', {'iot': boom})
    resp = client.post('/api/diag/iot')
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is False


def test_diag_does_not_write_to_db(client, registered):
    """探测是只读的：不能顺手改配置或落日志。"""
    uid = user_id_of(registered[0])
    before = _cfg(uid)
    client.post('/api/diag/iot')
    client.post('/api/diag/webhook')
    assert _cfg(uid) == before


def test_diag_targets_match_handlers():
    """TARGETS 与 _HANDLERS 必须一一对应，避免加了目标却忘了实现。"""
    assert set(diag.TARGETS) == set(diag._HANDLERS)


def test_diag_json_serializable(client, registered):
    """结果必须能直接 jsonify（前端只读 ok/message/detail）。"""
    body = client.post('/api/diag/weather').get_json()
    assert set(body) == {'ok', 'message', 'detail'}
    json.dumps(body)
