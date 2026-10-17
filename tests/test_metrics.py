"""NF5 节水减碳看板的单元测试（运行时长累加、估算口径、逐日序列）。"""

from datetime import date, datetime, timedelta

import pytest

from helpers import execute, fetch_all, user_id_of
from qinghe import db, metrics


@pytest.fixture(autouse=True)
def _fresh_metrics(flask_app, monkeypatch):
    """每个用例重置建表标记与状态缓存，并清掉可能影响口径的环境变量。"""
    metrics._schema_ready = False
    with metrics._last_lock:
        metrics._last.clear()
    monkeypatch.delenv('FARM_CHANNEL_AREA_M2', raising=False)
    monkeypatch.delenv('FARM_CH4_SAVED_G_PER_HOUR', raising=False)
    yield
    metrics._schema_ready = False
    with metrics._last_lock:
        metrics._last.clear()


def _uid(registered):
    """取已登录用户 id。"""
    return user_id_of(registered[0])


def _today_ms(hour=10, minute=0):
    """今天某个整点的毫秒时间戳（本地时区）。"""
    now = datetime.now()
    return int(datetime(now.year, now.month, now.day, hour, minute).timestamp() * 1000)


def _seconds_of(uid, device, day=None):
    """读取某设备某日累计秒数（缺省今天）。"""
    metrics._ensure_schema()
    day = day or date.today().strftime('%Y-%m-%d')
    rows = fetch_all(
        'SELECT seconds FROM pump_runtime WHERE user_id=? AND device=? AND day=?',
        (uid, device, day),
    )
    return rows[0]['seconds'] if rows else 0


def test_note_pump_state_accumulates_each_cycle(client, registered):
    """on→off 一个完整周期累加实际运行秒数。"""
    base = _today_ms()
    uid = _uid(registered)

    metrics.note_pump_state(uid, 'air_pump', 'on', base)
    metrics.note_pump_state(uid, 'air_pump', 'off', base + 120_000)

    assert _seconds_of(uid, 'air_pump') == 120


def test_note_pump_state_dedups_same_state(client, registered):
    """同状态重复上报不重复计时（on/on/off = 120 秒而非 150 秒）。"""
    base = _today_ms()
    uid = _uid(registered)

    metrics.note_pump_state(uid, 'water_pump', 'on', base)
    metrics.note_pump_state(uid, 'water_pump', 'on', base + 30_000)
    metrics.note_pump_state(uid, 'water_pump', 'off', base + 120_000)

    assert _seconds_of(uid, 'water_pump') == 120


def test_note_pump_state_ignores_invalid_input(client, registered):
    """非法设备 / 非法状态直接忽略，不建行也不抛异常。"""
    base = _today_ms()
    uid = _uid(registered)

    metrics.note_pump_state(uid, 'valve', 'on', base)
    metrics.note_pump_state(uid, 'air_pump', 'maybe', base)
    metrics.note_pump_state('not-a-uid', 'air_pump', 'on', base)
    metrics.note_pump_state(uid, 'air_pump', 'off', base + 60_000)

    assert fetch_all('SELECT * FROM pump_runtime WHERE user_id=?', (uid,)) == []


