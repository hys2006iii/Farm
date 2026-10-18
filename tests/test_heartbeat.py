"""NF3 设备心跳与离线判定测试。"""

import threading
import time
from contextlib import closing

import pytest

from qinghe import alert_center, heartbeat, logbook
from qinghe.db import get_db
import helpers


def _now_ms():
    return int(time.time() * 1000)


def _device_row(uid):
    with closing(get_db()) as conn:
        return conn.execute(
            'SELECT * FROM device_status WHERE user_id = ?', (uid,)
        ).fetchone()


def _logs_of(uid, source='device'):
    logbook.flush_logs()
    return [row for row in logbook.query_logs(uid) if row['source'] == source]


def _join_push_threads(timeout=3.0):
    with alert_center._push_lock:
        threads = list(alert_center._PUSH_THREADS)
        alert_center._PUSH_THREADS.clear()
    for thread in threads:
        thread.join(timeout=timeout)


@pytest.fixture(autouse=True)
def _heartbeat_isolation(flask_app, monkeypatch):
    """快速 webhook 桩、清理冷却状态，并保证巡检线程在用例结束后停止。"""
    monkeypatch.setattr(alert_center.alerts, 'notify_webhook',
                        lambda *args, **kwargs: True)
    alert_center._ensure_schema()
    alert_center._reset_dedupe()
    # 日志/告警的内容冷却表是进程级全局：本文件多个用例写同形正文
    # （「首次心跳」「设备离线」…），不清掉会让后一个用例的写入被前一个挡下。
    logbook.reset_recent_logs()
    yield
    heartbeat.stop_watcher()
    _join_push_threads()
    alert_center._reset_dedupe()
    logbook.reset_recent_logs()


def test_watcher_not_started_by_default(flask_app):
    """导入模块不会自动启动巡检线程，stop_watcher 在未启动时也安全。"""
    names = [thread.name for thread in threading.enumerate()]
    assert 'device-watcher' not in names
    assert heartbeat._watcher is None
    heartbeat.stop_watcher()
    heartbeat.stop_watcher()


def test_mark_seen_then_status_online(flask_app):
    """上报心跳后状态为在线，last_seen_ts 与静默秒数准确。"""
    uid = helpers.make_user('alice', 'secret123')
    seen = _now_ms() - 2000
    heartbeat.mark_seen(uid, seen)

    status = heartbeat.get_status(uid)
    assert status['online'] is True
    assert status['last_seen_ts'] == seen
    assert 2 <= status['silent_seconds'] < 5
    assert set(status) == {'online', 'last_seen_ts', 'silent_seconds'}

    row = _device_row(uid)
    assert row is not None
    assert int(row['online']) == 1
    assert row['last_reason'] == 'heartbeat'


def test_never_seen_device_is_offline(flask_app):
    """从未上报过心跳的设备返回离线且时间为 0。"""
    uid = helpers.make_user('bob', 'secret123')
    assert heartbeat.get_status(uid) == {
        'online': False, 'last_seen_ts': 0, 'silent_seconds': 0,
    }
    assert heartbeat.get_status('abc') == {
        'online': False, 'last_seen_ts': 0, 'silent_seconds': 0,
    }
    assert heartbeat.get_status(0)['online'] is False


def test_silent_seconds_threshold(flask_app):
    """静默超过默认 30 秒即离线，自定义阈值可覆盖判定。"""
    uid = helpers.make_user('carol', 'secret123')
    heartbeat.mark_seen(uid, _now_ms() - 5000)
    fresh = heartbeat.get_status(uid)
    assert fresh['online'] is True
    assert 5 <= fresh['silent_seconds'] < 10

    stale = heartbeat.get_status(uid, offline_seconds=1)
    assert stale['online'] is False
    assert stale['last_seen_ts'] == fresh['last_seen_ts']
    assert fresh['silent_seconds'] <= stale['silent_seconds'] < fresh['silent_seconds'] + 2


def test_mark_seen_clamps_future_timestamp(flask_app):
    """未来时间戳被收敛到当前时间，静默秒数不会为负。"""
    uid = helpers.make_user('dave', 'secret123')
    heartbeat.mark_seen(uid, _now_ms() + 60000)
    status = heartbeat.get_status(uid)
    assert status['online'] is True
    assert status['silent_seconds'] >= 0
    assert status['last_seen_ts'] <= _now_ms()


def test_sweep_offline_returns_only_newly_offline(flask_app):
    """sweep 只返回本次新变离线的用户，重复 sweep 返回空。"""
    alice = helpers.make_user('alice2', 'secret123')
    bob = helpers.make_user('bob2', 'secret123')
    carol = helpers.make_user('carol2', 'secret123')
    heartbeat.mark_seen(alice, _now_ms() - 60000)
    heartbeat.mark_seen(bob, _now_ms() - 1000)
    heartbeat.mark_seen(carol, _now_ms() - 45000)

    first = heartbeat.sweep_offline([alice, bob, carol])
    assert sorted(first) == sorted([alice, carol])
    assert heartbeat.sweep_offline([alice, bob, carol]) == []

    assert heartbeat.get_status(alice)['online'] is False
    assert heartbeat.get_status(carol)['online'] is False
    assert heartbeat.get_status(bob)['online'] is True
    assert int(_device_row(alice)['online']) == 0
    assert _device_row(alice)['last_reason'] == 'silent_timeout'


