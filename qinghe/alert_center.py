"""青禾智灌 —— NF1 服务端告警中心。

职责：
- `push_alert()`：告警落库 + 冷却去重 + 异步 webhook 推送（失败重试 2 次）；
- `list_alerts()` / `ack_alert()` / `prune_alerts()`：查询、确认与过期清理；
- `evaluate_and_push()`：复用 `alerts.evaluate_alerts()` 判定候选并逐条推送。

表 `alerts` 与索引 `idx_alerts_user_ts` 由 `_ensure_schema()` 懒建，不修改 `db.py`。
所有函数在未配置 webhook / 无网络时也能正常返回，不向调用方抛异常。
"""

import logging
import threading
import time
from contextlib import closing

from qinghe import alerts, config
from qinghe.db import get_db

logger = logging.getLogger(__name__)

#: 告警级别（与前端 info / warning / danger 对齐）
ALERT_LEVELS = ('info', 'warning', 'danger')

#: 契约规定的告警类型码
ALERT_CODES = (
    'soil_low', 'soil_high', 'water_low', 'water_high',
    'rori_medium', 'rori_high', 'device_offline', 'plan_pending', 'auto_action',
)

#: 告警正文最大长度（契约 ≤500 字符）
CONTENT_MAX_LEN = 500

#: 单次查询最大条数（分页上限）
MAX_LIMIT = 500

#: 异步 webhook 重试退避（秒）：首次 + 重试 2 次
PUSH_RETRY_DELAYS = (0.0, 0.5, 1.0)

#: 类型码对应的中文标题（webhook 标题用）
_CODE_TITLES = {
    'soil_low': '土壤湿度过低',
    'soil_high': '土壤湿度过高',
    'water_low': '水位过低',
    'water_high': '水位过高',
    'rori_medium': 'RORI 中度缺氧',
    'rori_high': 'RORI 重度厌氧',
    'device_offline': '设备离线',
    'plan_pending': '预案待确认',
    'auto_action': '自动调控动作',
}

#: 建表一次性标记：记录已建表的数据库路径，临时库切换时重新建表
_schema_ready = False
_schema_path = None
_schema_lock = threading.Lock()

#: 复用既有 AlertDeduper 做进程内冷却（键为 uid|code|正文）
_deduper = alerts.AlertDeduper()
_last_ids = {}
_dedupe_lock = threading.Lock()

#: 后台 webhook 推送线程（测试可 join，避免用例结束时仍有存活线程）
_PUSH_THREADS = []
_push_lock = threading.Lock()


