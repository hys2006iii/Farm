"""天气与逆地理模块测试（全部离线：monkeypatch 掉 requests，不联网）。"""

import pytest
import requests

from helpers import fetch_one
from qinghe import config, weather


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


# ============================================================
# _pick_admin
# ============================================================

def test_pick_admin_filters_country_and_empty():
    assert weather._pick_admin(['中华人民共和国', '中国', '', None, '浙江省']) == ['浙江省']


def test_pick_admin_dedupes_keeping_order():
    assert weather._pick_admin(['浙江省', '浙江省', '杭州市']) == ['浙江省', '杭州市']


def test_pick_admin_keeps_at_most_four_levels():
    got = weather._pick_admin(['A省', 'B市', 'C区', 'D街道', 'E社区'])
    assert got == ['B市', 'C区', 'D街道', 'E社区']      # 取最细 4 级


def test_pick_admin_preserves_big_to_small_order():
    assert weather._pick_admin(['浙江省', '杭州市', '西湖区']) == ['浙江省', '杭州市', '西湖区']


def test_pick_admin_all_empty_returns_empty():
    assert weather._pick_admin([None, '', '中国']) == []


def test_pick_admin_empty_input():
    assert weather._pick_admin([]) == []


# ============================================================
# photon_reverse
# ============================================================

def _photon_payload(props):
    return {'features': [{'properties': props}]}


def test_photon_reverse_success_joins_chain(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        _photon_payload({'state': '浙江省', 'city': '杭州市', 'district': '西湖区'})))
    assert weather.photon_reverse(30.2, 120.1) == '浙江省 · 杭州市 · 西湖区'


def test_photon_reverse_appends_finer_name(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        _photon_payload({'state': '浙江省', 'city': '杭州市', 'name': '文新街道'})))
    assert weather.photon_reverse(30.2, 120.1) == '浙江省 · 杭州市 · 文新街道'


def test_photon_reverse_does_not_duplicate_name(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        _photon_payload({'city': '杭州市', 'name': '杭州市'})))
    assert weather.photon_reverse(30.2, 120.1) == '杭州市'


def test_photon_reverse_timeout_returns_none(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout('timed out')

    monkeypatch.setattr(requests, 'get', boom)
    assert weather.photon_reverse(30.2, 120.1) is None


def test_photon_reverse_non_json_returns_none(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(raise_json=True))
    assert weather.photon_reverse(30.2, 120.1) is None


def test_photon_reverse_http_500_with_valid_json_still_parses(monkeypatch):
    """旧版未检查状态码：500 但体是合法 JSON 时仍照常解析（行为保持一致）。"""
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        _photon_payload({'city': '杭州市'}), status_code=500))
    assert weather.photon_reverse(30.2, 120.1) == '杭州市'


def test_photon_reverse_empty_properties_returns_none(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(_photon_payload({})))
    assert weather.photon_reverse(30.2, 120.1) is None


def test_photon_reverse_empty_features_returns_none(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp({'features': []}))
    assert weather.photon_reverse(30.2, 120.1) is None


def test_photon_reverse_passes_timeout_and_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(url=url, params=params, timeout=timeout)
        return _Resp(_photon_payload({'city': '杭州市'}))

    monkeypatch.setattr(requests, 'get', fake_get)
    weather.photon_reverse(30.25, 120.15)
    assert captured['url'] == 'https://photon.komoot.io/reverse'
    assert captured['params'] == {'lat': 30.25, 'lon': 120.15, 'lang': 'zh'}
    assert captured['timeout'] == config.TIMEOUT_PHOTON


def test_photon_reverse_only_keeps_last_four(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(_photon_payload({
        'state': 'A', 'city': 'B', 'county': 'C', 'district': 'D',
        'suburb': 'E', 'quarter': 'F'})))
    assert weather.photon_reverse(1, 2) == 'C · D · E · F'


# ============================================================
# geo_key / 兜底文案
# ============================================================

def test_geo_key_rounds_to_four_decimals():
    assert weather.geo_key(30.123456, 120.654321) == '30.1235,120.6543'


def test_geo_fallback_text_format():
    assert weather.geo_fallback_text(30.2, 120.15) == 'E: 120.15°, N: 30.20°'


# ============================================================
# geo_lookup（缓存）
# ============================================================

