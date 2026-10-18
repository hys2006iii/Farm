"""NF2 运行日志服务端化测试。"""

import queue
import time
from contextlib import closing

import pytest

from qinghe import logbook
from qinghe.db import get_db
import helpers


def _insert_log_row(uid, ts, level='info', source='system', message='测试日志'):
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT INTO logs (user_id, ts, level, source, message)'
            ' VALUES (?, ?, ?, ?, ?)',
            (uid, ts, level, source, message),
        )
        conn.commit()


@pytest.fixture(autouse=True)
def _logbook_isolation(flask_app):
    """每个用例重置队列、丢弃计数、冷却表与建表标记，结束后确保线程停止。"""
    logbook._writer.stop()
    logbook._writer.queue = queue.Queue(maxsize=logbook.QUEUE_MAX)
    logbook._writer.dropped = 0
    logbook._schema_ready = False
    # 重复日志冷却表是进程级全局：本文件大量用例写的是同一条/同形正文，
    # 不清掉会让后一个用例的写入被前一个用例的冷却挡下。
    logbook.reset_recent_logs()
    yield
    try:
        logbook.flush_logs()
    finally:
        logbook._writer.stop()
        logbook.reset_recent_logs()


def test_ensure_schema_idempotent(flask_app):
    """重复建表不报错，只有一张 logs 表与一个 idx_logs_user_ts 索引。"""
    logbook._ensure_schema()
    logbook._ensure_schema()
    with closing(get_db()) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='logs'"
        ).fetchall()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND name='idx_logs_user_ts'"
        ).fetchall()
    assert len(tables) == 1
    assert len(indexes) == 1


def test_add_log_is_nonblocking_and_flush_persists(flask_app):
    """add_log 立即返回，flush_logs 后字段完整落库。"""
    uid = helpers.make_user('alice', 'secret123')
    started = time.monotonic()
    result = logbook.add_log(uid, '水泵启动', 'warning', 'device')
    elapsed = time.monotonic() - started
    assert result is True
    assert elapsed < 0.5

    logbook.flush_logs()
    rows = logbook.query_logs(uid)
    assert len(rows) == 1
    row = rows[0]
    assert row['rid'] == 1
    assert row['level'] == 'warning'
    assert row['source'] == 'device'
    assert row['message'] == '水泵启动'
    assert abs(int(time.time() * 1000) - row['ts']) < 60_000


def test_add_log_nonblocking_when_queue_full(flask_app, monkeypatch):
    """队列满时 add_log 仍立即返回并累计丢弃数，不阻塞调用方。"""
    uid = helpers.make_user('bob', 'secret123')
    original_start = logbook._writer.start
    monkeypatch.setattr(logbook._writer, 'start', lambda: None)
    logbook._writer.queue = queue.Queue(maxsize=5)

    started = time.monotonic()
    for index in range(200):
        logbook.add_log(uid, '事件%d' % index, cooldown=0)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert logbook._writer.queue.qsize() == 5
    assert logbook.dropped_count() == 195

    monkeypatch.setattr(logbook._writer, 'start', original_start)
    logbook.flush_logs()


def test_queue_full_drops_oldest(flask_app, monkeypatch):
    """队列满时丢弃最旧一条，保留最新 N 条并可落库。"""
    uid = helpers.make_user('carol', 'secret123')
    original_start = logbook._writer.start
    monkeypatch.setattr(logbook._writer, 'start', lambda: None)
    logbook._writer.queue = queue.Queue(maxsize=3)

    for index in range(5):
        logbook.add_log(uid, 'msg%d' % index, cooldown=0)
    assert logbook.dropped_count() == 2

    monkeypatch.setattr(logbook._writer, 'start', original_start)
    logbook.flush_logs()
    rows = logbook.query_logs(uid)
    assert len(rows) == 3
    assert {row['message'] for row in rows} == {'msg2', 'msg3', 'msg4'}


