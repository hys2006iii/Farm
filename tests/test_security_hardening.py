"""安全加固回归测试：SSRF、注册限流、改密会话、Cookie/CORS、错误脱敏。

对应 api-auditor 报告的 P0-1 / P1-2 / P1-7 / P1-8 / P1-9 / P1-10：
- AI / Webhook 地址不得指向本机、私网、云元数据（防 SSRF）；
- 注册接口按来源 IP 限流；改密后旧会话失效；
- 会话 Cookie 带 HttpOnly / SameSite=Lax；Socket.IO 不再放开任意跨域；
- 天气错误不回显含 Key 的 URL；webhook 超时收紧到 3s。
"""

import pytest
import requests

from qinghe import ai, alerts, config, weather
from helpers import set_config, user_id_of


def _body(resp, status):
    """断言状态码并返回 JSON。"""
    assert resp.status_code == status, resp.data[:300]
    return resp.get_json()





def test_ai_chat_allows_public_domain(monkeypatch):
    """公网域名正常放行（不因守卫误伤）。"""
    captured = {}

    class _Resp:
        status_code = 200
        text = '{}'

        def json(self):
            return {'choices': [{'message': {'content': 'ok'}}]}

    def fake_post(url, **kwargs):
        captured['url'] = url
        return _Resp()

    monkeypatch.setattr(requests, 'post', fake_post)
    got = ai.chat('https://api.deepseek.com', 'sk-test', 'hi')
    assert captured['url'].startswith('https://api.deepseek.com/')
    assert got['choices'][0]['message']['content'] == 'ok'


def test_webhook_private_target_not_called(monkeypatch, client, registered):
    """Webhook 指向本机时不发请求（SSRF），返回 False。"""
    uid = user_id_of('farmer01')
    set_config(uid, webhook_url='http://127.0.0.1:5099/hook')
    called = {'n': 0}

    def fake_post(*args, **kwargs):  # pragma: no cover - 不应被调用
        called['n'] += 1
        raise AssertionError('SSRF：webhook 不应访问本机')

    monkeypatch.setattr(alerts.requests, 'post', fake_post)
    assert alerts.notify_webhook(uid, '测试', '内容') is False
    assert called['n'] == 0


def test_webhook_timeout_is_short():
    """同步推送链路上的 webhook 超时必须收紧，最长不超过 3 秒。"""
    assert config.TIMEOUT_WEBHOOK <= 3


# ------------------------------------------------------------
# P1-10：天气错误不回显含 Key 的 URL
# ------------------------------------------------------------


def test_weather_error_does_not_echo_key(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError('https://devapi.qweather.com/v7/weather?key=SECRET')

    monkeypatch.setattr(weather.requests, 'get', boom)
    got = weather.fetch_forecast('devapi.qweather.com', 1, 2, 'SECRET')
    assert got['code'] == 'ERR'
    assert 'SECRET' not in got['error']
    assert got['error'].startswith('天气接口请求失败: ')


# ------------------------------------------------------------
# P2：请求体上限、Content-Type、Cookie / CORS 加固
# ------------------------------------------------------------


def test_session_cookie_flags(client):
    client.post('/api/register', json={'username': 'cookiefarmer', 'password': 'secret123'})
    resp = client.post('/api/login', json={'username': 'cookiefarmer', 'password': 'secret123'})
    cookie = resp.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in cookie
    assert 'SameSite=Lax' in cookie


def test_socketio_cors_disabled(flask_app):
    """Socket.IO 不再放开 '*'，避免任意站点借用用户 Cookie 建连。"""
    allowed = flask_app.config.get('CORS_ALLOWED_ORIGINS')
    assert allowed is None


# ------------------------------------------------------------
# P1-8：注册限流
# ------------------------------------------------------------


def test_register_rate_limited(client):
    """同一来源 IP 连续注册超过上限后返回 429。"""
    for i in range(config.REGISTER_MAX_ATTEMPTS):
        resp = client.post('/api/register', json={'username': 'bulk%02d' % i, 'password': 'secret123'})
        assert resp.status_code == 200, resp.data[:200]
    resp = client.post('/api/register', json={'username': 'bulk99', 'password': 'secret123'})
    body = _body(resp, 429)
    assert '频繁' in body['message']


# ------------------------------------------------------------
# 改密后旧会话失效（P1-2 的 Web 会话部分）
# ------------------------------------------------------------


def test_change_password_invalidates_session(client, registered):
    _body(client.post('/api/change_password', json={
        'old_password': 'secret123', 'new_password': 'secret456'}), 200)
    # 会话已清空：再访问需要登录的接口应 401
    assert client.get('/api/get_config').status_code == 401
    body = _body(client.post('/api/login', json={
        'username': 'farmer01', 'password': 'secret456'}), 200)
    assert body['status'] == 'success'


@pytest.mark.parametrize('domain', [
    'http://127.0.0.1:5099',
    'http://localhost:5099',
    'http://169.254.169.254/latest/meta-data',
    'http://10.0.0.5',
    'http://192.168.1.10:8080',
    'http://[::1]:5099',
    'file:///etc/passwd',
])
def test_ai_chat_rejects_private_targets(monkeypatch, domain):
    """内网 / 回环 / 元数据 / 非 http(s) 地址一律不发请求。"""
    called = {'n': 0}

    def fake_post(*args, **kwargs):  # pragma: no cover - 不应被调用
        called['n'] += 1
        raise AssertionError('SSRF：不应向 %s 发起请求' % domain)

    monkeypatch.setattr(requests, 'post', fake_post)
    got = ai.chat(domain, 'sk-test', 'hi')
    assert called['n'] == 0
    assert '不允许' in got['choices'][0]['message']['content']
