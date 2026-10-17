"""AI 对话代理测试：全部离线（monkeypatch requests），不联网。"""

import pytest
import requests

from helpers import set_config, user_id_of
from qinghe import ai, config

NO_KEY_TIP = '⚠️ 提示：未检测到 AI Key，请在【设置】中配置。'
SYSTEM_PROMPT = '你是一个智能灌溉与水利控制系统助手，请简洁专业地回答中文问题。'


class _Resp:
    """假 HTTP 响应。"""

    def __init__(self, payload=None, status_code=200, raise_json=False, text=''):
        self._payload = payload
        self.status_code = status_code
        self._raise_json = raise_json
        self.text = text

    def json(self):
        if self._raise_json:
            raise ValueError('not json')
        return self._payload


def _content(resp_json):
    """从响应 dict 里取出 choices 首条 content。"""
    return resp_json['choices'][0]['message']['content']


# ============================================================
# 契约常量
# ============================================================

def test_system_prompt_is_exact():
    assert ai.SYSTEM_PROMPT == SYSTEM_PROMPT


def test_model_name_is_deepseek_chat():
    _url, _headers, body = ai.build_chat_request(None, 'hi')
    assert body['model'] == 'deepseek-chat'
    assert body['model'] == config.DEFAULT_AI_MODEL


def test_wrap_shape_matches_frontend_contract():
    got = ai._wrap('hello')
    assert got == {'choices': [{'message': {'content': 'hello'}}]}


# ============================================================
# normalize_base_url
# ============================================================

def test_normalize_base_url_empty_uses_default():
    assert ai.normalize_base_url(None) == config.DEFAULT_AI_DOMAIN
    assert ai.normalize_base_url('') == config.DEFAULT_AI_DOMAIN


def test_normalize_base_url_upgrades_http_deepseek():
    assert ai.normalize_base_url('http://api.deepseek.com') == 'https://api.deepseek.com'


def test_normalize_base_url_strips_whitespace():
    assert ai.normalize_base_url('  https://api.deepseek.com  ') == 'https://api.deepseek.com'


def test_normalize_base_url_keeps_other_http_hosts():
    """仅纠正 deepseek 官方域名，其它自建地址保持原样。"""
    assert ai.normalize_base_url('http://my-llm.local:8000') == 'http://my-llm.local:8000'


# ============================================================
# build_chat_request
# ============================================================

def test_build_chat_request_url_and_headers():
    url, headers, _body = ai.build_chat_request('https://api.deepseek.com', 'hi')
    assert url == 'https://api.deepseek.com/chat/completions'
    assert headers['Content-Type'] == 'application/json'


def test_build_chat_request_strips_trailing_slash():
    url, _h, _b = ai.build_chat_request('https://api.deepseek.com/', 'hi')
    assert url == 'https://api.deepseek.com/chat/completions'


def test_build_chat_request_messages_order():
    _u, _h, body = ai.build_chat_request(None, '水稻要浇多少水？')
    assert body['messages'] == [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': '水稻要浇多少水？'},
    ]
    assert body['stream'] is False


# ============================================================
# chat()
# ============================================================

def test_chat_success_passthrough(monkeypatch):
    payload = {'choices': [{'message': {'content': '每天 20 升'}}]}
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(payload))
    assert ai.chat(None, 'KEY', 'hi') == payload


def test_chat_sends_bearer_token_and_timeout(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json, timeout=timeout)
        return _Resp({'choices': []})

    monkeypatch.setattr(requests, 'post', fake_post)
    ai.chat('https://api.deepseek.com', 'sk-abc', 'hi')
    assert captured['headers']['Authorization'] == 'Bearer sk-abc'
    assert captured['timeout'] == config.TIMEOUT_AI
    assert captured['url'] == 'https://api.deepseek.com/chat/completions'


def test_chat_http_error_wrapped_not_raised(monkeypatch):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(
        status_code=401, text='unauthorized'))
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got) == 'AI 接口返回异常（HTTP 401）：unauthorized'


def test_chat_http_error_snippet_truncated_to_300(monkeypatch):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(
        status_code=500, text='E' * 800))
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got) == 'AI 接口返回异常（HTTP 500）：%s' % ('E' * 300)


def test_chat_http_error_empty_body_placeholder(monkeypatch):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(
        status_code=500, text=''))
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got) == 'AI 接口返回异常（HTTP 500）：(空响应)'


