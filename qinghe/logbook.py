"""青禾智灌 —— NF2 运行日志服务端化。

- `add_log()`：把日志写入模块级有界队列，调用方（MQTT / HTTP 线程）永不阻塞；
  同一 `(用户, 级别, 来源, 正文)` 在冷却窗口内只保留第一条，抑制重复刷屏；
- 后台守护线程每 1.0 秒或积攒 ≥20 条时用 `executemany` 批量落库；
- `flush_logs()`：测试 / 退出时强制刷盘；
- `query_logs()` / `prune_logs()`：按用户分页查询与过期清理。

表 `logs` 与索引 `idx_logs_user_ts` 由 `_ensure_schema()` 懒建，不修改 `db.py`。
"""

import logging
import queue
import re
import threading
import time
from contextlib import closing

from qinghe import config
from qinghe.db import get_db

logger = logging.getLogger(__name__)

#: 日志级别（契约规定）
LOG_LEVELS = ('info', 'warning', 'error')

#: 日志来源（契约规定）
LOG_SOURCES = ('system', 'device', 'auto', 'manual', 'plan', 'config')

#: 队列上限，满则丢弃最旧一条（不阻塞上报线程）
QUEUE_MAX = 1000

#: 单次批量落库条数
BATCH_SIZE = 20

#: 后台线程定期刷盘周期（秒）
FLUSH_INTERVAL = 1.0

#: 单条日志正文最大长度
MESSAGE_MAX_LEN = 500

#: 单次查询最大条数（分页上限）
MAX_LIMIT = 1000

#: 重复日志冷却表的容量上限（超出后按冷却时间清理过期键）
_RECENT_MAX = 2000

#: 建表一次性标记：记录已建表的数据库路径，临时库切换时重新建表
_schema_ready = False
_schema_path = None
_schema_lock = threading.Lock()

#: 所有写入者共用一把库锁，保证 flush_logs() 能看到后台线程的在途写入
_DB_LOCK = threading.Lock()

#: 重复日志冷却表：`(uid, level, source, 正文指纹)` -> 上次放行时间（秒）
_recent_logs = {}
_recent_lock = threading.Lock()


def reset_recent_logs() -> None:
    """清空重复日志冷却表（测试隔离与运行期调参后调用）。"""
    with _recent_lock:
        _recent_logs.clear()


