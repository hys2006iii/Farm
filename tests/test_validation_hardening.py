"""入参加固回归测试：非对象请求体、farm_id 溢出、配置字段校验、请求体上限。

对应 api-auditor 报告的 P0-2 / P0-3 / P0-4 / P1-4 / P1-6 / P2（413、415）：
- 真值为非 dict 的 JSON 体一律 4xx，不再 500；
- farm_id 超 SQLite INTEGER 范围返回 400；
- 配置写入（名称/经纬度/Webhook/manual_mode）非法值 400，不静默写脏数据；
- 地块面积显式 null 不再清零；请求体超限 413、Content-Type 不符 415 也返回 JSON。
"""

import json

import pytest

from qinghe import config, db
from helpers import fetch_one, user_id_of


def _body(resp, status):
    """断言状态码并返回 JSON。"""
    assert resp.status_code == status, resp.data[:300]
    return resp.get_json()


@pytest.mark.parametrize('path', [
    '/api/register', '/api/login', '/api/app_login', '/api/change_password',
    '/api/save_config', '/api/thresh_settings', '/api/ai_chat',
    '/api/farms', '/api/farms/switch', '/api/farms/update', '/api/farms/delete',
])
def test_non_object_body_returns_400(client, registered, path):
    """`[1]` / `"x"` 这类合法 JSON 但不是对象时返回 400。"""
    resp = client.post(path, json=[1])
    assert resp.status_code == 400, (path, resp.data[:300])
    assert resp.is_json


def test_non_object_body_on_jwt_command_returns_400(client, auth_headers):
    """App 端指令接口（JWT 鉴权）同样不能因非对象体 500。"""
    resp = client.post('/api/app_send_command', json=123, headers=auth_headers)
    assert resp.status_code == 400


# ------------------------------------------------------------
# P0-3：farm_id 溢出 / 非法
# ------------------------------------------------------------


@pytest.mark.parametrize('path', ['/api/farms/switch', '/api/farms/update', '/api/farms/delete'])
def test_farm_id_overflow_returns_400(client, registered, path):
    """2**63 会触发 SQLite OverflowError，必须在入参层拦掉。"""
    body = _body(client.post(path, json={'farm_id': 2 ** 63}), 400)
    assert 'farm_id' in body['message']


@pytest.mark.parametrize('path', ['/api/farms/switch', '/api/farms/update', '/api/farms/delete'])
def test_farm_id_wrong_type_returns_400(client, registered, path):
    body = _body(client.post(path, json={'farm_id': 'abc'}), 400)
    assert body['status'] == 'error'


# ------------------------------------------------------------
# P0-4：配置字段类型 / 长度 / 范围
# ------------------------------------------------------------


def test_save_config_farm_name_wrong_type_returns_400(client, registered):
    """dict / list 不再让 sqlite3 bind 抛 500。"""
    assert client.post('/api/save_config', json={'farm_name': {'x': 1}}).status_code == 400
    assert client.post('/api/save_config', json={'farm_name': ['a']}).status_code == 400


def test_save_config_farm_name_too_long_returns_400(client, registered):
    too_long = '很长的农场名' * 10
    body = _body(client.post('/api/save_config', json={'farm_name': too_long}), 400)
    assert '长度' in body['error']


@pytest.mark.parametrize('value', ['abc', 999, 91, True, [1]])
def test_save_config_lat_invalid_returns_400(client, registered, value):
    assert client.post('/api/save_config', json={'farm_lat': value}).status_code == 400


def test_save_config_webhook_without_scheme_returns_400(client, registered):
    body = _body(client.post('/api/save_config', json={'webhook_url': 'ftp://x/y'}), 400)
    assert 'http' in body['error']


def test_save_config_keeps_string_coordinate_type(client, registered):
    """前端传字符串坐标时按原样落库（历史契约），不能统一转 float 丢格式。"""
    uid = user_id_of('farmer01')
    _body(client.post('/api/save_config', json={'farm_lat': '31.90', 'farm_lng': '118.78'}), 200)
    row = fetch_one('SELECT farm_lat, farm_lng FROM configs WHERE user_id=?', (uid,))
    assert row['farm_lat'] == '31.90'
    assert row['farm_lng'] == '118.78'


def test_save_thresh_manual_mode_string_false_returns_400(client, registered):
    """`"false"` 曾被 truthy 判断当成开启，必须 400。"""
    body = _body(client.post('/api/thresh_settings', json={'manual_mode': 'false'}), 400)
    assert 'manual_mode' in body['error']


def test_save_thresh_missing_fields_uses_defaults(client, registered):
    """空对象仍按默认值写入并 200（旧契约）。"""
    body = _body(client.post('/api/thresh_settings', json={}), 200)
    assert body['status'] == 'success'


@pytest.mark.parametrize('payload', [
    {'message': {'x': 1}}, {'message': ['hi']}, {'message': 12},
])
def test_ai_chat_message_wrong_type_returns_400(client, registered, payload):
    assert client.post('/api/ai_chat', json=payload).status_code == 400


def test_ai_chat_message_too_long_returns_400(client, registered):
    resp = client.post('/api/ai_chat', json={'message': '水' * (config.AI_MSG_MAX_LEN + 1)})
    body = _body(resp, 400)
    assert '过长' in body['error']


def test_ai_chat_empty_message_still_200(client, registered):
    """旧契约：空消息仍返回 200（无 Key 时给提示）。"""
    resp = client.post('/api/ai_chat', json={'message': ''})
    assert resp.status_code == 200
    assert resp.get_json()['choices']


# ------------------------------------------------------------
# P0-1：AI 域名 SSRF
# ------------------------------------------------------------


def test_oversized_body_returns_json_413(client):
    big = json.dumps({'username': 'x' * (600 * 1024), 'password': 'y'})
    resp = client.post('/api/login', data=big, content_type='application/json')
    assert resp.status_code == 413
    assert resp.is_json


def test_plain_text_body_returns_json_415(client):
    resp = client.post('/api/login', data='not json', content_type='text/plain')
    assert resp.status_code == 415
    assert resp.is_json


def test_update_farm_area_null_keeps_old_value(client, registered):
    """显式 null 不再把面积静默清零。"""
    uid = user_id_of('farmer01')
    created = _body(client.post('/api/farms', json={'name': '面积块', 'area_m2': 800}), 200)
    farm_id = created['farm']['id']
    _body(client.post('/api/farms/update',
                     json={'farm_id': farm_id, 'area_m2': None, 'name': '面积块'}), 200)
    farm = db.get_farm(uid, farm_id)
    assert float(farm['area_m2']) == pytest.approx(800.0)


# ------------------------------------------------------------
# P1-6：AI 提问入参
# ------------------------------------------------------------