def test_geo_lookup_miss_calls_photon_and_caches(flask_app, monkeypatch):
    calls = []

    def fake_reverse(lat, lng):
        calls.append((lat, lng))
        return '浙江省 · 杭州市'

    monkeypatch.setattr(weather, 'photon_reverse', fake_reverse)
    name, cached = weather.geo_lookup(30.2, 120.1)
    assert (name, cached) == ('浙江省 · 杭州市', False)
    assert calls == [(30.2, 120.1)]
    row = fetch_one('SELECT name FROM geo_cache WHERE key=?', ('30.2,120.1',))
    assert row['name'] == '浙江省 · 杭州市'


def test_geo_lookup_hit_does_not_call_external(flask_app, monkeypatch):
    from qinghe import db

    db.set_geo_cache('30.2,120.1', '浙江省 · 杭州市')

    def boom(*a, **k):
        raise AssertionError('缓存命中时不应发起外部请求')

    monkeypatch.setattr(weather, 'photon_reverse', boom)
    name, cached = weather.geo_lookup(30.2, 120.1)
    assert (name, cached) == ('浙江省 · 杭州市', True)


def test_geo_lookup_failure_returns_none_and_no_cache(flask_app, monkeypatch):
    monkeypatch.setattr(weather, 'photon_reverse', lambda lat, lng: None)
    name, cached = weather.geo_lookup(30.9, 121.9)
    assert (name, cached) == (None, False)
    assert fetch_one('SELECT name FROM geo_cache WHERE key=?', ('30.9,121.9',)) is None


def test_geo_lookup_same_coordinate_only_calls_once(flask_app, monkeypatch):
    calls = []

    def fake_reverse(lat, lng):
        calls.append(1)
        return '杭州市'

    monkeypatch.setattr(weather, 'photon_reverse', fake_reverse)
    weather.geo_lookup(30.2, 120.1)
    weather.geo_lookup(30.2, 120.1)
    assert len(calls) == 1


# ============================================================
# fetch_forecast
# ============================================================

def test_build_forecast_url_default_domain():
    url = weather.build_forecast_url(None, '118.78', '31.90', 'KEY')
    assert url == ('https://%s/v7/weather/7d?location=118.78,31.90&key=KEY'
                   % config.DEFAULT_WEATHER_DOMAIN)


def test_build_forecast_url_custom_domain():
    url = weather.build_forecast_url('api.example.com', 1, 2, 'K')
    assert url == 'https://api.example.com/v7/weather/7d?location=1,2&key=K'


def test_fetch_forecast_success_passthrough(monkeypatch):
    payload = {'code': '200', 'daily': [{'fxDate': '2026-01-01'}]}
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(payload))
    assert weather.fetch_forecast(None, '118.78', '31.90', 'KEY') == payload


def test_fetch_forecast_uses_timeout(monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured['timeout'] = timeout
        return _Resp({'code': '200'})

    monkeypatch.setattr(requests, 'get', fake_get)
    weather.fetch_forecast(None, 1, 2, 'K')
    assert captured['timeout'] == config.TIMEOUT_WEATHER


def test_fetch_forecast_network_error_returns_error_dict(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError('refused')

    monkeypatch.setattr(requests, 'get', boom)
    got = weather.fetch_forecast(None, 1, 2, 'K')
    assert got['code'] == 'ERR'
    assert got['error'].startswith('天气接口请求失败: ')


def test_fetch_forecast_non_json_returns_error_dict(monkeypatch):
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        status_code=502, raise_json=True))
    got = weather.fetch_forecast(None, 1, 2, 'K')
    assert got == {'code': 'ERR', 'error': '天气接口非 JSON（HTTP 502）'}


def test_fetch_forecast_never_raises(monkeypatch):
    """任何上游异常都不得向上抛到请求栈。"""
    monkeypatch.setattr(requests, 'get', lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError('weird')))
    got = weather.fetch_forecast(None, 1, 2, 'K')
    assert got['code'] == 'ERR'


@pytest.mark.parametrize('payload,expected', [
    ({'code': 'ERR', 'error': 'x'}, True),
    ({'code': '200', 'daily': []}, False),
    ({}, False),
    (None, True),
    ('not-a-dict', True),
    ([], True),
])
def test_forecast_failed_classifies_payload(payload, expected):
    """路由层据此选 502/200：只有明确失败体或非 dict 才判失败。"""
    assert weather.forecast_failed(payload) is expected


# ============================================================
# 接口层：/api/forecast 与 /api/reverse_geocode（离线）
# ============================================================

