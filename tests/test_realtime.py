"""实时通道与设备离线巡检的接线测试。

覆盖：
- `realtime._device_uids()` 能读到心跳表里的用户 id；
- `realtime._emit_device_status()` 把巡检事件包装成前端认识的 `hw_data` 载荷；
- `realtime.start_device_watcher()` 幂等启动守护线程；
- 巡检线程能把静默超时的设备判为离线并调用 emit。
"""

import time

import pytest

from helpers import make_user
from qinghe import heartbeat, realtime


@pytest.fixture()
def uid(flask_app):
    """一个普通用户。"""
    created = make_user('rt01', 'secret123')
    assert created
    return created


@pytest.fixture()
def sent(monkeypatch):
    """拦截 socketio.emit，收集 (event, payload, room) 三元组。"""
    from qinghe import socketio

    captured = []

    def fake_emit(event, payload=None, room=None, **kwargs):
        captured.append((event, payload, room))

    monkeypatch.setattr(socketio, 'emit', fake_emit)
    return captured


def test_device_uids_lists_heartbeat_rows(uid):
    """心跳表里有记录的用户会被巡检读到。"""
    assert realtime._device_uids() == []
    heartbeat.mark_seen(uid)
    assert realtime._device_uids() == [uid]


def test_emit_device_status_wraps_payload(uid, sent):
    """巡检事件被包装成 type=device_status 的 hw_data 推给用户房间。"""
    realtime._emit_device_status(uid, {
        'event': 'device_offline',
        'online': False,
        'last_seen_ts': 1234567890,
        'silent_seconds': 42,
        'ts': 1234567999,
    })
    assert len(sent) == 1
    event, payload, room = sent[0]
    assert event == 'hw_data'
    assert room == str(uid)
    assert payload['type'] == 'device_status'
    assert payload['status'] == 'offline'
    assert payload['silent_seconds'] == 42
    assert payload['last_seen_ts'] == 1234567890


def test_emit_device_status_marks_online(uid, sent):
    """在线事件包装为 status=online。"""
    realtime._emit_device_status(uid, {'online': True, 'ts': 1})
    assert sent[0][1]['status'] == 'online'


def test_start_device_watcher_is_idempotent_and_detects_offline(uid, sent):
    """巡检线程幂等启动，并能把静默超时的设备判为离线后 emit。"""
    heartbeat.stop_watcher()
    # 造一条 60 秒前的心跳，超过默认 30 秒阈值
    heartbeat.mark_seen(uid, ts=int(time.time() * 1000) - 60_000)
    try:
        first = realtime.start_device_watcher(interval=0.2)
        second = realtime.start_device_watcher(interval=0.2)
        assert first is second
        deadline = time.time() + 5
        while time.time() < deadline and not sent:
            time.sleep(0.05)
        assert sent, '巡检线程未推送离线事件'
        event, payload, room = sent[0]
        assert event == 'hw_data'
        assert room == str(uid)
        assert payload['status'] == 'offline'
        assert heartbeat.get_status(uid)['online'] is False
    finally:
        heartbeat.stop_watcher()
