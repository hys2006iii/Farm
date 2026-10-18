"""按地块独立的物联网接入配置：地块覆盖、回落账号级、切换生效。

覆盖点：
- farms 表新增 iot_* 列（旧库增量迁移）；
- `save_farm_iot` 只写显式提交的字段，空串=清空（回落账号级）；
- `load_iot_config` 逐字段叠加：地块填了的优先，留空的回落账号级；
- `/api/save_config` 把接入字段同步到当前地块，掩码/未提交字段不动地块；
- `/api/get_config` 返回当前地块生效的接入值；
- 切换地块后生效的接入参数随之改变。
"""

import pytest

from qinghe import config, db


@pytest.fixture()
def uid(flask_app, registered):
    """已注册用户的 id（registered 已登录，这里直接查库拿 id）。"""
    with flask_app.app_context():
        with db.closing(db.get_db()) as conn:
            row = conn.execute(
                'SELECT id FROM users WHERE username=?', (registered[0],)
            ).fetchone()
    assert row, '注册用户应当存在'
    return int(row['id'])


def _save(client, payload):
    """调用 /api/save_config 并断言成功。"""
    resp = client.post('/api/save_config', json=payload)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def test_farms_table_has_iot_columns(flask_app):
    """farms 表必须带上按地块保存的 iot_* 列。"""
    with flask_app.app_context():
        with db.closing(db.get_db()) as conn:
            cols = {r[1] for r in conn.execute('PRAGMA table_info(farms)').fetchall()}
    for col in db.FARM_IOT_COLUMNS:
        assert col in cols, '缺少列 %s' % col


def test_load_iot_config_falls_back_to_account_level(flask_app, uid):
    """地块上没填的字段一律回落账号级配置。"""
    with flask_app.app_context():
        db.save_config(uid, {'iot_host': 'account.example.com', 'iot_client_id': 'acc_cli'})
        merged = db.load_iot_config(uid)
    assert merged['iot_host'] == 'account.example.com'
    assert merged['iot_client_id'] == 'acc_cli'


def test_farm_overrides_account_level(flask_app, uid):
    """地块上填了的字段覆盖账号级，未填的仍回落。"""
    with flask_app.app_context():
        db.save_config(uid, {'iot_host': 'account.example.com', 'iot_client_id': 'acc_cli'})
        farm_id = db.get_active_farm_id(uid)
        assert farm_id
        db.save_farm_iot(uid, farm_id, {'iot_host': 'farm.example.com'})
        merged = db.load_iot_config(uid)
    assert merged['iot_host'] == 'farm.example.com'
    assert merged['iot_client_id'] == 'acc_cli'


def test_save_farm_iot_only_touches_submitted_fields(flask_app, uid):
    """只提交一个字段时，地块上其它字段保持原值。"""
    with flask_app.app_context():
        farm_id = db.get_active_farm_id(uid)
        db.save_farm_iot(uid, farm_id, {'iot_host': 'a.example.com', 'iot_user': 'u1'})
        db.save_farm_iot(uid, farm_id, {'iot_host': 'b.example.com'})
        merged = db.load_iot_config(uid)
    assert merged['iot_host'] == 'b.example.com'
    assert merged['iot_user'] == 'u1'


def test_empty_string_clears_farm_field(flask_app, uid):
    """空串=清空该字段，随后回落账号级。"""
    with flask_app.app_context():
        db.save_config(uid, {'iot_host': 'account.example.com'})
        farm_id = db.get_active_farm_id(uid)
        db.save_farm_iot(uid, farm_id, {'iot_host': 'farm.example.com'})
        assert db.load_iot_config(uid)['iot_host'] == 'farm.example.com'
        db.save_farm_iot(uid, farm_id, {'iot_host': ''})
        merged = db.load_iot_config(uid)
    assert merged['iot_host'] == 'account.example.com'


def test_save_farm_iot_rejects_unknown_farm(flask_app, uid):
    """不存在的 farm_id 返回 False，不抛异常。"""
    with flask_app.app_context():
        assert db.save_farm_iot(uid, 999999, {'iot_host': 'x.example.com'}) is False


def test_save_farm_iot_ignores_non_iot_keys(flask_app, uid):
    """非 iot 字段（如 farm_name）不会写进地块接入列。"""
    with flask_app.app_context():
        farm_id = db.get_active_farm_id(uid)
        assert db.save_farm_iot(uid, farm_id, {'farm_name': '不该写'}) is False