def test_api_forecast_requires_login(client):
    assert client.get('/api/forecast').status_code == 401


def test_api_forecast_without_key_returns_err(client, auth_headers):
    """未配置 Key 属于服务端不可用，返回 502 且响应体保持 {code:ERR, error:...}。"""
    resp = client.get('/api/forecast', headers=auth_headers)
    assert resp.status_code == 502
    assert resp.get_json() == {'code': 'ERR', 'error': '未配置天气 API Key'}


def test_api_forecast_with_key_proxies(client, auth_headers, monkeypatch):
    from helpers import user_id_of, set_config

    uid = user_id_of('farmer01')
    set_config(uid, weather_key='WK')
    payload = {'code': '200', 'daily': [1, 2, 3, 4, 5, 6, 7]}
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(payload))
    resp = client.get('/api/forecast?lng=118.78&lat=31.90', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == payload


def test_api_forecast_non_json_upstream(client, auth_headers, monkeypatch):
    from helpers import user_id_of, set_config

    set_config(user_id_of('farmer01'), weather_key='WK')
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        status_code=500, raise_json=True))
    resp = client.get('/api/forecast', headers=auth_headers)
    assert resp.status_code == 502
    assert resp.get_json() == {'code': 'ERR', 'error': '天气接口非 JSON（HTTP 500）'}


def test_api_forecast_network_error_returns_502(client, auth_headers, monkeypatch):
    """上游请求异常同样以 502 上报，body 保持既有 error 文案。"""
    from helpers import user_id_of, set_config

    set_config(user_id_of('farmer01'), weather_key='WK')

    def _boom(*a, **k):
        raise requests.ConnectionError('boom')

    monkeypatch.setattr(requests, 'get', _boom)
    resp = client.get('/api/forecast', headers=auth_headers)
    assert resp.status_code == 502
    got = resp.get_json()
    assert got['code'] == 'ERR'
    assert got['error'].startswith('天气接口请求失败:')


def test_api_forecast_ok_status_is_200(client, auth_headers, monkeypatch):
    """上游 code=200 时状态码必须是 200（前端只认 body.code === '200'）。"""
    from helpers import user_id_of, set_config

    set_config(user_id_of('farmer01'), weather_key='WK')
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp(
        {'code': '200', 'daily': []}))
    resp = client.get('/api/forecast', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['code'] == '200'


def test_api_reverse_geocode_requires_login(client):
    assert client.get('/api/reverse_geocode?lat=1&lng=2').status_code == 401


def test_api_reverse_geocode_missing_coords(client, auth_headers):
    resp = client.get('/api/reverse_geocode', headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json() == {'error': '缺少坐标'}


@pytest.mark.parametrize('query', ['lat=abc&lng=2', 'lat=1&lng=xyz'])
def test_api_reverse_geocode_bad_format(client, auth_headers, query):
    resp = client.get('/api/reverse_geocode?%s' % query, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json() == {'error': '坐标格式错误'}


def test_api_reverse_geocode_blank_values_are_missing(client, auth_headers):
    """空串参数视为缺参（旧版行为）。"""
    resp = client.get('/api/reverse_geocode?lat=&lng=', headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json() == {'error': '缺少坐标'}


def test_api_reverse_geocode_success(client, auth_headers, monkeypatch):
    monkeypatch.setattr(weather, 'photon_reverse', lambda lat, lng: '浙江省 · 杭州市')
    got = client.get('/api/reverse_geocode?lat=30.2&lng=120.1',
                     headers=auth_headers).get_json()
    assert got == {'name': '浙江省 · 杭州市'}


def test_api_reverse_geocode_fallback_text(client, auth_headers, monkeypatch):
    monkeypatch.setattr(weather, 'photon_reverse', lambda lat, lng: None)
    got = client.get('/api/reverse_geocode?lat=30.2&lng=120.15',
                     headers=auth_headers).get_json()
    assert got == {'name': 'E: 120.15°, N: 30.20°'}


def test_api_reverse_geocode_second_call_hits_cache(client, auth_headers, monkeypatch):
    calls = []
    monkeypatch.setattr(weather, 'photon_reverse',
                        lambda lat, lng: calls.append(1) or '杭州市')
    client.get('/api/reverse_geocode?lat=30.2&lng=120.1', headers=auth_headers)
    client.get('/api/reverse_geocode?lat=30.2&lng=120.1', headers=auth_headers)
    assert len(calls) == 1
