"""NF1 服务端告警中心测试。"""

import sqlite3
import time
from contextlib import closing

import pytest

from qinghe import alert_center, config
from qinghe.db import get_db
import helpers


def _insert_alert_row(uid, ts, level='info', code='auto_action',
                      content='测试告警', acked=0):
    with closing(get_db()) as conn:
        cursor = conn.execute(
            'INSERT INTO alerts (user_id, ts, level, code, content, acked)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (uid, ts, level, code, content, acked),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _count_alerts(uid):
    with closing(get_db()) as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS c FROM alerts WHERE user_id = ?', (uid,)
        ).fetchone()
    return int(row['c'])


def _join_push_threads(timeout=3.0):
    with alert_center._push_lock:
        threads = list(alert_center._PUSH_THREADS)
        alert_center._PUSH_THREADS.clear()
    for thread in threads:
        thread.join(timeout=timeout)


@pytest.fixture(autouse=True)
def _alert_isolation(flask_app, monkeypatch):
    """每个用例独立的建表状态、冷却状态与快速 webhook 桩。"""
    alert_center._ensure_schema()
    alert_center._reset_dedupe()
    monkeypatch.setattr(alert_center.alerts, 'notify_webhook',
                        lambda *args, **kwargs: True)
    yield
    _join_push_threads()
    alert_center._reset_dedupe()


def test_ensure_schema_idempotent(flask_app):
    """重复调用 _ensure_schema 不报错，且只建一张 alerts 表与一个索引。"""
    alert_center._ensure_schema()
    alert_center._ensure_schema()
    with closing(get_db()) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND name='idx_alerts_user_ts'"
        ).fetchall()
    assert len(tables) == 1
    assert len(indexes) == 1


def test_push_alert_returns_id_and_persists(flask_app):
    """push_alert 返回自增 id，落库字段完整且默认未确认。"""
    uid = helpers.make_user('alice', 'secret123')
    result = alert_center.push_alert(uid, 'warning', 'soil_low', '  土壤湿度过低  ')
    assert isinstance(result, dict)
    assert result['deduped'] is False
    assert result['pushed'] is True
    assert result['id'] > 0

    rows = alert_center.list_alerts(uid)
    assert len(rows) == 1
    row = rows[0]
    assert row['id'] == result['id']
    assert row['rid'] == 1
    assert row['level'] == 'warning'
    assert row['code'] == 'soil_low'
    assert row['content'] == '土壤湿度过低'
    assert row['acked'] == 0
    assert abs(int(time.time() * 1000) - row['ts']) < 60_000


def test_list_alerts_order_and_since_ts(flask_app):
    """列表按 ts DESC 排序，rid 从 1 递增，since_ts 只返回更新的记录。"""
    uid = helpers.make_user('bob', 'secret123')
    base = int(time.time() * 1000) - 10_000
    _insert_alert_row(uid, base, content='第一条')
    _insert_alert_row(uid, base + 2000, content='第二条')
    _insert_alert_row(uid, base + 4000, content='第三条')

    rows = alert_center.list_alerts(uid)
    assert [row['content'] for row in rows] == ['第三条', '第二条', '第一条']
    assert [row['rid'] for row in rows] == [1, 2, 3]

    newer = alert_center.list_alerts(uid, since_ts=base + 2000)
    assert [row['content'] for row in newer] == ['第三条']


def test_list_alerts_limit_truncation(flask_app):
    """limit 生效且上限被收敛，不会一次返回超量记录。"""
    uid = helpers.make_user('carol', 'secret123')
    base = int(time.time() * 1000) - 10_000
    for index in range(5):
        _insert_alert_row(uid, base + index, content='告警%d' % index)

    assert len(alert_center.list_alerts(uid, limit=2)) == 2
    assert len(alert_center.list_alerts(uid, limit=0)) == 1
    assert len(alert_center.list_alerts(uid, limit=10_000)) == 5
    assert alert_center.list_alerts(uid, limit='bad') != []


