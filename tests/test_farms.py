"""多农场（地块）接口测试。

覆盖：登录携带地块清单、CRUD、切换、越权、边界校验、最后一块不可删、
切换后清空实时遥测缓存、设置页改名同步到当前地块。
"""

import pytest

from helpers import login_session, make_user


@pytest.fixture()
def farmer(client, registered):
    """已登录用户。"""
    return registered


def _farms(client):
    """取地块清单响应体。"""
    resp = client.get('/api/farms')
    assert resp.status_code == 200
    return resp.get_json()


def test_login_returns_default_farm(client, registered):
    """注册后登录必须自带一块默认地块。"""
    resp = login_session(client, *registered)
    body = resp.get_json()
    assert body['active_farm_id']
    assert len(body['farms']) == 1
    assert body['farms'][0]['id'] == body['active_farm_id']


def test_register_creates_default_farm(client):
    """注册即建一块「默认地块」，名称为空不报错。"""
    resp = client.post('/api/register', json={'username': 'farm01', 'password': 'pass1234'})
    assert resp.get_json()['status'] == 'success'
    login_session(client, 'farm01', 'pass1234')
    body = _farms(client)
    assert body['status'] == 'success'
    assert len(body['farms']) == 1
    assert body['active_id'] == body['farms'][0]['id']


def test_create_and_list_farm(client, farmer):
    """新建地块后清单增加且经纬度保留。"""
    before = _farms(client)['farms']
    resp = client.post('/api/farms', json={
        'name': '北洼试验田', 'lat': 23.1291, 'lon': 113.2644, 'area_m2': 320.5,
    })
    assert resp.status_code == 200
    farm = resp.get_json()['farm']
    assert farm['name'] == '北洼试验田'
    assert abs(farm['lat'] - 23.1291) < 1e-6
    assert farm['area_m2'] == 320.5
    after = _farms(client)['farms']
    assert len(after) == len(before) + 1


def test_switch_farm_updates_active(client, farmer):
    """切换后 active_id 变化，configs 的名称镜像同步。"""
    farm_id = client.post('/api/farms', json={'name': '东三垄', 'lat': 23.1, 'lon': 113.2}
                          ).get_json()['farm']['id']
    resp = client.post('/api/farms/switch', json={'farm_id': farm_id})
    assert resp.status_code == 200
    assert _farms(client)['active_id'] == farm_id

    cfg = client.get('/api/get_config').get_json()
    assert cfg['farm_name'] == '东三垄'
    assert abs(float(cfg['farm_lat']) - 23.1) < 1e-6


def test_switch_clears_telemetry_cache(client, farmer):
    """切地块后实时遥测缓存清空，避免看板串数据。"""
    from qinghe import planner

    uid = _uid(client)
    planner.update_telemetry(uid, waterlevel=1500, humidity=2200, do=6.0, eh=120.0)
    assert planner.build_context(uid)['rori'] is not None

    farm_id = client.post('/api/farms', json={'name': '南坡'}).get_json()['farm']['id']
    client.post('/api/farms/switch', json={'farm_id': farm_id})
    ctx = planner.build_context(uid)
    assert ctx.get('rori') is None


def test_create_farm_rejects_bad_input(client, farmer):
    """名称超长 / 经纬度越界 / 只填一半都要 400。"""
    for payload, _label in (
        ({'name': ''}, '空名称'),
        ({'name': 'x' * 21}, '名称过长'),
        ({'name': '地', 'lat': 123, 'lon': 113}, '纬度越界'),
        ({'name': '地', 'lat': 23, 'lon': 999}, '经度越界'),
        ({'name': '地', 'lat': 23}, '只填纬度'),
        ({'name': '地', 'lat': 'abc', 'lon': 113}, '纬度非数字'),
    ):
        resp = client.post('/api/farms', json=payload)
        assert resp.status_code == 400, payload
        assert resp.get_json()['status'] == 'error'


def test_farm_quota(client, farmer):
    """地图上限来自 config.FARM_MAX_COUNT，超出返回 400。"""
    from qinghe import config

    for index in range(config.FARM_MAX_COUNT - 1):
        resp = client.post('/api/farms', json={'name': '地块%d' % index})
        assert resp.status_code == 200
    resp = client.post('/api/farms', json={'name': '超额地块'})
    assert resp.status_code == 400
    assert '上限' in resp.get_json()['message']


def test_update_farm(client, farmer):
    """改名 / 改坐标 / 改面积都生效。"""
    farm_id = client.post('/api/farms', json={'name': '旧名'}).get_json()['farm']['id']
    resp = client.post('/api/farms/update', json={
        'farm_id': farm_id, 'name': '新名', 'lat': 24.5, 'lon': 114.2, 'area_m2': 800,
    })
    assert resp.status_code == 200
    farm = resp.get_json()['farm']
    assert farm['name'] == '新名'
    assert farm['area_m2'] == 800


def test_save_config_syncs_active_farm_meta(client, farmer):
    """系统设置里改农场名/经纬度，应同步到当前地块记录。"""
    client.post('/api/save_config', json={'farm_name': '西长垄', 'farm_lat': 22.9,
                                          'farm_lng': 113.0})
    active = _farms(client)['active_id']
    farm = [f for f in _farms(client)['farms'] if f['id'] == active][0]
    assert farm['name'] == '西长垄'
    assert abs(farm['lat'] - 22.9) < 1e-6


def test_delete_farm(client, farmer):
    """删除非当前地块成功；最后一块不允许删。"""
    keep = _farms(client)['active_id']
    extra = client.post('/api/farms', json={'name': '待删地块'}).get_json()['farm']['id']
    resp = client.post('/api/farms/delete', json={'farm_id': extra})
    assert resp.status_code == 200
    assert extra not in [f['id'] for f in _farms(client)['farms']]

    resp = client.post('/api/farms/delete', json={'farm_id': keep})
    assert resp.status_code == 400
    assert '至少保留' in resp.get_json()['message']


def test_farm_isolation_between_users(client, farmer):
    """A 用户不能切换/删除/更新 B 用户的地块。"""
    farm_id = client.post('/api/farms', json={'name': 'A 的地'}).get_json()['farm']['id']
    make_user('other02', 'pass1234')
    client.get('/api/logout')
    login_session(client, 'other02', 'pass1234')
    assert client.get('/api/farms').get_json()['farms'][0]['id'] != farm_id
    for path in ('/api/farms/switch', '/api/farms/delete'):
        resp = client.post(path, json={'farm_id': farm_id})
        assert resp.status_code == 400, path
    resp = client.post('/api/farms/update', json={'farm_id': farm_id, 'name': '偷改'})
    assert resp.status_code == 400


def test_farms_require_login(client):
    """未登录一律 401。"""
    assert client.get('/api/farms').status_code == 401
    assert client.post('/api/farms', json={'name': 'x'}).status_code == 401
    assert client.post('/api/farms/switch', json={'farm_id': 1}).status_code == 401


def test_switch_missing_or_unknown_farm(client, farmer):
    """缺 farm_id / 不存在的地块都是 400。"""
    assert client.post('/api/farms/switch', json={}).status_code == 400
    assert client.post('/api/farms/switch', json={'farm_id': 99999}).status_code == 400


def _uid(client):
    """从会话取 uid。"""
    with client.session_transaction() as sess:
        return sess.get('user_id')