def _ensure_schema() -> None:
    """懒建 `alerts` 表与 `idx_alerts_user_ts` 索引（按当前库路径幂等）。"""
    global _schema_ready, _schema_path
    path = config.get_db_path()
    if _schema_ready and _schema_path == path:
        return
    with _schema_lock:
        if _schema_ready and _schema_path == path:
            return
        with closing(get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    code TEXT NOT NULL,
                    content TEXT NOT NULL,
                    acked INTEGER DEFAULT 0
                )'''
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_alerts_user_ts ON alerts(user_id, ts)'
            )
            conn.commit()
        _schema_path = path
        _schema_ready = True
        _reset_dedupe()


def _reset_dedupe() -> None:
    """清空冷却状态（切换数据库或测试隔离时调用）。"""
    with _dedupe_lock:
        _deduper.reset()
        _last_ids.clear()


def _now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


def _as_int(value, default: int) -> int:
    """尽力转 int，失败返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp_limit(limit, default: int = 100) -> int:
    """把 limit 收敛到 [1, MAX_LIMIT]，非法值使用默认值。"""
    value = _as_int(limit, default)
    return max(1, min(value, MAX_LIMIT))


def _normalize_level(level) -> str:
    """归一化告警级别；`warn`/`danger` 别名与未知值都能安全落库。"""
    value = str(level or '').strip().lower()
    if value == 'warn':
        return 'warning'
    if value in ('critical', 'fatal', 'error'):
        return 'danger'
    return value if value in ALERT_LEVELS else 'info'


def _normalize_code(code) -> str:
    """归一化告警类型码；空值回退为 `auto_action`。"""
    value = str(code or '').strip()
    return value if value else 'auto_action'


def _clip_content(content) -> str:
    """归一化告警正文：去首尾空白并截断到 500 字符。"""
    return str(content or '').strip()[:CONTENT_MAX_LEN]


def _dedupe_key(uid: int, code: str, content: str) -> str:
    """冷却去重键：`(uid, code, content.strip())`。"""
    return '%d|%s|%s' % (uid, code, content)


def _insert_alert(user_id: int, level: str, code: str, content: str) -> int:
    """落库一条告警，返回自增 id；失败时记录日志并返回 0。"""
    try:
        with closing(get_db()) as conn:
            cursor = conn.execute(
                'INSERT INTO alerts (user_id, ts, level, code, content, acked)'
                ' VALUES (?, ?, ?, ?, ?, 0)',
                (user_id, _now_ms(), level, code, content),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)
    except Exception:
        logger.exception('告警落库失败 uid=%s code=%s', user_id, code)
        return 0


def push_alert(uid: int, level: str, code: str, content: str) -> dict:
    """写入一条服务端告警并异步推送 webhook。

    去重键为 `(uid, code, content.strip())`，冷却时间取
    `config.ALERT_COOLDOWN_SECONDS`；冷却期内不落库、不重复推送。
    `pushed` 表示是否已调度异步推送（真实结果由后台线程记录日志）。

    参数:
        uid:     用户 id
        level:   `info` / `warning` / `danger`（`warn` 自动归一为 `warning`）
        code:    告警类型码，见 `ALERT_CODES`
        content: 告警正文，超过 500 字符自动截断

    返回:
        {'id': int, 'deduped': bool, 'pushed': bool}
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return {'id': 0, 'deduped': False, 'pushed': False}
    level_value = _normalize_level(level)
    code_value = _normalize_code(code)
    text = _clip_content(content)
    key = _dedupe_key(user_id, code_value, text)
    # 冷却时间每次从 config 读取，便于运行期调整与测试 monkeypatch
    _deduper.cooldown = float(config.ALERT_COOLDOWN_SECONDS)
    with _dedupe_lock:
        if not _deduper.should_emit(key):
            return {'id': _last_ids.get(key, 0), 'deduped': True, 'pushed': False}
        alert_id = _insert_alert(user_id, level_value, code_value, text)
        if alert_id <= 0:
            return {'id': 0, 'deduped': False, 'pushed': False}
        _last_ids[key] = alert_id
    title = '%s：%s' % (level_value, _CODE_TITLES.get(code_value, code_value))
    thread = threading.Thread(
        target=_push_with_retry, args=(user_id, title, text),
        name='alert-push', daemon=True,
    )
    thread.start()
    with _push_lock:
        # 只保留仍存活的推送线程，避免长跑进程里列表无限增长
        _PUSH_THREADS[:] = [item for item in _PUSH_THREADS if item.is_alive()]
        _PUSH_THREADS.append(thread)
    return {'id': alert_id, 'deduped': False, 'pushed': True}


def _push_with_retry(uid: int, title: str, content: str) -> bool:
    """后台推送 webhook：失败按 0.5s / 1.0s 退避重试 2 次，最终失败仅记录。"""
    for delay in PUSH_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            if alerts.notify_webhook(uid, title, content):
                return True
        except Exception:
            logger.warning('webhook 推送异常 uid=%s', uid, exc_info=True)
    logger.warning('webhook 推送最终失败 uid=%s title=%s', uid, title)
    return False


def list_alerts(uid: int, limit: int = 100, since_ts: int = 0) -> list[dict]:
    """按 `ts DESC` 查询告警，`rid` 为 1 基序号。

    `since_ts` 为毫秒时间戳，只返回 `ts > since_ts` 的告警；`limit` 会被
    收敛到 `[1, MAX_LIMIT]`，用于前端分页与增量轮询。
    """
    _ensure_schema()
    user_id = _as_int(uid, -1)
    if user_id <= 0:
        return []
    count = _clamp_limit(limit, 100)
    since = _as_int(since_ts, 0)
    with closing(get_db()) as conn:
        rows = conn.execute(
            'SELECT id, ts, level, code, content, acked FROM alerts'
            ' WHERE user_id = ? AND ts > ? ORDER BY ts DESC, id DESC LIMIT ?',
            (user_id, since, count),
        ).fetchall()
    return [
        {
            'rid': index + 1,
            'id': int(row['id']),
            'ts': int(row['ts']),
            'level': row['level'],
            'code': row['code'],
            'content': row['content'],
            'acked': int(row['acked'] or 0),
        }
        for index, row in enumerate(rows)
    ]


def ack_alert(uid: int, alert_id: int) -> bool:
    """确认自己的告警；非本人告警、参数非法或不存在时返回 False。"""
    _ensure_schema()
    user_id = _as_int(uid, -1)
    target = _as_int(alert_id, -1)
    if user_id <= 0 or target <= 0:
        return False
    with closing(get_db()) as conn:
        cursor = conn.execute(
            'UPDATE alerts SET acked = 1 WHERE id = ? AND user_id = ?',
            (target, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def prune_alerts(keep_days: int = 7) -> int:
    """删除早于 `keep_days` 天的告警，返回删除行数（幂等）。"""
    _ensure_schema()
    days = max(0, _as_int(keep_days, 7))
    cutoff = _now_ms() - days * 86400000
    with closing(get_db()) as conn:
        cursor = conn.execute('DELETE FROM alerts WHERE ts < ?', (cutoff,))
        conn.commit()
        return int(cursor.rowcount or 0)


def _code_for_message(message: str, level: str) -> str:
    """把告警正文映射为契约告警类型码（**兼容回退路径**）。

    优先由 `evaluate_and_push()` 直接取 `evaluate_alerts()` 结果里的稳定 `code`；
    仅当候选没有 `code`（例如外部自行构造的候选）时才走这里的中文文案前缀匹配。
    文案一旦改写，回退映射会失效，因此新代码应始终传 `code`。
    """
    if message.startswith('土壤湿度过低'):
        return 'soil_low'
    if message.startswith('土壤湿度过高'):
        return 'soil_high'
    if message.startswith('水位过低'):
        return 'water_low'
    if message.startswith('水位过高'):
        return 'water_high'
    if message.startswith('RORI'):
        return 'rori_high' if level == 'danger' else 'rori_medium'
    return 'auto_action'


def _code_of(item: dict, message: str, level: str) -> str:
    """取候选告警的类型码：优先稳定 `code` 字段，缺失才回退文案映射。"""
    code = str(item.get('code') or '').strip()
    if code in ALERT_CODES:
        return code
    return _code_for_message(message, level)


def evaluate_and_push(uid: int, soil_pct, water_mm, rori, humi_lower, humi_upper,
                      water_lower, water_upper) -> list[dict]:
    """按既有 `alerts.evaluate_alerts()` 判定候选并逐条推送。

    `water_lower` 仅为契约签名保留：现有 `evaluate_alerts()` 不产出低水位
    告警，调用方可直接 `push_alert(..., 'water_low', ...)` 产生。

    返回本次真正落库（未被冷却去重）的告警列表，每项含
    `id / level / code / content / deduped / pushed`。
    """
    _ensure_schema()
    candidates = alerts.evaluate_alerts(
        soil_pct, water_mm, humi_lower, humi_upper, water_upper, rori,
    )
    added = []
    for item in candidates or []:
        level = _normalize_level(item.get('level'))
        message = str(item.get('msg') or '')
        code = _code_of(item, message, level)
        result = push_alert(uid, level, code, message)
        if result.get('deduped'):
            continue
        added.append({
            'id': result.get('id', 0),
            'level': level,
            'code': code,
            'content': _clip_content(message),
            'deduped': False,
            'pushed': bool(result.get('pushed')),
        })
    return added
