"""七日灌溉建议（advice）单元测试与接口测试。

纯函数部分不碰数据库；接口部分验证登录、天气缺失降级与 7 天结构。
"""

import pytest

from qinghe import advice

from helpers import login_session


# ---------------------------------------------------------------- 纯函数

def test_build_calendar_returns_seven_days():
    """无论输入几天预报，始终返回 7 天。"""
    days = advice.build_calendar([])
    assert len(days) == 7
    assert days[0]['date'] < days[6]['date']


def test_build_calendar_maps_forecast_precip():
    """有预报时逐日挂上降雨量，无预报的日补 0 并标记 has_forecast=False。"""
    days = advice.build_calendar([0.0, 12.4, 38.0, 5.6])
    assert days[0]['precip'] == 0.0
    assert days[2]['precip'] == 38.0
    assert days[0]['has_forecast'] is True
    assert days[6]['precip'] == 0.0
    assert days[6]['has_forecast'] is False


def test_drought_soil_triggers_irrigate():
    """土壤明显低于动态下限且当日无雨 → 需要灌溉。"""
    days = advice.build_calendar(
        [0.0], soil_pct=30.0, water_mm=150.0,
        thresholds={'humi_down': 45, 'humi_up': 75},
    )
    assert days[0]['level'] == 'irrigate'
    assert '灌水' in days[0]['text']


def test_rain_day_suggests_waiting():
    """预报有效降雨 → 控水等雨。"""
    days = advice.build_calendar(
        [0.0, 30.0], soil_pct=30.0, water_mm=150.0,
        thresholds={'humi_down': 45},
    )
    assert days[1]['level'] == 'wait_rain'
    assert '雨' in days[1]['text']


def test_small_rain_is_watch():
    """1~5 mm 的小雨且墒情接近下限 → 观察待定。"""
    days = advice.build_calendar(
        [2.0], soil_pct=30.0, water_mm=150.0, thresholds={'humi_down': 45},
    )
    assert days[0]['level'] == 'watch'


def test_water_low_triggers_irrigate():
    """水位低于下限 → 建议灌溉（即便土壤读数缺失）。"""
    days = advice.build_calendar(
        [0.0], soil_pct=None, water_mm=20.0,
        thresholds={'waterlevel_down': 30},
    )
    assert days[0]['level'] == 'irrigate'


def test_no_data_is_hold_not_invented():
    """没有任何读数且无雨 → 正常维持，文案里不编造数字。"""
    days = advice.build_calendar([])
    assert days[0]['level'] == 'hold'
    assert '未知' in days[0]['text']


def test_summarize_counts_and_forecast_state():
    """总览文案包含降雨总量与「等雨/灌溉」天数。"""
    days = advice.build_calendar([0.0, 30.0], soil_pct=30.0, water_mm=150.0)
    text = advice.summarize(days, {'P6d': 30.0, 'alpha': 0.95}, True)
    assert '6 日' in text and '等雨' in text
    text = advice.summarize(days, {}, False)
    assert '天气' in text


# ---------------------------------------------------------------- 接口

@pytest.fixture()
def logged_in(client, registered):
    """已登录客户端。"""
    login_session(client, *registered)
    return client


def test_api_requires_login(client):
    """未登录 401。"""
    assert client.get('/api/advice/calendar').status_code == 401


def test_api_returns_seven_days(logged_in):
    """接口返回 7 天与总览，天气缺失时 has_forecast 为 false。"""
    resp = logged_in.get('/api/advice/calendar')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['status'] == 'success'
    assert len(body['days']) == 7
    assert body['has_forecast'] is False
    assert body['summary']


def test_api_uses_live_telemetry(logged_in):
    """接口读取实时遥测换算后的水位与墒情。"""
    from qinghe import planner

    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    planner.update_telemetry(uid, waterlevel=1500, humidity=2200, do=6.0, eh=120.0)
    body = logged_in.get('/api/advice/calendar').get_json()
    assert body['water_mm'] is not None
    assert body['soil_pct'] is not None
    assert 0 <= body['rori'] <= 100


def test_api_marks_forecast_present(logged_in, monkeypatch):
    """有 6 日报雨时 has_forecast 为 true，且带上 P6d/α。"""
    from qinghe import planner

    monkeypatch.setattr(planner, 'forecast_precips',
                        lambda uid: [0.0, 8.0, 20.0, 5.0, 12.0, 3.0])
    body = logged_in.get('/api/advice/calendar').get_json()
    assert body['has_forecast'] is True
    assert body['p6d'] == pytest.approx(29.4, abs=0.05)
    assert body['alpha'] == pytest.approx(0.75, abs=0.01)
