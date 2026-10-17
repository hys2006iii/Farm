"""SocketIO 事件契约测试：事件名、房间、设备白名单与指令下发。

不真正建立 WebSocket 连接，直接取出注册在 socketio 单例上的处理函数调用，
并用 monkeypatch 断言副作用（join_room / connect_huawei_iot / send_property_command）。

注：设备离线巡检（heartbeat watcher）的接线测试在 `test_realtime.py`，
本文件专注 `connect` / `send_command` 两个对外事件的契约。
"""

import pytest

from helpers import make_user
from qinghe import iot, realtime


@pytest.fixture()
def events(flask_app):
    """返回 {事件名: 处理函数}。

    Flask-SocketIO 5.x 把用户处理函数包了一层 `_handler(sid, *args)`，并交给
    `_handle_event` 做 `environ` 校验；测试里没有真实 Socket.IO 客户端，
    直接调用包装函数会因 `self.server.get_environ(sid)` 取不到环境而返回
    `('', 400)`，拿不到真实行为。因此这里用 `__wrapped__` 取回**未包装的原始
    处理函数**，只验证我们自己的契约（房间、白名单、指令下发）。
    """
    import qinghe

    handlers = dict(qinghe.socketio.server.handlers.get('/', {}))
    assert 'connect' in handlers and 'send_command' in handlers
    return {name: getattr(fn, '__wrapped__', fn) for name, fn in handlers.items()}


@pytest.fixture()
def uid(flask_app):
    return make_user('wsuser01', 'pw123456')


def _session_ctx(flask_app, uid=None):
    """构造带（或不带）user_id 的请求上下文，供处理函数读取 session。"""
    app = flask_app

    class _Ctx:
        def __enter__(self):
            self.req = app.test_request_context('/')
            self.req.push()
            from flask import session
            if uid is not None:
                session['user_id'] = uid
            return session

        def __exit__(self, *exc):
            self.req.pop()
            return False

    return _Ctx()


def _patch_room_apis(monkeypatch):
    """把依赖真实 Socket.IO 会话的函数换成空实现。

    `join_room` 需要 `flask.request.sid`（由 python-socketio 在真实连接时注入），
    测试上下文里没有，必须替换掉。
    """
    monkeypatch.setattr(realtime, 'join_room', lambda room: None)


# ============================================================
# 事件注册与契约
# ============================================================

def test_both_events_registered(events):
    assert set(events) >= {'connect', 'send_command'}


def test_prop_map_is_whitelist():
    assert realtime.PROP_MAP == {'water_pump': 'water_pump', 'air_pump': 'air_pump'}


def test_register_events_works_on_fresh_socket():
    """在全新 SocketIO 实例上注册不报错，且两个事件都在。"""
    from flask_socketio import SocketIO

    sock = SocketIO()
    realtime.register_events(sock)
    # 未绑定 app 时 SocketIO.on 会把事件暂存在 handlers 列表里
    names = {item[0] for item in sock.handlers}
    assert names >= {'connect', 'send_command'}


# ============================================================
# connect
# ============================================================

def test_connect_without_session_returns_false(flask_app, events):
    with _session_ctx(flask_app, uid=None):
        assert events['connect']() is False


def test_connect_joins_user_room(flask_app, events, uid, monkeypatch):
    joined = []
    monkeypatch.setattr(realtime, 'join_room', lambda room: joined.append(room))
    monkeypatch.setattr(iot, 'connect_huawei_iot', lambda u: False)
    monkeypatch.setattr(realtime, 'emit_hw_data', lambda u, p: None)
    with _session_ctx(flask_app, uid=uid):
        events['connect']()
    assert joined == [str(uid)]


def test_connect_triggers_mqtt_connect(flask_app, events, uid, monkeypatch):
    called = []
    monkeypatch.setattr(realtime, 'join_room', lambda room: None)
    monkeypatch.setattr(iot, 'connect_huawei_iot', lambda u: called.append(u) or False)
    monkeypatch.setattr(realtime, 'emit_hw_data', lambda u, p: None)
    with _session_ctx(flask_app, uid=uid):
        events['connect']()
    assert called == [uid]