def test_note_pump_state_splits_midnight(client, registered):
    """跨越午夜的运行时长按自然日拆分。"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    start = int(datetime(today.year, today.month, today.day, 23, 59, 0).timestamp() * 1000)
    end = int(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 1, 0).timestamp() * 1000)
    uid = _uid(registered)

    metrics.note_pump_state(uid, 'air_pump', 'on', start)
    metrics.note_pump_state(uid, 'air_pump', 'off', end)

    assert _seconds_of(uid, 'air_pump', today.strftime('%Y-%m-%d')) == 60
    assert _seconds_of(uid, 'air_pump', tomorrow.strftime('%Y-%m-%d')) == 60


def test_estimate_water_liters_manual(client, registered):
    """手算口径：水位抬升 300mm × 0.5 m² → 150 L。"""
    uid = _uid(registered)
    base = _today_ms(8)
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc) VALUES (?,?,?,?)',
            (uid, base, 0, 2000))
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc) VALUES (?,?,?,?)',
            (uid, base + 3_600_000, 4095, 2000))

    result = metrics.estimate(uid, days=1)

    assert result['days'] == 1
    assert result['water_liters'] == pytest.approx(150.0)
    assert result['pump_minutes'] == 0.0
    assert result['air_minutes'] == 0.0


def test_estimate_water_liters_filters_by_farm(client, registered):
    """给出 farm_id 时只统计该地块的用水量，账号级汇总仍包含全部地块。"""
    uid = _uid(registered)
    farm1 = db.get_active_farm_id(uid)
    farm2 = client.post('/api/farms', json={'name': '南坡试验田'}).get_json()['farm']['id']
    base = _today_ms(8)

    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc, farm_id)'
            ' VALUES (?,?,?,?,?)', (uid, base, 0, 2000, farm1))
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc, farm_id)'
            ' VALUES (?,?,?,?,?)', (uid, base + 60_000, 4095, 2000, farm1))
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc, farm_id)'
            ' VALUES (?,?,?,?,?)', (uid, base + 2 * 3_600_000, 0, 2000, farm2))
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc, farm_id)'
            ' VALUES (?,?,?,?,?)', (uid, base + 3 * 3_600_000, 2048, 2000, farm2))

    assert metrics.estimate(uid, days=1)['water_liters'] == pytest.approx(225.0, rel=1e-3)
    assert metrics.estimate(uid, days=1, farm_id=farm1)['water_liters'] == pytest.approx(150.0, rel=1e-3)
    assert metrics.estimate(uid, days=1, farm_id=farm2)['water_liters'] == pytest.approx(75.0, rel=1e-3)


def test_estimate_air_minutes_and_carbon(client, registered):
    """手算口径：气泵 1h → 60min → CH4 0.8g → CO₂e 22.4g；水泵 0.5h → 30min。"""
    uid = _uid(registered)
    base = _today_ms(9)

    metrics.note_pump_state(uid, 'air_pump', 'on', base)
    metrics.note_pump_state(uid, 'air_pump', 'off', base + 3_600_000)
    metrics.note_pump_state(uid, 'water_pump', 'on', base)
    metrics.note_pump_state(uid, 'water_pump', 'off', base + 1_800_000)

    result = metrics.estimate(uid, days=1)

    assert result['air_minutes'] == pytest.approx(60.0)
    assert result['pump_minutes'] == pytest.approx(30.0)
    assert result['ch4_saved_g'] == pytest.approx(0.8)
    assert result['co2e_saved_g'] == pytest.approx(22.4)


def test_estimate_env_overrides(client, registered, monkeypatch):
    """环境变量覆盖渠道面积与减排系数后口径随之变化。"""
    monkeypatch.setenv('FARM_CHANNEL_AREA_M2', '2.0')
    monkeypatch.setenv('FARM_CH4_SAVED_G_PER_HOUR', '1.5')
    uid = _uid(registered)
    base = _today_ms(8)

    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc) VALUES (?,?,?,?)',
            (uid, base, 0, 2000))
    execute('INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc) VALUES (?,?,?,?)',
            (uid, base + 60_000, 4095, 2000))
    metrics.note_pump_state(uid, 'air_pump', 'on', base)
    metrics.note_pump_state(uid, 'air_pump', 'off', base + 3_600_000)

    result = metrics.estimate(uid, days=1)

    assert result['water_liters'] == pytest.approx(600.0)
    assert result['ch4_saved_g'] == pytest.approx(1.5)
    assert result['co2e_saved_g'] == pytest.approx(42.0)
    assert metrics.channel_area_m2() == 2.0
    assert metrics.ch4_saved_g_per_hour() == 1.5


def test_estimate_method_marks_engineering_estimate(client, registered):
    """method 必须明示「工程估算，非实测」。"""
    uid = _uid(registered)
    result = metrics.estimate(uid, days=7)
    assert '工程估算' in result['method']
    assert '非实测' in result['method']


def test_daily_series_shape_and_clamp(client, registered):
    """逐日序列长度、字段齐全、最后一项为今天，days 越界自动收敛。"""
    uid = _uid(registered)
    series = metrics.daily_series(uid, days=5)

    assert len(series) == 5
    assert series[-1]['day'] == date.today().strftime('%Y-%m-%d')
    assert set(series[0]) == {
        'day', 'water_liters', 'pump_minutes', 'air_minutes', 'ch4_saved_g', 'co2e_saved_g',
    }
    assert len(metrics.daily_series(uid, days=0)) == 1
    assert len(metrics.daily_series(uid, days=999)) == metrics.MAX_DAYS


def test_estimate_without_any_data_is_zero(client, registered):
    """无遥测、无运行时长的用户返回全 0，不抛异常。"""
    uid = _uid(registered)
    result = metrics.estimate(uid, days=3)

    assert result['water_liters'] == 0.0
    assert result['pump_minutes'] == 0.0
    assert result['air_minutes'] == 0.0
    assert result['ch4_saved_g'] == 0.0
    assert result['co2e_saved_g'] == 0.0


def test_daily_series_attributes_seconds_to_their_day(client, registered):
    """昨天的运行时长效不串到今天。"""
    uid = _uid(registered)
    yesterday = date.today() - timedelta(days=1)
    start = int(datetime(yesterday.year, yesterday.month, yesterday.day, 10, 0).timestamp() * 1000)
    metrics.note_pump_state(uid, 'air_pump', 'on', start)
    metrics.note_pump_state(uid, 'air_pump', 'off', start + 1_800_000)

    series = metrics.daily_series(uid, days=2)

    assert series[0]['day'] == yesterday.strftime('%Y-%m-%d')
    assert series[0]['air_minutes'] == pytest.approx(30.0)
    assert series[1]['air_minutes'] == 0.0
    assert metrics.estimate(uid, days=2)['air_minutes'] == pytest.approx(30.0)
