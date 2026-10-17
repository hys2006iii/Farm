"""青禾智灌 —— NF3 设备心跳与离线判定。

- `mark_seen()`：记录设备最近一次心跳（毫秒时间戳），首次 / 恢复上线写 device 日志；
- `get_status()`：返回在线状态与静默秒数；
- `sweep_offline()`：批量把静默超时的设备落到离线态，只返回**本次新变离线**的用户；
- `start_watcher()` / `stop_watcher()`：可停止的后台巡检线程，默认不启动。

表 `device_status` 由 `_ensure_schema()` 懒建，不修改 `db.py`；无网络时全部函数正常返回。
"""

import logging
import threading
import time
from contextlib import closing

from qinghe import alert_center, config, logbook
from qinghe.db import get_db

logger = logging.getLogger(__name__)

#: 静默超过该秒数判定离线（契约默认 30 秒，config.py 不新增常量）
DEVICE_OFFLINE_SECONDS = 30

#: 后台巡检线程默认扫描周期（秒）
WATCH_INTERVAL = 5.0

#: 建表一次性标记：记录已建表的数据库路径，临时库切换时重新建表
_schema_ready = False
_schema_path = None
_schema_lock = threading.Lock()

#: 状态读写锁：mark_seen / get_status / sweep_offline 共用
_STATUS_LOCK = threading.RLock()

#: 后台巡检线程与停止信号（默认不启动）
_watcher = None
_watcher_stop = threading.Event()
_watcher_lock = threading.Lock()