def test_iot_port_zero_means_unset(flask_app, uid):
    """iot_port 用 0 表示未设置；非法值同样按未设置处理。"""
    with flask_app.app_context():
        db.save_config(uid, {'iot_port': 1883})
        farm_id = db.get_active_farm_id(uid)
        db.save_farm_iot(uid, farm_id, {'iot_port': 'not-a-number'})
        assert db.load_iot_config(uid)['iot_port'] == 1883
        db.save_farm_iot(uid, farm_id, {'iot_port': 8883})
        assert db.load_iot_config(uid)['iot_port'] == 8883


def test_switch_farm_changes_effective_iot(flask_app, uid):
    """两块地各配一套接入信息，切换地块后生效值随之改变。"""
    with flask_app.app_context():
        first = db.get_active_farm_id(uid)
        db.save_farm_iot(uid, first, {'iot_host': 'first.example.com'})
        second = db.create_farm(uid, '二号地', None, None, 0.0, '')
        assert second
        db.save_farm_iot(uid, second, {'iot_host': 'second.example.com'})

        assert db.load_iot_config(uid)['iot_host'] == 'first.example.com'
        assert db.set_active_farm(uid, second)
        assert db.load_iot_config(uid)['iot_host'] == 'second.example.com'


def test_save_config_syncs_iot_to_active_farm(client, registered, uid):
    """/api/save_config 把提交的接入字段落到当前地块。"""
    _save(client, {'iot_host': 'farm.example.com', 'iot_client_id': 'cli1'})
    with client.session_transaction() as sess:
        user_id = sess['user_id']
    with db.closing(db.get_db()) as conn:
        row = conn.execute(
            'SELECT iot_host, iot_client_id FROM farms WHERE user_id=? AND id=?',
            (user_id, db.get_active_farm_id(user_id)),
        ).fetchone()
    assert row['iot_host'] == 'farm.example.com'
    assert row['iot_client_id'] == 'cli1'


def test_masked_password_does_not_touch_farm(client, registered, uid):
    """提交掩码占位（前端未改动）时，不覆盖地块上的口令。"""
    _save(client, {'iot_pass': 'secret-pass', 'iot_host': 'h.example.com'})
    with client.session_transaction() as sess:
        user_id = sess['user_id']
    with db.closing(db.get_db()) as conn:
        before = conn.execute(
            'SELECT iot_pass FROM farms WHERE user_id=? AND id=?',
            (user_id, db.get_active_farm_id(user_id)),
        ).fetchone()['iot_pass']
    assert before == 'secret-pass'

    _save(client, {'iot_pass': config.MASK, 'iot_host': 'h2.example.com'})
    with db.closing(db.get_db()) as conn:
        row = conn.execute(
            'SELECT iot_pass, iot_host FROM farms WHERE user_id=? AND id=?',
            (user_id, db.get_active_farm_id(user_id)),
        ).fetchone()
    assert row['iot_pass'] == 'secret-pass', '掩码不应清掉地块口令'
    assert row['iot_host'] == 'h2.example.com'


def test_get_config_returns_farm_effective_values(client, registered, uid):
    """/api/get_config 返回当前地块生效的接入值（地块优先）。"""
    _save(client, {'iot_host': 'farm.example.com'})
    resp = client.get('/api/get_config')
    assert resp.status_code == 200
    assert resp.get_json()['iot_host'] == 'farm.example.com'


def test_get_config_masks_pass_but_keeps_farm_value(client, registered, uid):
    """口令仍以掩码返回，不因按地块读取而泄漏明文。"""
    _save(client, {'iot_pass': 'secret-pass'})
    body = client.get('/api/get_config').get_json()
    assert body['iot_pass'] == config.MASK


def test_save_config_without_iot_keys_keeps_farm_values(client, registered, uid):
    """只改农场名的部分提交不会清掉地块接入信息。"""
    _save(client, {'iot_host': 'keep.example.com'})
    _save(client, {'farm_name': '新名字'})
    with client.session_transaction() as sess:
        user_id = sess['user_id']
    with db.closing(db.get_db()) as conn:
        row = conn.execute(
            'SELECT iot_host FROM farms WHERE user_id=? AND id=?',
            (user_id, db.get_active_farm_id(user_id)),
        ).fetchone()
    assert row['iot_host'] == 'keep.example.com'


def test_iot_config_for_user_without_farm(flask_app, uid):
    """账号没有地块时直接返回账号级配置，不报错。"""
    with flask_app.app_context():
        db.save_config(uid, {'iot_host': 'account.example.com'})
        db.set_active_farm(uid, 0)
        assert db.load_iot_config(uid)['iot_host'] == 'account.example.com'


def test_load_iot_config_missing_user(flask_app):
    """配置行不存在时返回 None。"""
    with flask_app.app_context():
        assert db.load_iot_config(999999) is None

