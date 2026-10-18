"""告警「一键确认全部」测试（NF1 增量）。

值守场景：告警中心一屏可能积压几十条同类提示，逐条点确认既不现实也容易漏掉
真正重要的那条。新增 `POST /api/alerts/ack_all` 与 `alert_center.ack_all_alerts()`。

锁住的契约：
- 只确认自己的告警，不会动到别人的；
- 幂等：没有未确认告警时返回 0 而不是报错；
- 可按类型码过滤（例如只清 `soil_low` 这类持续性提示）；
- 非法 `codes`（非数组 / 数量超限）返回 400；
- 未登录返回 401。
"""

import time
from contextlib import closing

import pytest

from qinghe import alert_center
from qinghe.db import get_db

from helpers import login_session, make_user


def _insert_alert_row(uid, code='soil_low', content='测试告警', acked=0):
    """直接插一条告警行（绕开冷却，便于构造批量场景）。"""
    # alerts 表由 alert_center 懒建，直接插行前必须先建表
    alert_center._ensure_schema()
    with closing(get_db()) as conn:
        cursor = conn.execute(
            'INSERT INTO alerts (user_id, ts, level, code, content, acked)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (uid, int(time.time() * 1000), 'warning', code, content, acked),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _unacked(uid):
    """该用户未确认告警条数。"""
    alert_center._ensure_schema()
    with closing(get_db()) as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS c FROM alerts WHERE user_id = ? AND acked = 0', (uid,)
        ).fetchone()
    return int(row['c'])


@pytest.fixture()
def uid(flask_app):
    """普通用户。"""
    value = make_user('ackall01', 'secret123')
    assert value
    return value


@pytest.fixture()
def other_uid(flask_app):
    """另一个用户，用于隔离性断言。"""
    value = make_user('ackall02', 'secret123')
    assert value
    return value


# ---------------------------------------------------------------- 模型层

def test_ack_all_marks_everything(uid):
    """全部未确认告警被确认，返回条数准确。"""
    for index in range(5):
        _insert_alert_row(uid, content='土壤湿度过低 %d%%' % index)
    assert _unacked(uid) == 5
    assert alert_center.ack_all_alerts(uid) == 5
    assert _unacked(uid) == 0


def test_ack_all_is_idempotent(uid):
    """重复调用返回 0，不报错。"""
    _insert_alert_row(uid)
    assert alert_center.ack_all_alerts(uid) == 1
    assert alert_center.ack_all_alerts(uid) == 0


def test_ack_all_skips_already_acked(uid):
    """已确认的告警不重复计入。"""
    _insert_alert_row(uid, acked=0)
    _insert_alert_row(uid, acked=1)
    assert alert_center.ack_all_alerts(uid) == 1


def test_ack_all_is_per_user(uid, other_uid):
    """只确认自己的告警，别人的不受影响。"""
    _insert_alert_row(uid)
    _insert_alert_row(other_uid)
    assert alert_center.ack_all_alerts(uid) == 1
    assert _unacked(uid) == 0
    assert _unacked(other_uid) == 1, '不应误确认其他用户的告警'


def test_ack_all_filters_by_code(uid):
    """按类型码过滤：只清指定类型，其余保留。"""
    _insert_alert_row(uid, code='soil_low', content='土壤湿度过低')
    _insert_alert_row(uid, code='soil_low', content='土壤湿度过低 2')
    _insert_alert_row(uid, code='rori_high', content='RORI 过高')
    assert alert_center.ack_all_alerts(uid, ['soil_low']) == 2
    remaining = alert_center.list_alerts(uid, limit=50)
    unacked_codes = [row['code'] for row in remaining if not row['acked']]
    assert unacked_codes == ['rori_high']


def test_ack_all_ignores_unknown_codes(uid):
    """类型码全为未知值时返回 0，不会误清其它告警。"""
    _insert_alert_row(uid, code='soil_low')
    assert alert_center.ack_all_alerts(uid, ['不存在的类型']) == 0
    assert _unacked(uid) == 1


def test_ack_all_rejects_invalid_uid():
    """非法 uid 返回 0，不抛异常。"""
    assert alert_center.ack_all_alerts(0) == 0
    assert alert_center.ack_all_alerts('abc') == 0


# ---------------------------------------------------------------- HTTP 接口

def test_api_ack_all_requires_login(client):
    """未登录不能批量确认。"""
    assert client.post('/api/alerts/ack_all', json={}).status_code == 401


def test_api_ack_all_acks_everything(client, registered):
    """登录后一键确认，返回确认条数，列表变全已确认。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    for index in range(3):
        _insert_alert_row(uid, content='水位过高 %d' % index)

    resp = client.post('/api/alerts/ack_all', json={})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success'
    assert body['acked'] == 3

    rows = client.get('/api/alerts?limit=50').get_json()['alerts']
    assert all(row['acked'] for row in rows)


def test_api_ack_all_accepts_codes(client, registered):
    """带 codes 时只确认指定类型。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    _insert_alert_row(uid, code='soil_low')
    _insert_alert_row(uid, code='rori_high', content='RORI 过高')

    resp = client.post('/api/alerts/ack_all', json={'codes': ['rori_high']})
    assert resp.status_code == 200
    assert resp.get_json()['acked'] == 1


@pytest.mark.parametrize('payload', [
    {'codes': 'soil_low'},          # 不是数组
    {'codes': 123},
    {'codes': ['a'] * (len(alert_center.ALERT_CODES) + 1)},   # 数量超限
])
def test_api_ack_all_rejects_bad_codes(client, registered, payload):
    """非法 codes 返回 400 而不是 500。"""
    login_session(client, *registered)
    assert client.post('/api/alerts/ack_all', json=payload).status_code == 400


def test_api_ack_all_tolerates_empty_body(client, registered):
    """空请求体 / 非对象请求体都能工作（等价于确认全部）。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    _insert_alert_row(uid)
    assert client.post('/api/alerts/ack_all').status_code == 200
    assert _unacked(uid) == 0
