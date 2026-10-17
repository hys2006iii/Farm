"""青禾智灌 —— SocketIO 实时通道。

对外事件名与载荷字段与旧版 app.py 逐字一致：
- 下行（服务端→前端）：`hw_data`，载荷 {'type': 'device_status'|'data', ...}
- 上行（前端→服务端）：`send_command`，载荷 {'device': 'water_pump'|'air_pump', 'action': 'on'|'off'}
"""

from flask import session
from flask_socketio import join_room

from qinghe import iot

#: 允许下发的设备白名单，防止任意属性透传
PROP_MAP = {
    'water_pump': 'water_pump',
    'air_pump': 'air_pump',
}


def emit_hw_data(uid, payload) -> None:
    """把一条 `hw_data` 事件推给指定用户房间（str(uid)）。"""
    from qinghe import socketio

    socketio.emit('hw_data', payload, room=str(uid))


def _emit_device_status(uid, event) -> None:
    """把离线巡检事件包装成前端认识的 `hw_data` 载荷推给用户房间。"""
    from qinghe import socketio

    payload = {'type': 'device_status', 'status': 'offline' if not event.get('online') else 'online'}
    for key in ('last_seen_ts', 'silent_seconds', 'ts'):
        if event.get(key) is not None:
            payload[key] = event[key]
    try:
        socketio.emit('hw_data', payload, room=str(uid))
    except Exception:  # noqa: BLE001 - 推送失败不影响巡检线程
        pass


def _device_uids() -> list:
    """读取所有曾上报过心跳的 user_id，供离线巡检使用。"""
    from contextlib import closing

    from qinghe import db

    try:
        with closing(db.get_db()) as conn:
            rows = conn.execute('SELECT user_id FROM device_status').fetchall()
        return [int(row[0]) for row in rows]
    except Exception:  # noqa: BLE001 - 表未建 / 库忙时返回空列表
        return []


def start_device_watcher(interval: float = None):
    """启动设备离线巡检守护线程。

    **只应在进程入口（`app.py` / `server.py` 的 `__main__`）调用一次**，
    不要在应用工厂里调用，否则每个测试用例都会多起一个线程。

    参数:
        interval: 巡检周期（秒），None 用 `heartbeat.WATCH_INTERVAL`。

    返回:
        `heartbeat.start_watcher()` 返回的守护线程（幂等）。
    """
    from qinghe import heartbeat

    if interval is None:
        return heartbeat.start_watcher(_device_uids, _emit_device_status)
    return heartbeat.start_watcher(_device_uids, _emit_device_status, interval=interval)


def register_events(sock) -> None:
    """把 SocketIO 事件注册到给定实例（应用工厂调用）。"""

    @sock.on('connect')
    def on_ws_connect():
        uid = session.get('user_id')
        if not uid:
            return False
        join_room(str(uid))
        iot.connect_huawei_iot(uid)
        # 把当前真实华为云连接状态推给前端：仅 broker 真正握手成功(rc==0)才 online，
        # 没配/没连/握手失败都发 offline，避免前端依赖 SocketIO 自身连上就误标"已连接"
        status = 'online' if iot.is_connected(uid) else 'offline'
        emit_hw_data(uid, {'type': 'device_status', 'status': status})

    @sock.on('send_command')
    def on_ws_command(data):
        uid = session.get('user_id')
        if not uid:
            return
        data = data or {}
        prop = PROP_MAP.get(data.get('device'))
        if not prop:
            return
        action = data.get('action')
        iot.send_property_command(uid, {prop: 'on' if action == 'on' else 'off'})


# 兼容旧调用方式：`socketio` 单例在包初始化时已创建，此处直接注册
def _register_default() -> None:
    """在包单例上注册事件（导入本模块时执行）。"""
    from qinghe import socketio

    if getattr(socketio, '_qinghe_registered', False):
        return
    register_events(socketio)
    try:
        socketio._qinghe_registered = True
    except Exception:
        pass


_register_default()

__all__ = ['emit_hw_data', 'start_device_watcher', 'register_events', 'PROP_MAP']
