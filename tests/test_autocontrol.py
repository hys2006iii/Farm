"""NF7 服务端自动调控引擎的单元测试（默认关闭、动作下发、滞回、失败保护）。"""

import json

import pytest

from helpers import execute, fetch_one, user_id_of
from qinghe import autocontrol, iot


@pytest.fixture(autouse=True)
def _fresh_autocontrol(flask_app):
    """每个用例重置模块级建表标记（临时库每个用例都是新的）。"""
    autocontrol._schema_ready = False
    yield
    autocontrol._schema_ready = False


def _uid(registered):
    """取已登录用户 id。"""
    return user_id_of(registered[0])


def _telemetry(water_adc=100, soil_adc=1000, rori=0.0, air='off', pump='off', precips=None):
    """构造一份遥测快照（默认水位偏低、缺氧风险低、设备都关着）。"""
    payload = {
        'water_adc': water_adc,
        'soil_adc': soil_adc,
        'rori': rori,
        'air_pump': air,
        'water_pump': pump,
    }
    if precips is not None:
        payload['precips'] = precips
    return payload


def _patch_send(monkeypatch, ok=True):
    """替换 MQTT 下发，返回记录用的列表。"""
    calls = []

    def fake_send(uid, props):
        calls.append((uid, props))
        return ok

    monkeypatch.setattr(iot, 'send_property_command', fake_send)
    return calls


def test_disabled_by_default_and_never_sends(client, registered, monkeypatch):
    """默认关闭：查库无记录返回 False，evaluate 不产生任何下发。"""
    uid = _uid(registered)
    calls = _patch_send(monkeypatch)

    assert autocontrol.is_enabled(uid) is False
    assert autocontrol.status(uid)['enabled'] is False
    assert autocontrol.evaluate(uid, _telemetry()) == []
    assert calls == []


def test_set_enabled_toggles_single_row(client, registered):
    """开启 / 关闭写入同一行（user_id 主键），状态可回读。"""
    uid = _uid(registered)

    autocontrol.set_enabled(uid, True)
    assert autocontrol.is_enabled(uid) is True
    assert autocontrol.status(uid)['enabled'] is True

    autocontrol.set_enabled(uid, False)
    assert autocontrol.is_enabled(uid) is False

    autocontrol.set_enabled(uid, True)
    rows = fetch_one('SELECT COUNT(*) AS cnt FROM auto_control WHERE user_id=?', (uid,))
    assert rows['cnt'] == 1


def test_evaluate_sends_pump_on_when_water_low(client, registered, monkeypatch):
    """水位低于下限且无降雨时下发水泵开启。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    applied = autocontrol.evaluate(uid, _telemetry(water_adc=100))

    assert [item['device'] for item in applied] == ['water_pump']
    assert applied[0]['action'] == 'on'
    assert calls == [(uid, {'water_pump': 'on'})]
    state = autocontrol.status(uid)['state']
    assert state['water_pump']['state'] == 'on'
    assert autocontrol.status(uid)['last_action_ts'] > 0


def test_evaluate_silent_inside_hysteresis_band(client, registered, monkeypatch):
    """水位处于 [下限, 上限] 区间时水泵待命，不下发。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    applied = autocontrol.evaluate(uid, _telemetry(water_adc=819))

    assert applied == []
    assert calls == []


def test_hysteresis_blocks_repeat_action_within_min_interval(client, registered, monkeypatch):
    """同设备 60 秒内的第二次动作被跳过，时间回拨后放行。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    _patch_send(monkeypatch)

    first = autocontrol.evaluate(uid, _telemetry(water_adc=100))
    assert [item['action'] for item in first] == ['on']

    second = autocontrol.evaluate(uid, _telemetry(water_adc=4095))
    assert second == [], '刚下发过动作，滞回期内不得再次下发'

    row = fetch_one('SELECT state_json FROM auto_control WHERE user_id=?', (uid,))
    state = json.loads(row['state_json'])
    state['water_pump']['ts'] = state['water_pump']['ts'] - 120_000
    execute('UPDATE auto_control SET state_json=? WHERE user_id=?',
            (json.dumps(state, ensure_ascii=False), uid))

    third = autocontrol.evaluate(uid, _telemetry(water_adc=4095))
    assert [item['action'] for item in third] == ['off']
    assert autocontrol.AUTO_MIN_INTERVAL_SECONDS == 60


def test_send_failure_keeps_state_untouched(client, registered, monkeypatch):
    """下发失败时不更新状态，留给下一轮重试。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    _patch_send(monkeypatch, ok=False)

    applied = autocontrol.evaluate(uid, _telemetry(water_adc=100))

    assert applied == []
    assert autocontrol.status(uid)['last_action_ts'] == 0
    assert autocontrol.status(uid)['state'] == {}


def test_rain_forecast_suppresses_pump(client, registered, monkeypatch):
    """有降雨前馈时水泵 hold（不补水），不会下发 water_pump。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    applied = autocontrol.evaluate(uid, _telemetry(water_adc=100, precips=[10, 10, 10]))

    assert all(item['device'] != 'water_pump' for item in applied)
    assert all(props.get('water_pump') is None for _uid_arg, props in calls)


def test_evaluate_tolerates_bad_input(client, registered, monkeypatch):
    """非法 uid / 非 dict 遥测不抛异常，返回空列表。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    assert autocontrol.evaluate(uid, None) == []
    assert autocontrol.evaluate('not-a-uid', _telemetry()) == []
    assert isinstance(autocontrol.evaluate(uid, {}), list)
    assert all(_uid_arg == uid for _uid_arg, _props in calls)


def test_status_shape_and_disable_stops_engine(client, registered, monkeypatch):
    """status 字段齐全；关闭后即使指标越界也不再下发。"""
    uid = _uid(registered)
    autocontrol._ensure_schema()

    empty = autocontrol.status(uid)
    assert set(empty) == {'enabled', 'last_action_ts', 'state'}
    assert empty['enabled'] is False

    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)
    assert autocontrol.evaluate(uid, _telemetry(water_adc=100))
    assert len(calls) == 1

    autocontrol.set_enabled(uid, False)
    assert autocontrol.evaluate(uid, _telemetry(water_adc=100)) == []
    assert len(calls) == 1


def test_unknown_water_quality_never_toggles_air_pump(client, registered, monkeypatch):
    """缺 RORI / 溶解氧 / 氧化还原电位时不碰气泵，但水位越界仍可调水泵。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    telemetry = {'water_adc': 100, 'soil_adc': 1000, 'air_pump': 'on', 'water_pump': 'off'}
    applied = autocontrol.evaluate(uid, telemetry)

    assert [item['device'] for item in applied] == ['water_pump']
    assert all('air_pump' not in props for _uid_arg, props in calls)


def test_rori_computed_from_do_and_eh_turns_air_pump_on(client, registered, monkeypatch):
    """遥测未直接给 RORI 时用溶解氧 + 氧化还原电位现算，重度缺氧开气泵。"""
    uid = _uid(registered)
    autocontrol.set_enabled(uid, True)
    calls = _patch_send(monkeypatch)

    telemetry = _telemetry(water_adc=3000, soil_adc=50, air='off', pump='off')
    telemetry.pop('rori')
    telemetry.update({'do_mgl': 0.5, 'eh_mv': -100})
    applied = autocontrol.evaluate(uid, telemetry)

    assert [item['device'] for item in applied] == ['air_pump']
    assert applied[0]['action'] == 'on'
    assert calls == [(uid, {'air_pump': 'on'})]