def test_sweep_offline_ignores_unknown_users(flask_app):
    """从未上报心跳的用户不会被 sweep 判离线，也不产生状态行。"""
    uid = helpers.make_user('frank', 'secret123')
    assert heartbeat.sweep_offline([uid]) == []
    assert _device_row(uid) is None
    assert heartbeat.sweep_offline([]) == []
    assert heartbeat.sweep_offline([0, -1, 'bad']) == []


def test_sweep_offline_emits_log_and_alert(flask_app):
    """设备变离线时写 warning 日志并推送 device_offline 告警。"""
    uid = helpers.make_user('grace', 'secret123')
    heartbeat.mark_seen(uid, _now_ms() - 90000)
    assert heartbeat.sweep_offline([uid]) == [uid]

    logs = _logs_of(uid)
    assert any('离线' in row['message'] and row['level'] == 'warning' for row in logs)
    alerts = alert_center.list_alerts(uid)
    codes = [row['code'] for row in alerts]
    assert 'device_offline' in codes


def test_mark_seen_writes_online_logs(flask_app):
    """首次上线与离线恢复都会写 device 来源 info 日志。"""
    uid = helpers.make_user('heidi', 'secret123')
    heartbeat.mark_seen(uid, _now_ms())
    first_logs = _logs_of(uid)
    assert any('首次' in row['message'] for row in first_logs)

    with closing(get_db()) as conn:
        conn.execute('UPDATE device_status SET online = 0 WHERE user_id = ?', (uid,))
        conn.commit()
    heartbeat.mark_seen(uid, _now_ms())
    second_logs = _logs_of(uid)
    assert len(second_logs) > len(first_logs)
    assert any('恢复' in row['message'] for row in second_logs)


def test_sweep_marks_recovered_online(flask_app):
    """状态行被误标离线但心跳仍新鲜时，sweep 会恢复在线状态。"""
    uid = helpers.make_user('ivan', 'secret123')
    heartbeat.mark_seen(uid, _now_ms())
    with closing(get_db()) as conn:
        conn.execute('UPDATE device_status SET online = 0 WHERE user_id = ?', (uid,))
        conn.commit()

    assert heartbeat.sweep_offline([uid]) == []
    assert int(_device_row(uid)['online']) == 1
    assert heartbeat.get_status(uid)['online'] is True


def test_watcher_start_stop_and_emit(flask_app):
    """巡检线程按周期扫描并通过 emit 上报新离线设备，可干净停止。"""
    uid = helpers.make_user('judy', 'secret123')
    heartbeat.mark_seen(uid, _now_ms() - 60000)
    events = []

    def _emit(user_id, event):
        events.append((user_id, event))

    thread = heartbeat.start_watcher(lambda: [uid], _emit, interval=0.05)
    assert thread.daemon is True
    assert thread.name == 'device-watcher'
    assert heartbeat.start_watcher(lambda: [uid], _emit, interval=0.05) is thread

    deadline = time.monotonic() + 3.0
    while not events and time.monotonic() < deadline:
        time.sleep(0.02)
    heartbeat.stop_watcher()
    assert thread.is_alive() is False

    assert events, '巡检线程应在 3 秒内上报离线事件'
    user_id, event = events[0]
    assert user_id == uid
    assert event['event'] == 'device_offline'
    assert event['online'] is False
    assert event['last_seen_ts'] > 0
    assert event['silent_seconds'] >= 60
    assert event['ts'] > 0
    # 同一设备只上报一次，不会每个周期重复刷屏
    assert [item[0] for item in events].count(uid) == 1


def test_watcher_survives_get_uids_error(flask_app):
    """get_uids 抛异常时巡检线程不退出，后续周期仍可工作。"""

    def _boom():
        raise RuntimeError('数据库忙')

    thread = heartbeat.start_watcher(_boom, lambda uid, event: None, interval=0.05)
    time.sleep(0.2)
    assert thread.is_alive() is True
    heartbeat.stop_watcher()
    assert thread.is_alive() is False


def test_device_status_table_structure(flask_app):
    """device_status 表字段与契约一致，user_id 为主键。"""
    heartbeat._ensure_schema()
    with closing(get_db()) as conn:
        columns = {
            row['name']: row
            for row in conn.execute('PRAGMA table_info(device_status)').fetchall()
        }
    assert set(columns) == {'user_id', 'last_seen_ts', 'online', 'last_reason'}
    assert columns['user_id']['pk'] == 1
    assert columns['last_seen_ts']['notnull'] == 1
    assert columns['online']['notnull'] == 1
    assert columns['online']['dflt_value'] == '0'