def test_connect_emits_offline_when_not_connected(flask_app, events, uid, monkeypatch):
    emitted = []
    monkeypatch.setattr(realtime, 'join_room', lambda room: None)
    monkeypatch.setattr(iot, 'connect_huawei_iot', lambda u: False)
    monkeypatch.setattr(realtime, 'emit_hw_data', lambda u, p: emitted.append((u, p)))
    with _session_ctx(flask_app, uid=uid):
        events['connect']()
    assert emitted == [(uid, {'type': 'device_status', 'status': 'offline'})]


def test_connect_emits_online_when_connected(flask_app, events, uid, monkeypatch):
    emitted = []
    iot.mqtt_clients[uid] = {'client': None, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    monkeypatch.setattr(realtime, 'join_room', lambda room: None)
    monkeypatch.setattr(iot, 'connect_huawei_iot', lambda u: True)
    monkeypatch.setattr(realtime, 'emit_hw_data', lambda u, p: emitted.append(p))
    with _session_ctx(flask_app, uid=uid):
        events['connect']()
    assert emitted == [{'type': 'device_status', 'status': 'online'}]


# ============================================================
# send_command
# ============================================================

def _spy_send(monkeypatch):
    calls = []
    monkeypatch.setattr(iot, 'send_property_command',
                        lambda uid, props: calls.append((uid, props)) or True)
    return calls


@pytest.mark.parametrize('device', ['water_pump', 'air_pump'])
@pytest.mark.parametrize('action,expected', [('on', 'on'), ('off', 'off')])
def test_send_command_allowed_devices(flask_app, events, uid, monkeypatch,
                                      device, action, expected):
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid):
        events['send_command']({'device': device, 'action': action})
    assert calls == [(uid, {device: expected})]


@pytest.mark.parametrize('device', ['light', 'water_pump2', '', None, 0, 'WATER_PUMP'])
def test_send_command_rejects_unknown_device(flask_app, events, uid, monkeypatch, device):
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid):
        events['send_command']({'device': device, 'action': 'on'})
    assert calls == []


def test_send_command_without_session_is_ignored(flask_app, events, monkeypatch):
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=None):
        events['send_command']({'device': 'water_pump', 'action': 'on'})
    assert calls == []


def test_send_command_none_payload_is_ignored(flask_app, events, uid, monkeypatch):
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid):
        events['send_command'](None)
    assert calls == []


def test_send_command_empty_payload_is_ignored(flask_app, events, uid, monkeypatch):
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid):
        events['send_command']({})
    assert calls == []


@pytest.mark.parametrize('action,expected', [
    ('on', 'on'), ('off', 'off'), ('ON', 'off'), ('OFF', 'off'),
    ('toggle', 'off'), (None, 'off'), ('', 'off'), (1, 'off'),
])
def test_send_command_action_normalization(flask_app, events, uid, monkeypatch,
                                           action, expected):
    """只有精确的 'on' 才开泵，其余一律 'off'（与旧版 `'on' if action=='on' else 'off'` 一致）。"""
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid):
        events['send_command']({'device': 'water_pump', 'action': action})
    assert calls == [(uid, {'water_pump': expected})]


def test_send_command_uses_session_uid(flask_app, events, monkeypatch):
    uid_a = make_user('wsa', 'pw123456')
    uid_b = make_user('wsb', 'pw123456')
    calls = _spy_send(monkeypatch)
    with _session_ctx(flask_app, uid=uid_b):
        events['send_command']({'device': 'air_pump', 'action': 'on'})
    assert calls[0][0] == uid_b
    assert calls[0][0] != uid_a


# ============================================================
# emit_hw_data
# ============================================================

def test_emit_hw_data_uses_hw_data_event_and_room(flask_app, monkeypatch, uid):
    captured = {}
    import qinghe

    def fake_emit(event, payload=None, room=None, **kwargs):
        captured.update(event=event, payload=payload, room=room)

    monkeypatch.setattr(qinghe.socketio, 'emit', fake_emit)
    realtime.emit_hw_data(uid, {'type': 'data', 'topic': 'log', 'payload': 'hi'})
    assert captured['event'] == 'hw_data'
    assert captured['room'] == str(uid)
    assert captured['payload'] == {'type': 'data', 'topic': 'log', 'payload': 'hi'}


def test_emit_hw_data_room_is_stringified(flask_app, monkeypatch):
    captured = {}
    import qinghe

    monkeypatch.setattr(qinghe.socketio, 'emit',
                        lambda event, payload=None, room=None, **k: captured.update(room=room))
    realtime.emit_hw_data(42, {'type': 'data'})
    assert captured['room'] == '42'