def test_query_logs_order_and_limit(flask_app):
    """查询按 ts DESC、rid 从 1 递增，limit 截断生效。"""
    uid = helpers.make_user('dave', 'secret123')
    logbook._ensure_schema()
    base = int(time.time() * 1000) - 10_000
    for index in range(4):
        _insert_log_row(uid, base + index, message='日志%d' % index)

    rows = logbook.query_logs(uid)
    assert [row['message'] for row in rows] == ['日志3', '日志2', '日志1', '日志0']
    assert [row['rid'] for row in rows] == [1, 2, 3, 4]
    assert len(logbook.query_logs(uid, limit=2)) == 2
    assert len(logbook.query_logs(uid, limit=10_000)) == 4


def test_query_logs_since_ts(flask_app):
    """since_ts 只返回更新的日志，用于前端增量轮询。"""
    uid = helpers.make_user('erin', 'secret123')
    logbook._ensure_schema()
    base = int(time.time() * 1000) - 10_000
    _insert_log_row(uid, base, message='旧')
    _insert_log_row(uid, base + 5000, message='新')

    rows = logbook.query_logs(uid, since_ts=base + 1)
    assert [row['message'] for row in rows] == ['新']
    assert [row['message'] for row in logbook.query_logs(uid, since_ts=base + 6000)] == []


def test_prune_logs_returns_deleted_count(flask_app):
    """prune 只删过期日志并返回准确删除行数，幂等。"""
    uid = helpers.make_user('frank', 'secret123')
    logbook._ensure_schema()
    now = int(time.time() * 1000)
    _insert_log_row(uid, now - 10 * 86400000, message='过期一')
    _insert_log_row(uid, now - 8 * 86400000, message='过期二')
    _insert_log_row(uid, now - 1000, message='新鲜')

    assert logbook.prune_logs(keep_days=7) == 2
    assert logbook.prune_logs(keep_days=7) == 0
    assert [row['message'] for row in logbook.query_logs(uid)] == ['新鲜']


def test_add_log_normalizes_fields_and_truncates(flask_app):
    """level/source 非法值回退为 info/system，超长正文截断到 500 字符。"""
    uid = helpers.make_user('grace', 'secret123')
    logbook.add_log(uid, 'x' * 900, 'fatal', 'unknown-source')
    logbook.flush_logs()

    row = logbook.query_logs(uid)[0]
    assert row['level'] == 'info'
    assert row['source'] == 'system'
    assert len(row['message']) == logbook.MESSAGE_MAX_LEN


def test_invalid_uid_is_ignored(flask_app):
    """uid 非法时不写库、不抛异常。"""
    logbook.add_log(0, '无效用户')
    logbook.add_log(-5, '无效用户')
    logbook.add_log('abc', '无效用户')
    logbook.flush_logs()
    with closing(get_db()) as conn:
        count = conn.execute('SELECT COUNT(*) AS c FROM logs').fetchone()['c']
    assert int(count) == 0
    assert logbook.query_logs(0) == []


def test_queue_dropped_count_starts_at_zero(flask_app):
    """新进程 / 新用例的丢弃计数从 0 开始，且单调递增。"""
    uid = helpers.make_user('heidi', 'secret123')
    assert logbook.dropped_count() == 0
    original_start = logbook._writer.start
    logbook._writer.start = lambda: None
    try:
        logbook._writer.queue = queue.Queue(maxsize=2)
        for index in range(4):
            logbook.add_log(uid, 'x%d' % index, cooldown=0)
        assert logbook.dropped_count() == 2
    finally:
        logbook._writer.start = original_start


def test_background_writer_flushes_without_explicit_flush(flask_app):
    """后台守护线程会在 1 秒量级内自动落库，无需调用 flush_logs。"""
    uid = helpers.make_user('ivan', 'secret123')
    logbook.add_log(uid, '自动刷盘', 'info', 'auto')
    deadline = time.monotonic() + 3.0
    rows = []
    while time.monotonic() < deadline:
        rows = logbook.query_logs(uid)
        if rows:
            break
        time.sleep(0.05)
    assert rows and rows[0]['message'] == '自动刷盘'