def _ensure_schema() -> None:
    """懒建 `logs` 表与 `idx_logs_user_ts` 索引（按当前库路径幂等）。"""
    global _schema_ready, _schema_path
    path = config.get_db_path()
    if _schema_ready and _schema_path == path:
        return
    with _schema_lock:
        if _schema_ready and _schema_path == path:
            return
        with closing(get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL
                )'''
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_logs_user_ts ON logs(user_id, ts)'
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


def _clamp_limit(limit, default: int = 200) -> int:
    """把 limit 收敛到 [1, MAX_LIMIT]，非法值使用默认值。"""
    value = _as_int(limit, default)
    return max(1, min(value, MAX_LIMIT))


def _normalize_level(level) -> str:
    """归一化日志级别；未知值回退为 `info`。"""
    value = str(level or '').strip().lower()
    return value if value in LOG_LEVELS else 'info'


def _normalize_source(source) -> str:
    """归一化日志来源；未知值回退为 `system`。"""
    value = str(source or '').strip().lower()
    return value if value in LOG_SOURCES else 'system'


def _clip_message(message) -> str:
    """归一化日志正文：去首尾空白并截断到 500 字符。"""
    return str(message or '').strip()[:MESSAGE_MAX_LEN]


def _write_rows(rows) -> int:
    """把一批日志 `executemany` 落库，返回成功条数（失败不向上抛）。"""
    if not rows:
        return 0
    _ensure_schema()
    with _DB_LOCK:
        try:
            with closing(get_db()) as conn:
                conn.executemany(
                    'INSERT INTO logs (user_id, ts, level, source, message)'
                    ' VALUES (?, ?, ?, ?, ?)',
                    rows,
                )
                conn.commit()
            return len(rows)
        except Exception:
            logger.exception('运行日志批量落库失败，丢弃 %d 条', len(rows))
            return 0


class _LogWriter:
    """模块级有界队列 + 单后台守护线程批量落库。

    - `enqueue()` 只做非阻塞入队；队列满时丢弃**最旧**一条并累加 `dropped`；
    - 后台线程每 `flush_interval` 秒或积攒 ≥`batch` 条时 flush；
    - `flush_all()` 供测试 / 退出时强制刷盘。
    """

    def __init__(self, maxsize: int = QUEUE_MAX,
                 flush_interval: float = FLUSH_INTERVAL,
                 batch: int = BATCH_SIZE):
        self.queue = queue.Queue(maxsize=maxsize)
        self.flush_interval = float(flush_interval)
        self.batch = max(1, int(batch))
        self.dropped = 0
        self._stop = threading.Event()
        self._thread = None
        self._state_lock = threading.Lock()

    def enqueue(self, item) -> bool:
        """非阻塞入队；队列满时丢弃最旧一条，返回是否入队成功。"""
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            pass
        try:
            self.queue.get_nowait()
            with self._state_lock:
                self.dropped += 1
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            with self._state_lock:
                self.dropped += 1
            return False

    def _drain(self, limit: int):
        """最多取出 limit 条待写日志。"""
        rows = []
        while len(rows) < limit:
            try:
                rows.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return rows

    def flush_once(self, limit: int = None) -> int:
        """同步刷一批（默认 batch 条），返回写入条数。"""
        size = self.batch if limit is None else max(1, _as_int(limit, self.batch))
        rows = self._drain(size)
        if not rows:
            return 0
        written = _write_rows(rows)
        if written < len(rows):
            for row in rows[written:]:
                self.enqueue(row)
        return written

    def flush_all(self, timeout: float = 2.0) -> int:
        """阻塞把队列中已有日志全部落库，返回写入条数。"""
        self.start()
        try:
            limit = max(0.0, float(timeout))
        except (TypeError, ValueError):
            limit = 2.0
        deadline = time.monotonic() + limit
        total = 0
        while time.monotonic() < deadline:
            rows = self._drain(self.batch)
            if rows:
                written = _write_rows(rows)
                total += written
                if written < len(rows):
                    for row in rows[written:]:
                        self.enqueue(row)
                    break
                continue
            # 队列空时先拿库锁，确保后台线程的在途批次已经提交
            with _DB_LOCK:
                if self.queue.empty():
                    return total
        return total

    def _run(self) -> None:
        """后台线程主循环：定时或攒够 batch 条就刷盘。"""
        while not self._stop.is_set():
            if self.queue.qsize() >= self.batch:
                self.flush_once()
                continue
            if self._stop.wait(self.flush_interval):
                break
            self.flush_once()

    def start(self) -> None:
        """启动后台落库线程（幂等）。"""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name='logbook-writer', daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """停止后台线程并把剩余日志刷盘（退出 / 测试用）。"""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        # 直接清空队列，避免 flush_all 再启动线程
        rows = []
        while True:
            rows.extend(self._drain(self.batch))
            if self.queue.empty():
                break
        total = 0
        while rows:
            total += _write_rows(rows[:self.batch])
            rows = rows[self.batch:]
        return total


#: 全局单例写入器
_writer = _LogWriter()


def _log_key(user_id: int, level: str, source: str, message: str) -> tuple:
    """重复日志的判重键：同用户 + 同级别 + 同来源 + 正文指纹。

    正文先归一化：去掉首尾空白、把连续空白压成一个空格，并抹掉正文里的数字
    （`12.5 mm` 与 `12.6 mm` 视为同一件事）。这样「水位 29.8mm 偏低」连续刷屏
    时只会留一条，而「水位偏低」与「水泵开启」这类不同事实仍各留一条。
    """
    normalized = re.sub(r'\s+', ' ', str(message or '').strip())
    normalized = re.sub(r'\d+(?:\.\d+)?', '#', normalized)
    return (user_id, level, source, normalized[:120])


def _should_log(user_id: int, level: str, source: str, message: str,
                cooldown: float) -> bool:
    """是否应当放行这条日志（冷却期内重复内容返回 False）。

    `cooldown <= 0` 表示关闭去重（测试与需要逐条留痕的场景）。
    """
    if cooldown <= 0:
        return True
    key = _log_key(user_id, level, source, message)
    now = time.monotonic()
    with _recent_lock:
        last = _recent_logs.get(key)
        if last is not None and now - last < cooldown:
            return False
        _recent_logs[key] = now
        # 表本身也要有界，避免长跑进程里键无限增长
        if len(_recent_logs) > _RECENT_MAX:
            for stale in [k for k, ts in _recent_logs.items() if now - ts >= cooldown]:
                _recent_logs.pop(stale, None)
    return True


def reset_recent_logs() -> None:
    """清空重复日志冷却表（测试隔离与运行期调参后调用）。"""
    with _recent_lock:
        _recent_logs.clear()


def add_log(uid: int, message: str, level: str = 'info',
            source: str = 'system', cooldown: float = None) -> bool:
    """非阻塞写入一条运行日志。

    队列满（默认 1000）时丢弃最旧一条并计数，绝不阻塞调用方，也不抛异常。

    **降噪**：`(用户, 级别, 来源, 正文)` 相同的日志在
    `config.LOG_COOLDOWN_SECONDS`（默认 30 秒）内只保留第一条，避免设备抖动
    或自动调控反复触发时极短时间内刷出一屏相同/极其相似的消息。
    需要逐条留痕的调用方可以传 `cooldown=0` 关闭去重。

    返回: 是否真正入队（被冷却挡下返回 False）。
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return False
    level_value = _normalize_level(level)
    source_value = _normalize_source(source)
    text = _clip_message(message)
    window = config.LOG_COOLDOWN_SECONDS if cooldown is None else float(cooldown)
    if not _should_log(user_id, level_value, source_value, text, window):
        return False
    item = (user_id, _now_ms(), level_value, source_value, text)
    _writer.enqueue(item)
    _writer.start()
    return True


def flush_logs(timeout: float = 2.0) -> None:
    """强制把队列中的日志刷入数据库（测试与进程退出时使用）。"""
    _ensure_schema()
    _writer.flush_all(timeout)


def dropped_count() -> int:
    """返回因队列满被丢弃的最旧日志条数（监控与测试用）。"""
    _ensure_schema()
    return int(_writer.dropped)


def query_logs(uid: int, limit: int = 200, since_ts: int = 0) -> list[dict]:
    """按 `ts DESC` 查询用户日志，`rid` 为 1 基序号。

    `since_ts` 为毫秒时间戳，只返回 `ts > since_ts` 的日志；`limit` 会被
    收敛到 `[1, MAX_LIMIT]`，避免一次渲染上千条。
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return []
    count = _clamp_limit(limit, 200)
    since = _as_int(since_ts, 0)
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT ts, level, source, message FROM logs'
            ' WHERE user_id = ? AND ts > ? ORDER BY ts DESC, id DESC LIMIT ?',
            (user_id, since, count),
        ).fetchall()
    return [
        {
            'rid': index + 1,
            'ts': int(row['ts']),
            'level': row['level'],
            'source': row['source'],
            'message': row['message'],
        }
        for index, row in enumerate(rows)
    ]


def prune_logs(keep_days: int = 7) -> int:
    """删除早于 `keep_days` 天的日志，返回删除行数（幂等）。"""
    _ensure_schema()
    days = max(0, _as_int(keep_days, 7))
    cutoff = _now_ms() - days * 86400000
    with closing(get_db()) as conn:
        cursor = conn.execute('DELETE FROM logs WHERE ts < ?', (cutoff,))
        conn.commit()
        return int(cursor.rowcount or 0)
