"""青禾智灌 —— NF5 节水减碳看板（Metrics）。

职责：
- `note_pump_state()` 记录气泵 / 水泵的开关状态，按「状态切换」累加运行时长到 `pump_runtime`；
- `estimate()` 汇总最近 N 天的灌溉用水量、增氧时长、甲烷减排与 CO₂e 减排；
- `daily_series()` 逐日返回同样的指标，供前端画柱状图。

口径说明（**工程估算，非实测**）：
- 灌溉用水量按水位抬升体积折算：`Σ(Δwater_mm/1000) * 渠道面积(m²) * 1000`；
- 甲烷减排按增氧时长折算：`CH4_SAVED_G_PER_HOUR` 默认 0.8 g/h；
- `co2e = ch4 * 28`（GWP100=28）。

参数化配置（均可用环境变量覆盖，便于现场标定）：
- `FARM_CHANNEL_AREA_M2` 默认 0.5；
- `FARM_CH4_SAVED_G_PER_HOUR` 默认 0.8。
"""

import os
import threading
import time
from contextlib import closing
from datetime import date, datetime, timedelta

from qinghe import db, irrigation

# ============================================================
# 一、常量与模块级状态
# ============================================================

#: 默认渠道/水体面积（m²），可由环境变量 FARM_CHANNEL_AREA_M2 覆盖
DEFAULT_CHANNEL_AREA_M2 = 0.5

#: 默认增氧减排系数（g CH4 / 小时），可由环境变量 FARM_CH4_SAVED_G_PER_HOUR 覆盖
DEFAULT_CH4_SAVED_G_PER_HOUR = 0.8

#: 甲烷全球增温潜势（100 年尺度）
GWP100 = 28

#: 允许的设备名
DEVICES = ('air_pump', 'water_pump')

#: 单次估算的最大回溯天数，避免一次扫全表
MAX_DAYS = 90

#: 状态缓存：{(uid, device): (state, ts_ms)}，状态切换时才结算时长
_last = {}
_last_lock = threading.Lock()

#: 建表一次性标记
_schema_ready = False
_schema_lock = threading.Lock()


