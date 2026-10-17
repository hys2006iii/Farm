"""`/api/history` 接口测试。

覆盖点：
- 未登录 401（响应体逐字 `{'error': '未授权'}`）；
- 每行含 `ts` / `water_adc` / `soil_adc` / `do_mgl` / `eh_mv` 五个字段，
  键名与旧版三字段完全兼容（新增而非改名）；
- 早期数据（D-01 迁移前的行）DO / Eh 为 `null` 而不是 0 或缺失；
- 按时间升序返回（内部倒序查询后再 reverse）；
- limit clamp 语义：非法值回退默认、超上限截断、下界 1；
- 数据按用户隔离。
"""

import pytest

from helpers import make_user, user_id_of
from qinghe import config, db


def _insert(uid, ts, water_adc, soil_adc, do_mgl=None, eh_mv=None):
    """插入一行历史；do_mgl / eh_mv 省略即模拟迁移前的旧数据。"""
    if do_mgl is None and eh_mv is None:
        db.insert_history_rows([(uid, ts, water_adc, soil_adc)])
    else:
        db.insert_history_rows([(uid, ts, water_adc, soil_adc, do_mgl, eh_mv)])


@pytest.fixture()
def uid(client, registered):
    """当前登录用户 id。"""
    value = user_id_of('farmer01')
    assert value
    return value


def test_history_requires_login(client):
    """未登录访问历史返回 401 且响应体逐字不变。"""
    resp = client.get('/api/history')
    assert resp.status_code == 401
    assert resp.get_json() == {'error': '未授权'}


def test_history_empty_returns_empty_list(client, registered):
    """无数据时返回空列表而不是 null。"""
    resp = client.get('/api/history')
    assert resp.status_code == 200
    assert resp.get_json() == {'data': []}


def test_history_row_field_names(client, registered, uid):
    """每行字段集合逐字等于约定的五个键。"""
    _insert(uid, 1750000000000, 1200, 3000, 4.5, -80.0)
    row = client.get('/api/history').get_json()['data'][0]
    assert set(row) == {'ts', 'water_adc', 'soil_adc', 'do_mgl', 'eh_mv'}


def test_history_returns_do_and_eh_values(client, registered, uid):
    """DO / Eh 返回真实数值而非回退 0。"""
    _insert(uid, 1750000000000, 1200, 3000, 4.5, -80.0)
    row = client.get('/api/history').get_json()['data'][0]
    assert row['do_mgl'] == 4.5
    assert row['eh_mv'] == -80.0


def test_history_legacy_rows_null_do_eh(client, registered, uid):
    """迁移前的旧数据 DO / Eh 为 null（不是 0，也不是键缺失）。"""
    _insert(uid, 1740000000000, 900, 2500)
    row = client.get('/api/history').get_json()['data'][0]
    assert row['do_mgl'] is None
    assert row['eh_mv'] is None


def test_history_mixed_legacy_and_new_rows(client, registered, uid):
    """新旧数据混排时各自保留自己的空值语义。"""
    _insert(uid, 1740000000000, 900, 2500)
    _insert(uid, 1750000000000, 1200, 3000, 6.0, 100.0)
    rows = client.get('/api/history').get_json()['data']
    assert len(rows) == 2
    assert (rows[0]['do_mgl'], rows[0]['eh_mv']) == (None, None)
    assert (rows[1]['do_mgl'], rows[1]['eh_mv']) == (6.0, 100.0)


def test_history_legacy_three_fields_unchanged(client, registered, uid):
    """旧三字段的键名与取值保持不变。"""
    _insert(uid, 1750000000000, 1234, 3456, 5.0, 10.0)
    row = client.get('/api/history').get_json()['data'][0]
    assert row['ts'] == 1750000000000
    assert row['water_adc'] == 1234
    assert row['soil_adc'] == 3456


def test_history_ascending_order(client, registered, uid):
    """按 ts 升序返回。"""
    for offset in (3000, 1000, 2000):
        _insert(uid, 1750000000000 + offset, 100, 200, 1.0, 2.0)
    rows = client.get('/api/history').get_json()['data']
    assert [r['ts'] for r in rows] == [
        1750000000000 + 1000,
        1750000000000 + 2000,
        1750000000000 + 3000,
    ]


@pytest.mark.parametrize('raw', ['abc', '', ' ', 'null', '1.5', '--1'])
def test_history_bad_limit_falls_back_to_default(client, registered, uid, raw):
    """非法 limit 回退默认值（不报 4xx、不 500）。"""
    for index in range(3):
        _insert(uid, 1750000000000 + index, 100, 200, 1.0, 2.0)
    resp = client.get('/api/history?limit=%s' % raw)
    assert resp.status_code == 200
    assert len(resp.get_json()['data']) == 3


def test_history_limit_caps_at_max(client, registered, uid):
    """limit 超上限按 HISTORY_MAX_LIMIT 截断而不是报错。"""
    for index in range(5):
        _insert(uid, 1750000000000 + index, 100, 200, 1.0, 2.0)
    resp = client.get('/api/history?limit=999999')
    assert resp.status_code == 200
    assert len(resp.get_json()['data']) == 5


def test_history_limit_lower_bound_is_one(client, registered, uid):
    """limit=0 / 负数取下界 1，只返回最新一行。"""
    for index in range(4):
        _insert(uid, 1750000000000 + index, 100, 200, 1.0, 2.0)
    for raw in ('0', '-5'):
        rows = client.get('/api/history?limit=%s' % raw).get_json()['data']
        assert len(rows) == config.HISTORY_MIN_LIMIT
        assert rows[0]['ts'] == 1750000000003


def test_history_limit_honored(client, registered, uid):
    """合法 limit 精确生效。"""
    for index in range(6):
        _insert(uid, 1750000000000 + index, 100, 200, 1.0, 2.0)
    rows = client.get('/api/history?limit=2').get_json()['data']
    assert len(rows) == 2


def test_history_isolated_between_users(client, registered, uid):
    """只返回当前用户的数据。"""
    other = make_user('farmer02', 'secret123')
    assert other
    _insert(uid, 1750000000000, 111, 222, 1.0, 2.0)
    _insert(other, 1750000000001, 333, 444, 3.0, 4.0)
    rows = client.get('/api/history').get_json()['data']
    assert [r['water_adc'] for r in rows] == [111]
