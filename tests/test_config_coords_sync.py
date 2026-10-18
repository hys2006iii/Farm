"""回归测试：清空经纬度必须真正落到 `farms` 表。

背景（D-02 回归）：`/api/save_config` 保存后会把农场名与经纬度镜像到当前地块
记录。`db.save_active_farm_meta()` 的约定是「参数为 None 表示不改动」，而设置页
清空坐标时提交的是空字符串，`_validate_coords()` 把它写成 `''`，再经
`_to_float()` 变成 `None` —— 于是「清空」被当成「不改动」，`farms` 表里旧坐标
原样留着。下次登录 `ensure_default_farm()` 把 farms 镜像回 configs 时，用户
刚清掉的坐标又冒了出来。
"""

import pytest

from helpers import login_session, make_user

FARM_LAT = 23.1291
FARM_LNG = 113.2644


def _active_farm(uid):
    """取当前生效地块记录。"""
    from qinghe import db

    farm = db.ensure_default_farm(uid)
    assert farm is not None
    return farm


@pytest.fixture()
def uid(client, registered):
    """登录后的用户 id。"""
    from helpers import user_id_of

    login_session(client, *registered)
    value = user_id_of(registered[0])
    assert value
    return value


def test_clear_coords_clears_farm_record(client, uid):
    """先设置坐标再清空：farms 表里的坐标必须变成空。"""
    resp = client.post('/api/save_config', json={
        'farm_name': '青禾试验田', 'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG,
    })
    assert resp.status_code == 200
    farm = _active_farm(uid)
    assert farm['lat'] == pytest.approx(FARM_LAT, abs=1e-6)
    assert farm['lon'] == pytest.approx(FARM_LNG, abs=1e-6)

    resp = client.post('/api/save_config', json={'farm_lat': '', 'farm_lng': ''})
    assert resp.status_code == 200
    farm = _active_farm(uid)
    assert farm['lat'] is None, '清空经纬度后 farms 表不应保留旧坐标'
    assert farm['lon'] is None, '清空经纬度后 farms 表不应保留旧坐标'


def test_clear_coords_survives_relogin(client, uid):
    """清空坐标后重新登录，configs 不应被 farms 里的旧坐标镜像回来。"""
    client.post('/api/save_config', json={'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG})
    client.post('/api/save_config', json={'farm_lat': '', 'farm_lng': ''})

    from helpers import login_session as _login
    _login(client, 'farmer01', 'secret123')
    cfg = client.get('/api/get_config').get_json()
    assert not cfg.get('farm_lat'), '重新登录后旧纬度又被镜像回来了'
    assert not cfg.get('farm_lng'), '重新登录后旧经度又被镜像回来了'


def test_missing_coords_keeps_farm_record(client, uid):
    """请求里完全不提坐标时，farms 表的坐标保持不变（不清空）。"""
    client.post('/api/save_config', json={'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG})
    resp = client.post('/api/save_config', json={'farm_name': '改个名字'})
    assert resp.status_code == 200
    farm = _active_farm(uid)
    assert farm['lat'] == pytest.approx(FARM_LAT, abs=1e-6)
    assert farm['lon'] == pytest.approx(FARM_LNG, abs=1e-6)


def test_masked_coords_keep_farm_record(client, uid):
    """掩码占位（前端未改动）不覆盖已有坐标。"""
    from qinghe import config

    client.post('/api/save_config', json={'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG})
    resp = client.post('/api/save_config', json={
        'farm_lat': config.MASK, 'farm_lng': config.MASK,
    })
    assert resp.status_code == 200
    farm = _active_farm(uid)
    assert farm['lat'] == pytest.approx(FARM_LAT, abs=1e-6)
    assert farm['lon'] == pytest.approx(FARM_LNG, abs=1e-6)


def test_clear_coords_only_lat_is_rejected(client, uid):
    """只清一个坐标不构成「成对清空」，另一维仍是旧值则视为成对提交。"""
    client.post('/api/save_config', json={'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG})
    # 只清纬度、保留经度：属于「成对提交」（一个空一个有效），纬度清空
    resp = client.post('/api/save_config', json={'farm_lat': ''})
    assert resp.status_code == 200
    farm = _active_farm(uid)
    assert farm['lat'] is None
    assert farm['lon'] == pytest.approx(FARM_LNG, abs=1e-6)


def test_invalid_coords_rejected_and_record_untouched(client, uid):
    """非法坐标返回 400，且不写脏数据到地块记录。"""
    client.post('/api/save_config', json={'farm_lat': FARM_LAT, 'farm_lng': FARM_LNG})
    resp = client.post('/api/save_config', json={'farm_lat': 999, 'farm_lng': 113.0})
    assert resp.status_code == 400
    farm = _active_farm(uid)
    assert farm['lat'] == pytest.approx(FARM_LAT, abs=1e-6)
    assert farm['lon'] == pytest.approx(FARM_LNG, abs=1e-6)