def test_push_alert_dedup_cooldown(flask_app, monkeypatch):
    """冷却期内相同 (uid, code, 正文) 只落库一次，冷却过后可再次写入。"""
    uid = helpers.make_user('dave', 'secret123')
    monkeypatch.setattr(config, 'ALERT_COOLDOWN_SECONDS', 60)
    first = alert_center.push_alert(uid, 'warning', 'water_low', '水位过低')
    second = alert_center.push_alert(uid, 'warning', 'water_low', ' 水位过低 ')

    assert first['deduped'] is False
    assert second['deduped'] is True
    assert _count_alerts(uid) == 1

    monkeypatch.setattr(config, 'ALERT_COOLDOWN_SECONDS', 0)
    third = alert_center.push_alert(uid, 'warning', 'water_low', '水位过低')
    assert third['deduped'] is False
    assert _count_alerts(uid) == 2


@pytest.mark.parametrize('field', ['code', 'level', 'content'])
def test_push_alert_dedup_key_components(flask_app, monkeypatch, field):
    """去重键分别包含 code / level 之外的正文与类型码，字段不同则不去重。"""
    uid = helpers.make_user('erin' + field, 'secret123')
    monkeypatch.setattr(config, 'ALERT_COOLDOWN_SECONDS', 60)
    alert_center.push_alert(uid, 'warning', 'soil_high', '土壤湿度过高')
    if field == 'code':
        result = alert_center.push_alert(uid, 'warning', 'water_high', '土壤湿度过高')
    elif field == 'level':
        result = alert_center.push_alert(uid, 'danger', 'soil_high', '土壤湿度过高')
    else:
        result = alert_center.push_alert(uid, 'warning', 'soil_high', '土壤湿度偏高')
    if field == 'level':
        # 契约去重键只含 (uid, code, content)，级别变化不应绕过冷却
        assert result['deduped'] is True
        assert _count_alerts(uid) == 1
    else:
        assert result['deduped'] is False
        assert _count_alerts(uid) == 2


def test_ack_alert_ownership(flask_app):
    """A 用户不能确认 B 用户告警，只能确认自己的，且可重复确认。"""
    alice = helpers.make_user('alice2', 'secret123')
    bob = helpers.make_user('bob2', 'secret123')
    alice_alert = alert_center.push_alert(alice, 'danger', 'rori_high', 'RORI 过高')
    bob_alert = alert_center.push_alert(bob, 'danger', 'rori_high', 'RORI 过高')

    assert alert_center.ack_alert(bob, alice_alert['id']) is False
    assert alert_center.list_alerts(alice)[0]['acked'] == 0

    assert alert_center.ack_alert(alice, alice_alert['id']) is True
    assert alert_center.list_alerts(alice)[0]['acked'] == 1
    assert alert_center.ack_alert(alice, alice_alert['id']) is True
    assert alert_center.list_alerts(bob)[0]['id'] == bob_alert['id']
    assert alert_center.ack_alert(alice, 999999) is False


def test_prune_alerts_returns_deleted_count(flask_app):
    """prune 只删过期告警并返回准确删除行数，重复调用幂等。"""
    uid = helpers.make_user('frank', 'secret123')
    now = int(time.time() * 1000)
    _insert_alert_row(uid, now - 10 * 86400000, content='过期')
    _insert_alert_row(uid, now - 9 * 86400000, content='也过期')
    _insert_alert_row(uid, now - 1000, content='新鲜')

    assert alert_center.prune_alerts(keep_days=7) == 2
    assert alert_center.prune_alerts(keep_days=7) == 0
    assert [row['content'] for row in alert_center.list_alerts(uid)] == ['新鲜']