def _ensure_schema() -> None:
    """懒建 pump_runtime 表与索引（幂等，每个公开函数入口调用）。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with closing(db.get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS pump_runtime (
                    user_id INTEGER NOT NULL,
                    device TEXT NOT NULL,
                    day TEXT NOT NULL,
                    seconds INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, device, day)
                )'''
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_pump_runtime_user_day ON pump_runtime(user_id, day)'
            )
            conn.commit()
        _schema_ready = True


# ============================================================
# 二、配置与时间工具
# ============================================================


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量，缺失或非法时返回默认值（必须 > 0）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def channel_area_m2() -> float:
    """当前渠道面积（m²）：环境变量 FARM_CHANNEL_AREA_M2 覆盖，默认 0.5。"""
    return _env_float('FARM_CHANNEL_AREA_M2', DEFAULT_CHANNEL_AREA_M2)


def ch4_saved_g_per_hour() -> float:
    """当前增氧减排系数（g/h）：环境变量 FARM_CH4_SAVED_G_PER_HOUR 覆盖，默认 0.8。"""
    return _env_float('FARM_CH4_SAVED_G_PER_HOUR', DEFAULT_CH4_SAVED_G_PER_HOUR)


def _now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(time.time() * 1000)


def _day_of(ts_ms: int) -> str:
    """毫秒时间戳 → 本地时区 'YYYY-MM-DD'。"""
    return datetime.fromtimestamp(int(ts_ms) / 1000.0).strftime('%Y-%m-%d')


def _day_start_ms(day: date) -> int:
    """本地日期 → 当日 00:00 的毫秒时间戳。"""
    return int(datetime(day.year, day.month, day.day).timestamp() * 1000)


def _normalize_state(state):
    """把 on/off/True/False/1/0 归一成 'on' / 'off'，未知返回 None。"""
    if state is None:
        return None
    if isinstance(state, bool):
        return 'on' if state else 'off'
    text = str(state).strip().lower()
    if text in ('1', 'true', 'on', 'open'):
        return 'on'
    if text in ('0', 'false', 'off', 'close'):
        return 'off'
    return None


def _add_seconds(uid: int, device: str, start_ms: int, end_ms: int) -> None:
    """把一段运行时长按本地自然日切分累加进 pump_runtime（不足 1 秒的忽略）。"""
    if end_ms <= start_ms:
        return
    day_start = date.fromtimestamp(start_ms / 1000.0)
    cursor = start_ms
    segments = []
    guard = 0
    while cursor < end_ms and guard < 400:
        guard += 1
        next_midnight = _day_start_ms(day_start + timedelta(days=1))
        segment_end = min(end_ms, next_midnight)
        seconds = int(round((segment_end - cursor) / 1000.0))
        if seconds > 0:
            segments.append((day_start.strftime('%Y-%m-%d'), seconds))
        cursor = segment_end
        day_start = day_start + timedelta(days=1)
    if not segments:
        return
    with closing(db.get_db()) as conn:
        for day, seconds in segments:
            conn.execute(
                '''INSERT INTO pump_runtime (user_id, device, day, seconds) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, device, day) DO UPDATE SET seconds = seconds + excluded.seconds''',
                (int(uid), device, day, int(seconds)),
            )
        conn.commit()


# ============================================================
# 三、运行时长采集
# ============================================================


def note_pump_state(uid: int, device: str, state: str, ts: int = None) -> None:
    """记录一次水泵 / 气泵开关状态（状态去重累加，非法入参直接忽略）。

    只在状态发生切换时结算上一段运行时长：同状态重复上报不会重复计时。
    `ts` 为毫秒时间戳，缺省取当前时间。
    """
    _ensure_schema()
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return
    device = str(device or '').strip().lower()
    if device not in DEVICES:
        return
    normalized = _normalize_state(state)
    if normalized is None:
        return
    if ts is None:
        stamp = _now_ms()
    else:
        try:
            stamp = int(ts)
        except (TypeError, ValueError):
            return
    key = (uid, device)
    with _last_lock:
        previous = _last.get(key)
        if previous is not None and previous[0] == normalized:
            # 同状态重复上报：保留最初的状态起点，不重新计时
            return
        _last[key] = (normalized, stamp)
    if previous is None:
        return
    prev_state, prev_ts = previous
    if prev_state == 'on':
        _add_seconds(uid, device, prev_ts, stamp)


def _runtime_by_day(uid: int, days: list) -> dict:
    """查询指定日期集合内各设备累计秒数：{(device, 'YYYY-MM-DD'): int}。"""
    result = {}
    if not days:
        return result
    placeholders = ','.join('?' for _ in days)
    sql = ('SELECT device, day, COALESCE(SUM(seconds), 0) AS total FROM pump_runtime'
           ' WHERE user_id = ? AND day IN (%s) GROUP BY device, day' % placeholders)
    with closing(db.get_db()) as conn:
        rows = conn.execute(sql, [int(uid)] + list(days)).fetchall()
    for row in rows:
        try:
            device = str(row['device'])
            day = str(row['day'])
            total = int(row['total'] or 0)
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if device in DEVICES:
            result[(device, day)] = result.get((device, day), 0) + total
    return result


def _water_mm_by_day(uid: int, days: list) -> dict:
    """按本地自然日汇总水位抬升量（mm）：只累计正向抬升，回落视为消耗不抵扣。"""
    result = {day: 0.0 for day in days}
    if not days:
        return result
    first_day = date.fromisoformat(days[0])
    start_ms = _day_start_ms(first_day)
    with closing(db.get_db()) as conn:
        baseline = conn.execute(
            'SELECT ts, water_adc FROM sensor_history WHERE user_id = ? AND ts < ?'
            ' ORDER BY ts DESC LIMIT 1',
            (int(uid), start_ms),
        ).fetchone()
        rows = conn.execute(
            'SELECT ts, water_adc FROM sensor_history WHERE user_id = ? AND ts >= ?'
            ' ORDER BY ts ASC',
            (int(uid), start_ms),
        ).fetchall()
    prev_mm = None
    if baseline is not None:
        try:
            prev_mm = float(irrigation.adc_to_water_mm(baseline['water_adc']))
        except (IndexError, KeyError, TypeError, ValueError):
            prev_mm = None
    for row in rows:
        try:
            ts = int(row['ts'])
            current = float(irrigation.adc_to_water_mm(row['water_adc']))
        except (IndexError, KeyError, TypeError, ValueError):
            continue
        if prev_mm is not None:
            delta = current - prev_mm
            if delta > 0:
                day = _day_of(ts)
                if day in result:
                    result[day] += delta
        prev_mm = current
    return result


def _trailing_days(days: int) -> list:
    """返回截至今天的最近 N 个本地自然日（升序 'YYYY-MM-DD'）。"""
    today = date.today()
    return [(today - timedelta(days=offset)).strftime('%Y-%m-%d') for offset in range(days - 1, -1, -1)]


def _clamp_days(days) -> int:
    """把 days 收敛到 1~MAX_DAYS，非法值回落到 7。"""
    try:
        value = int(days)
    except (TypeError, ValueError):
        return 7
    return max(1, min(value, MAX_DAYS))


def _method_text(area: float, ch4_rate: float) -> str:
    """估算口径说明（必须明示「工程估算，非实测」）。"""
    return (
        '工程估算，非实测：灌溉用水量按水位抬升体积折算'
        '（Δwater_mm/1000 × %.2f m² × 1000 L/m³）；增氧减排按增氧时长 × %.2f g/h 折算，'
        'CO₂e = CH4 × %d（GWP100）。' % (area, ch4_rate, GWP100)
    )


# ============================================================
# 四、对外查询
# ============================================================


def daily_series(uid: int, days: int = 7) -> list:
    """逐日返回节水减碳指标（升序，最后一项为今天）。

    每项 `{'day','water_liters','pump_minutes','air_minutes','ch4_saved_g','co2e_saved_g'}`，
    口径为工程估算，非实测；`days` 收敛到 1~90。
    """
    _ensure_schema()
    uid = int(uid)
    days = _clamp_days(days)
    day_keys = _trailing_days(days)
    area = channel_area_m2()
    ch4_rate = ch4_saved_g_per_hour()
    water_map = _water_mm_by_day(uid, day_keys)
    runtime = _runtime_by_day(uid, day_keys)

    series = []
    for day in day_keys:
        water_mm = float(water_map.get(day) or 0.0)
        water_liters = water_mm * area
        air_seconds = int(runtime.get(('air_pump', day)) or 0)
        pump_seconds = int(runtime.get(('water_pump', day)) or 0)
        air_minutes = air_seconds / 60.0
        ch4_saved = air_minutes / 60.0 * ch4_rate
        series.append({
            'day': day,
            'water_liters': round(water_liters, 3),
            'pump_minutes': round(pump_seconds / 60.0, 2),
            'air_minutes': round(air_minutes, 2),
            'ch4_saved_g': round(ch4_saved, 3),
            'co2e_saved_g': round(ch4_saved * GWP100, 3),
        })
    return series


def estimate(uid: int, days: int = 7) -> dict:
    """汇总最近 N 天的节水减碳指标（工程估算，非实测）。

    返回 `{'days','water_liters','pump_minutes','air_minutes','ch4_saved_g',
    'co2e_saved_g','method'}`，`method` 明示估算口径与渠道面积 / 减排系数。
    """
    _ensure_schema()
    days = _clamp_days(days)
    series = daily_series(int(uid), days)
    water_liters = sum(float(item['water_liters']) for item in series)
    pump_minutes = sum(float(item['pump_minutes']) for item in series)
    air_minutes = sum(float(item['air_minutes']) for item in series)
    ch4_saved = sum(float(item['ch4_saved_g']) for item in series)
    return {
        'days': days,
        'water_liters': round(water_liters, 3),
        'pump_minutes': round(pump_minutes, 2),
        'air_minutes': round(air_minutes, 2),
        'ch4_saved_g': round(ch4_saved, 3),
        'co2e_saved_g': round(ch4_saved * GWP100, 3),
        'method': _method_text(channel_area_m2(), ch4_saved_g_per_hour()),
    }