def _ensure_schema() -> None:
    """懒建 `device_status` 表（按当前库路径幂等）。"""
    global _schema_ready, _schema_path
    path = config.get_db_path()
    if _schema_ready and _schema_path == path:
        return
    with _schema_lock:
        if _schema_ready and _schema_path == path:
            return
        with closing(get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS device_status (
                    user_id INTEGER PRIMARY KEY,
                    last_seen_ts INTEGER NOT NULL,
                    online INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT DEFAULT ''
                )'''
            )
            conn.commit()
        _schema_path = path
        _schema_ready = True


def _now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


def _as_int(value, default: int) -> int:
    """尽力转 int，失败返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _offline_seconds(offline_seconds=None) -> int:
    """离线阈值：调用方显式传入优先，否则用模块常量。"""
    value = _as_int(offline_seconds, DEVICE_OFFLINE_SECONDS)
    return value if value > 0 else DEVICE_OFFLINE_SECONDS


def _silent_seconds(now: int, last_seen: int) -> int:
    """静默秒数（毫秒差向上取整），避免 30.1 秒被误报成 30 秒在线。"""
    gap = max(0, now - last_seen)
    return (gap + 999) // 1000


def _read_row(user_id: int):
    """读取一行设备状态，不存在返回 None。"""
    with closing(get_db()) as conn:
        return conn.execute(
            'SELECT user_id, last_seen_ts, online, last_reason FROM device_status'
            ' WHERE user_id = ?',
            (user_id,),
        ).fetchone()


def mark_seen(uid: int, ts=None) -> None:
    """记录一次设备心跳。

    `ts` 为毫秒时间戳，缺省取当前时间。首次心跳或从离线恢复时写入一条
    `device` 来源的 info 日志；非法 uid 直接忽略，不抛异常。

    参数:
        uid: 用户 / 设备 id
        ts:  心跳毫秒时间戳，None 表示当前时间
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return
    now = _now_ms()
    seen_ts = _as_int(ts, now) if ts is not None else now
    seen_ts = min(seen_ts, now)
    with _STATUS_LOCK:
        previous = _read_row(user_id)
        was_online = bool(previous and int(previous['online'] or 0))
        with closing(get_db()) as conn:
            conn.execute(
                'INSERT INTO device_status (user_id, last_seen_ts, online, last_reason)'
                ' VALUES (?, ?, 1, ?)'
                ' ON CONFLICT(user_id) DO UPDATE SET'
                ' last_seen_ts = excluded.last_seen_ts,'
                ' online = 1,'
                ' last_reason = excluded.last_reason',
                (user_id, seen_ts, 'heartbeat'),
            )
            conn.commit()
    if not was_online:
        if previous is None:
            message = '设备首次上报心跳，判定在线'
        else:
            message = '设备心跳恢复，重新判定在线'
        logbook.add_log(user_id, message, 'info', 'device')


def get_status(uid: int, offline_seconds=None) -> dict:
    """查询设备在线状态。

    静默秒数 = 当前时间 - 最近心跳；静默超过阈值（默认
    `DEVICE_OFFLINE_SECONDS`）即视为离线。从未上报过的用户返回
    `{'online': False, 'last_seen_ts': 0, 'silent_seconds': 0}`。

    参数:
        uid:             用户 / 设备 id
        offline_seconds: 自定义离线阈值（秒），None 用模块常量
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return {'online': False, 'last_seen_ts': 0, 'silent_seconds': 0}
    threshold = _offline_seconds(offline_seconds)
    with _STATUS_LOCK:
        row = _read_row(user_id)
    if row is None:
        return {'online': False, 'last_seen_ts': 0, 'silent_seconds': 0}
    last_seen = int(row['last_seen_ts'] or 0)
    silent = _silent_seconds(_now_ms(), last_seen)
    return {
        'online': silent <= threshold,
        'last_seen_ts': last_seen,
        'silent_seconds': silent,
    }


def _normalize_uids(uids) -> list[int]:
    """去重并过滤非法 uid，保持首次出现顺序。"""
    result = []
    seen = set()
    for value in uids or []:
        user_id = _as_int(value, -1)
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        result.append(user_id)
    return result


def _emit_offline(uid: int, silent: int) -> None:
    """离线副作用：写 warning 日志 + 推送 device_offline 告警（受冷却去重）。"""
    logbook.add_log(uid, '设备心跳超时（静默 %d 秒），判定离线' % silent, 'warning', 'device')
    try:
        alert_center.push_alert(
            uid, 'warning', 'device_offline',
            '设备已离线，最后心跳 %d 秒前' % silent,
        )
    except Exception:
        logger.warning('离线告警推送失败 uid=%s', uid, exc_info=True)


def sweep_offline(uids: list[int]) -> list[int]:
    """批量检查设备，把静默超时的落为离线态。

    只返回**本次新变离线**的用户 id（已离线或从未上报过的不返回），
    便于调用方只推一次离线事件；对首次发现的离线设备写 warning 日志并
    推送 `device_offline` 告警（告警自带冷却去重）。

    参数:
        uids: 待检查的用户 / 设备 id 列表，允许重复与非法值
    """
    _ensure_schema()
    user_ids = _normalize_uids(uids)
    if not user_ids:
        return []
    now = _now_ms()
    threshold = _offline_seconds(None)
    newly_offline = []
    recovered = []
    with _STATUS_LOCK:
        placeholders = ','.join('?' * len(user_ids))
        with closing(get_db()) as conn:
            rows = conn.execute(
                'SELECT user_id, last_seen_ts, online FROM device_status'
                ' WHERE user_id IN (%s)' % placeholders,
                tuple(user_ids),
            ).fetchall()
            for row in rows:
                user_id = int(row['user_id'])
                last_seen = int(row['last_seen_ts'] or 0)
                was_online = bool(int(row['online'] or 0))
                silent = _silent_seconds(now, last_seen)
                should_online = silent <= threshold
                if was_online and not should_online:
                    conn.execute(
                        'UPDATE device_status SET online = 0, last_reason = ?'
                        ' WHERE user_id = ?',
                        ('silent_timeout', user_id),
                    )
                    newly_offline.append(user_id)
                elif not was_online and should_online:
                    conn.execute(
                        'UPDATE device_status SET online = 1, last_reason = ?'
                        ' WHERE user_id = ?',
                        ('heartbeat', user_id),
                    )
                    recovered.append(user_id)
            conn.commit()
    for user_id in recovered:
        logbook.add_log(user_id, '设备心跳恢复，重新判定在线', 'info', 'device')
    for user_id in newly_offline:
        silent = _silent_seconds(now, _last_seen_of(user_id))
        _emit_offline(user_id, silent)
    return newly_offline


def _last_seen_of(user_id: int) -> int:
    """读最近心跳时间，读不到返回当前时间（避免负数静默秒）。"""
    try:
        row = _read_row(user_id)
        return int(row['last_seen_ts']) if row is not None else _now_ms()
    except Exception:
        return _now_ms()


def _watch_loop(get_uids, emit, interval: float) -> None:
    """巡检线程主体：周期调用 `sweep_offline()`，把新离线设备交给 emit。"""
    while not _watcher_stop.is_set():
        try:
            uids = get_uids() if get_uids is not None else []
            offline = sweep_offline(uids or [])
        except Exception:
            logger.warning('设备离线巡检失败', exc_info=True)
            offline = []
        for user_id in offline:
            status = get_status(user_id)
            event = {
                'event': 'device_offline',
                'online': bool(status['online']),
                'last_seen_ts': int(status['last_seen_ts']),
                'silent_seconds': int(status['silent_seconds']),
                'ts': _now_ms(),
            }
            try:
                if emit is not None:
                    emit(user_id, event)
            except Exception:
                logger.warning('离线事件回调失败 uid=%s', user_id, exc_info=True)
        if _watcher_stop.wait(interval):
            break


def start_watcher(get_uids, emit, interval: float = WATCH_INTERVAL) -> threading.Thread:
    """启动设备离线巡检守护线程（幂等，已在跑则直接返回当前线程）。

    参数:
        get_uids: 无参回调，返回待检查的 uid 列表
        emit:     `emit(uid, event)` 回调，event 含 `event/online/last_seen_ts/
                  silent_seconds/ts`
        interval: 扫描周期（秒），默认 5.0

    返回:
        已启动的守护线程；进程退出前请调用 `stop_watcher()`
    """
    global _watcher
    _ensure_schema()
    with _watcher_lock:
        if _watcher is not None and _watcher.is_alive():
            return _watcher
        try:
            period = float(interval)
        except (TypeError, ValueError):
            period = WATCH_INTERVAL
        period = period if period > 0 else WATCH_INTERVAL
        _watcher_stop.clear()
        _watcher = threading.Thread(
            target=_watch_loop, args=(get_uids, emit, period),
            name='device-watcher', daemon=True,
        )
        _watcher.start()
        return _watcher


def stop_watcher(timeout: float = 2.0) -> None:
    """停止巡检线程并等待退出（幂等，未启动时安全返回）。"""
    global _watcher
    _ensure_schema()
    with _watcher_lock:
        thread = _watcher
        _watcher_stop.set()
    if thread is not None and thread.is_alive():
        try:
            thread.join(timeout=timeout)
        except RuntimeError:
            pass
    with _watcher_lock:
        if _watcher is thread:
            _watcher = None