def test_push_alert_normalizes_and_truncates(flask_app):
    """level/code 归一化，正文截断到 500 字符，非法 uid 不落库。"""
    uid = helpers.make_user('grace', 'secret123')
    result = alert_center.push_alert(uid, 'warn', '', 'x' * 900)
    row = alert_center.list_alerts(uid)[0]
    assert result['id'] == row['id']
    assert row['level'] == 'warning'
    assert row['code'] == 'auto_action'
    assert len(row['content']) == alert_center.CONTENT_MAX_LEN

    assert alert_center.push_alert(0, 'info', 'auto_action', 'bad') == {
        'id': 0, 'deduped': False, 'pushed': False,
    }
    assert alert_center.push_alert('abc', 'info', 'auto_action', 'bad')['id'] == 0
    assert _count_alerts(uid) == 1


def test_push_alert_webhook_retries_then_fails(flask_app, monkeypatch):
    """webhook 失败时按 0.5s/1.0s 退避重试 2 次（共 3 次），最终失败不抛异常。"""
    uid = helpers.make_user('heidi', 'secret123')
    calls = []

    def _always_false(*args, **kwargs):
        calls.append(args)
        return False

    monkeypatch.setattr(alert_center, 'PUSH_RETRY_DELAYS', (0.0, 0.0, 0.0))
    monkeypatch.setattr(alert_center.alerts, 'notify_webhook', _always_false)
    result = alert_center.push_alert(uid, 'danger', 'roli_high', '推送失败')
    _join_push_threads()

    assert result['pushed'] is True
    assert len(calls) == 3
    assert len(alert_center.list_alerts(uid)) == 1


def test_push_alert_webhook_called_asynchronously(flask_app, monkeypatch):
    """命中冷却之外的告警会调度 webhook 推送，标题带上类型中文名。"""
    uid = helpers.make_user('ivan', 'secret123')
    received = []

    def _capture(uid_arg, title, content):
        received.append((uid_arg, title, content))
        return True

    monkeypatch.setattr(alert_center.alerts, 'notify_webhook', _capture)
    alert_center.push_alert(uid, 'warning', 'device_offline', '设备离线')
    _join_push_threads()

    assert len(received) == 1
    assert received[0][0] == uid
    assert '设备离线' in received[0][1]
    assert received[0][2] == '设备离线'


def test_evaluate_and_push_uses_existing_evaluator(flask_app):
    """复用 alerts.evaluate_alerts 判定并只返回真正新增的告警。"""
    uid = helpers.make_user('judy', 'secret123')
    added = alert_center.evaluate_and_push(
        uid, soil_pct=10, water_mm=100, rori=85,
        humi_lower=30, humi_upper=70, water_lower=20, water_upper=200,
    )
    codes = {item['code'] for item in added}
    assert 'soil_low' in codes
    assert 'rori_high' in codes
    assert all(item['deduped'] is False for item in added)
    assert _count_alerts(uid) == len(added)

    again = alert_center.evaluate_and_push(
        uid, soil_pct=10, water_mm=100, rori=85,
        humi_lower=30, humi_upper=70, water_lower=20, water_upper=200,
    )
    assert again == []
    assert _count_alerts(uid) == len(added)


def test_list_alerts_isolated_between_users(flask_app):
    """不同用户的告警互不可见，空用户返回空列表。"""
    alice = helpers.make_user('alice3', 'secret123')
    bob = helpers.make_user('bob3', 'secret123')
    _insert_alert_row(alice, int(time.time() * 1000), content='A 的告警')
    assert alert_center.list_alerts(bob) == []
    assert [row['content'] for row in alert_center.list_alerts(alice)] == ['A 的告警']
    assert alert_center.list_alerts(0) == []


def test_alerts_table_supports_sqlite3_integrity(flask_app):
    """alerts 表结构字段与契约一致，NOT NULL 约束真实生效。"""
    with closing(get_db()) as conn:
        columns = {
            row['name']: row for row in conn.execute('PRAGMA table_info(alerts)').fetchall()
        }
    assert set(columns) == {'id', 'user_id', 'ts', 'level', 'code', 'content', 'acked'}
    assert columns['user_id']['notnull'] == 1
    assert columns['content']['notnull'] == 1
    assert columns['acked']['dflt_value'] == '0'
    with pytest.raises(sqlite3.IntegrityError):
        _insert_alert_row(None, None)