def test_chat_non_json_wrapped(monkeypatch):
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(
        status_code=200, raise_json=True, text='<html>oops</html>'))
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got) == 'AI 接口返回非 JSON 内容（HTTP 200）：<html>oops</html>'


def test_chat_timeout_wrapped(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout('timed out')

    monkeypatch.setattr(requests, 'post', boom)
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got) == '请求失败: timed out'


def test_chat_never_raises_on_unexpected_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('weird')

    monkeypatch.setattr(requests, 'post', boom)
    got = ai.chat(None, 'KEY', 'hi')
    assert _content(got).startswith('请求失败: ')


def test_chat_result_always_has_choices_shape(monkeypatch):
    """无论成功失败，返回结构都必须能被前端 choices[0].message.content 读取。"""
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(status_code=503, text='x'))
    got = ai.chat(None, 'KEY', 'hi')
    assert isinstance(got['choices'], list)
    assert isinstance(_content(got), str)


# ============================================================
# 接口层：/api/ai_chat
# ============================================================

def test_api_ai_chat_requires_login(client):
    assert client.post('/api/ai_chat', json={'message': 'hi'}).status_code == 401


def test_api_ai_chat_without_key_returns_tip(client, auth_headers, monkeypatch):
    monkeypatch.setattr(requests, 'post',
                        lambda *a, **k: pytest.fail('无 Key 时不应发起请求'))
    resp = client.post('/api/ai_chat', json={'message': 'hi'}, headers=auth_headers)
    assert resp.status_code == 200
    assert _content(resp.get_json()) == NO_KEY_TIP


def test_api_ai_chat_with_key_proxies(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), ai_key='sk-x')
    payload = {'choices': [{'message': {'content': 'ok'}}]}
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(payload))
    resp = client.post('/api/ai_chat', json={'message': 'hi'}, headers=auth_headers)
    assert resp.get_json() == payload


def test_api_ai_chat_upstream_error_wrapped(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), ai_key='sk-x')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: _Resp(status_code=429, text='rate'))
    got = client.post('/api/ai_chat', json={'message': 'hi'}, headers=auth_headers).get_json()
    assert _content(got) == 'AI 接口返回异常（HTTP 429）：rate'


def test_api_ai_chat_uses_configured_domain(client, auth_headers, monkeypatch):
    set_config(user_id_of('farmer01'), ai_key='sk-x',
               ai_domain='http://api.deepseek.com')
    captured = {}
    monkeypatch.setattr(requests, 'post',
                        lambda url, **k: captured.update(url=url) or _Resp({'choices': []}))
    client.post('/api/ai_chat', json={'message': 'hi'}, headers=auth_headers)
    assert captured['url'] == 'https://api.deepseek.com/chat/completions'


def test_api_ai_chat_empty_message_still_200(client, auth_headers, monkeypatch):
    """空消息不报 500（旧版行为：照常转发或返回提示）。"""
    set_config(user_id_of('farmer01'), ai_key='sk-x')
    monkeypatch.setattr(requests, 'post',
                        lambda *a, **k: _Resp({'choices': [{'message': {'content': ''}}]}))
    resp = client.post('/api/ai_chat', json={'message': ''}, headers=auth_headers)
    assert resp.status_code == 200


def test_api_ai_chat_missing_body_returns_415(client, auth_headers):
    """无 body 且无 Content-Type 时 Werkzeug 直接 415。

    这是旧版 app.py 用 `request.json`（而非 `get_json(silent=True)`）就有的行为，
    非本次重构引入的回归，但属于**已知缺陷**：前端正常请求都带
    `Content-Type: application/json`，因此线上不会触发；此处把现状钉住，
    避免以后误以为是新引入的问题。修复方向见交付说明的 bug 清单。
    """
    resp = client.post('/api/ai_chat', headers=auth_headers)
    assert resp.status_code == 415


def test_api_ai_chat_missing_body_with_json_content_type_200(client, auth_headers, monkeypatch):
    """带正确 Content-Type 但空 body 时不应 500。"""
    set_config(user_id_of('farmer01'), ai_key='sk-x')
    monkeypatch.setattr(requests, 'post',
                        lambda *a, **k: _Resp({'choices': [{'message': {'content': ''}}]}))
    resp = client.post('/api/ai_chat', headers=dict(auth_headers,
                                                    **{'Content-Type': 'application/json'}))
    assert resp.status_code == 200
