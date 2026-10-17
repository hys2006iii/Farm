"""灌溉决策纯函数测试：RORI 边界、动态阈值分段、decide_control 滞回。"""

import pytest

from qinghe import config, irrigation as ir


# ============================================================
# 量程换算
# ============================================================

@pytest.mark.parametrize('adc,expected', [
    (0, 0.0),
    (4095, 300.0),
    (2047.5, 150.0),
    (-100, 0.0),
    (9999, 300.0),
    (None, 0.0),
    ('abc', 0.0),
])
def test_adc_to_water_mm(adc, expected):
    assert ir.adc_to_water_mm(adc) == pytest.approx(expected)


@pytest.mark.parametrize('adc,expected', [
    (0, 100.0),
    (4095, 0.0),
    (2047.5, 50.0),
    (-100, 100.0),
    (9999, 0.0),
    (None, 0.0),
])
def test_adc_to_soil_pct(adc, expected):
    assert ir.adc_to_soil_pct(adc) == pytest.approx(expected)


# ============================================================
# 风险因子边界
# ============================================================

@pytest.mark.parametrize('eh,expected', [
    (-150, 1.0),      # 最低电位 -> 最大风险
    (300, 0.0),       # 安全上限 -> 无风险
    (75, 0.5),        # 中点
    (999, 0.0),       # 超上限 clamp 到 0
    (-999, 1.0),      # 超下限 clamp 到 1
])
def test_risk_eh(eh, expected):
    assert ir.risk_eh(eh) == pytest.approx(expected)


@pytest.mark.parametrize('do,expected', [
    (0, 1.0),
    (8.0, 0.0),
    (4.0, 0.5),
    (20.0, 0.0),
])
def test_risk_do(do, expected):
    assert ir.risk_do(do) == pytest.approx(expected)


@pytest.mark.parametrize('water,expected', [
    (0, 0.0),
    (5, 0.0),        # 死区边界
    (5.1, pytest.approx(0.001)),
    (105, 1.0),
    (300, 1.0),
])
def test_risk_water(water, expected):
    assert ir.risk_water(water) == expected


@pytest.mark.parametrize('pct,expected', [(0, 0.0), (50, 0.5), (100, 1.0), (150, 1.0)])
def test_risk_soil(pct, expected):
    assert ir.risk_soil(pct) == pytest.approx(expected)


# ============================================================
# RORI 融合
# ============================================================

def test_rori_ideal_conditions_is_zero():
    """Eh 高、DO 充足、水位低、土壤干 -> RORI 应为 0。"""
    rori = ir.compute_rori(water_adc=0, soil_adc=4095, do_mgl=8.0, eh_mv=300)
    assert rori == pytest.approx(0.0)


def test_rori_worst_case_is_100():
    """全部风险因子拉满 -> RORI 封顶 100。"""
    rori = ir.compute_rori(water_adc=4095, soil_adc=0, do_mgl=0, eh_mv=-150)
    assert rori == pytest.approx(100.0)


def test_rori_is_bounded():
    for water in (0, 2047, 4095):
        for soil in (0, 2047, 4095):
            for do in (0, 4, 8, 20):
                for eh in (-150, 0, 300):
                    rori = ir.compute_rori(water, soil, do, eh)
                    assert 0.0 <= rori <= 100.0


def test_rori_weighted_components():
    """单因子隔离验证权重：只开 SEh，其余无风险。"""
    rori = ir.compute_rori(water_adc=0, soil_adc=4095, do_mgl=8.0, eh_mv=-150)
    assert rori == pytest.approx(config.W_EH * 100.0)


def test_rori_soil_component_weight():
    """只开土壤风险：W_WATER_SOIL * 1.0 = 30。"""
    rori = ir.compute_rori(water_adc=0, soil_adc=0, do_mgl=8.0, eh_mv=300)
    assert rori == pytest.approx(config.W_WATER_SOIL * 100.0)


def test_rori_coupling_penalty_applies():
    """水位与土壤同时高时，耦合项 GAMMA*riskWater*riskSoil 生效。"""
    both = ir.compute_rori(water_adc=4095, soil_adc=0, do_mgl=8.0, eh_mv=300)
    only_soil = ir.compute_rori(water_adc=0, soil_adc=0, do_mgl=8.0, eh_mv=300)
    assert both > only_soil


def test_rori_monotonic_in_water_level():
    prev = -1.0
    for adc in (0, 500, 1000, 2000, 3000, 4095):
        rori = ir.compute_rori(adc, 4095, 8.0, 300)
        assert rori >= prev
        prev = rori


def test_rori_monotonic_in_soil_moisture():
    prev = -1.0
    for adc in (4095, 3000, 2000, 1000, 500, 0):
        rori = ir.compute_rori(0, adc, 8.0, 300)
        assert rori >= prev
        prev = rori


# ============================================================
# RORI 分级（表3-1）
# ============================================================

@pytest.mark.parametrize('rori,code,name', [
    (0, 0, '安全运行'),
    (39.99, 0, '安全运行'),
    (40, 1, '中度缺氧'),
    (69.99, 1, '中度缺氧'),
    (70, 2, '重度厌氧'),
    (100, 2, '重度厌氧'),
])
def test_classify_rori_boundaries(rori, code, name):
    level = ir.classify_rori(rori)
    assert level['code'] == code
    assert level['name'] == name
    assert level['strategy']


def test_classify_rori_strategies_are_distinct():
    strategies = {ir.classify_rori(v)['strategy'] for v in (0, 50, 90)}
    assert len(strategies) == 3


# ============================================================
# 动态阈值（说明书 3.3）
# ============================================================

def test_p6d_uses_decay_weights():
    """P6d = 1.0*10 + 0.9*10 + 0.7*10 + 0.5*10 + 0.4*10 + 0.3*10 = 38。"""
    assert ir.compute_p6d([10] * 6) == pytest.approx(38.0)


def test_p6d_ignores_extra_days():
    assert ir.compute_p6d([1, 1, 1, 1, 1, 1, 100]) == pytest.approx(
        sum(config.RAIN_WEIGHTS))


def test_p6d_handles_bad_values():
    assert ir.compute_p6d([None, 'abc', 10]) == pytest.approx(0.7 * 10)


def test_p6d_empty():
    assert ir.compute_p6d([]) == 0.0
    assert ir.compute_p6d(None) == 0.0


@pytest.mark.parametrize('p6d,alpha', [
    (0, 0.95), (10, 0.95), (10.01, 0.75), (50, 0.75), (50.01, 0.45), (200, 0.45),
])
def test_alpha_segments(p6d, alpha):
    assert ir.alpha_of(p6d) == pytest.approx(alpha)


def test_dynamic_threshold_no_rain():
    """无雨时 P6d=0，但 effLower 仍受 45% 保底约束（与前端公式逐字一致）。"""
    dt = ir.compute_dynamic_threshold(40, 80, [0, 0, 0, 0, 0, 0])
    assert dt['P6d'] == 0.0
    assert dt['alpha'] == pytest.approx(0.95)
    assert dt['effLower'] == pytest.approx(config.EFF_LOWER_FLOOR)   # 40 < 45 -> 被保底抬到 45
    assert dt['effUpper'] == pytest.approx(80.0)
    assert dt['hasForecast'] is True
    assert dt['rainComing'] is False


def test_dynamic_threshold_no_rain_keeps_high_base():
    """基础下限高于保底时，无雨应原样保留。"""
    dt = ir.compute_dynamic_threshold(60, 80, [0] * 6)
    assert dt['effLower'] == pytest.approx(60.0)


def test_dynamic_threshold_lowers_irrigation_trigger():
    """有降雨前馈时应下调灌溉触发下限（相对同基础值无雨情形）。"""
    base = ir.compute_dynamic_threshold(60, 80, [0] * 6)
    dt = ir.compute_dynamic_threshold(60, 80, [10, 10, 10, 10, 10, 10])
    assert dt['P6d'] == pytest.approx(38.0)
    assert dt['alpha'] == pytest.approx(0.75)
    assert dt['effLower'] < base['effLower']
    assert dt['rainComing'] is True


def test_dynamic_threshold_lower_floor_is_45():
    """极端降雨下 effLower 不得低于保底 45%（防枯萎）。"""
    dt = ir.compute_dynamic_threshold(40, 80, [100] * 6)
    assert dt['effLower'] == pytest.approx(config.EFF_LOWER_FLOOR)
    dt_high = ir.compute_dynamic_threshold(90, 95, [100] * 6)
    assert dt_high['effLower'] == pytest.approx(config.EFF_LOWER_FLOOR)


def test_dynamic_threshold_upper_relaxed_on_heavy_rain():
    dt = ir.compute_dynamic_threshold(40, 80, [10] * 6)   # P6d=38 >= 15
    assert dt['effUpper'] == pytest.approx(95.0)


def test_dynamic_threshold_upper_capped_at_100():
    dt = ir.compute_dynamic_threshold(40, 95, [10] * 6)
    assert dt['effUpper'] == pytest.approx(100.0)


def test_dynamic_threshold_light_rain_keeps_upper():
    dt = ir.compute_dynamic_threshold(40, 80, [1, 1, 1, 0, 0, 0])   # P6d=2.6 < 15
    assert dt['effUpper'] == pytest.approx(80.0)
    assert dt['rainComing'] is True


def test_dynamic_threshold_empty_forecast():
    dt = ir.compute_dynamic_threshold(40, 80, [])
    assert dt['hasForecast'] is False
    assert dt['rainComing'] is False
    assert dt['effLower'] == pytest.approx(config.EFF_LOWER_FLOOR)


def test_dynamic_threshold_has_all_frontend_fields():
    dt = ir.compute_dynamic_threshold(40, 80, [5] * 6)
    assert set(dt) == {'P6d', 'alpha', 'effLower', 'effUpper',
                       'baseLower', 'baseUpper', 'hasForecast', 'rainComing'}


# ============================================================
# decide_control：气泵
# ============================================================

TH = {'waterlevel_down': 30, 'waterlevel_up': 150, 'humi_down': 40, 'humi_up': 80}


def test_decide_control_air_off_when_safe():
    out = ir.decide_control(50, 60, rori=10, thresholds=TH, state={'air': 'ON'})
    assert out['air']['state'] == 'OFF'
    assert out['air']['changed'] is True


def test_decide_control_air_on_when_moderate():
    out = ir.decide_control(50, 60, rori=50, thresholds=TH, state={'air': 'OFF'})
    assert out['air']['state'] == 'ON'
    assert out['effective_code'] == 1


def test_decide_control_air_on_when_heavy():
    out = ir.decide_control(50, 60, rori=85, thresholds=TH, state={})
    assert out['air']['state'] == 'ON'
    assert out['effective_code'] == 2


def test_decide_control_air_state_deduped():
    out = ir.decide_control(50, 60, rori=85, thresholds=TH, state={'air': 'ON'})
    assert out['air']['changed'] is False


def test_decide_control_rain_feedforward_upgrades_air():
    """预测有雨时提前一级增氧：RORI<40 也开气泵。"""
    dt = ir.compute_dynamic_threshold(40, 80, [10] * 6)
    out = ir.decide_control(50, 60, rori=10, thresholds=TH, state={}, dt=dt)
    assert out['effective_code'] == 1
    assert out['air']['state'] == 'ON'


def test_decide_control_rain_does_not_downgrade_heavy():
    dt = ir.compute_dynamic_threshold(40, 80, [10] * 6)
    out = ir.decide_control(50, 60, rori=85, thresholds=TH, state={}, dt=dt)
    assert out['effective_code'] == 2


# ============================================================
# decide_control：水泵滞回
# ============================================================

def test_decide_control_pump_on_below_lower():
    out = ir.decide_control(10, 60, rori=0, thresholds=TH, state={'pump': 'ok'})
    assert out['pump']['state'] == 'on'
    assert out['pump']['command'] == 'ON'
    assert out['pump']['changed'] is True


def test_decide_control_pump_off_above_upper():
    out = ir.decide_control(200, 60, rori=0, thresholds=TH, state={'pump': 'on'})
    assert out['pump']['state'] == 'off'
    assert out['pump']['command'] == 'OFF'


def test_decide_control_pump_idle_inside_band():
    out = ir.decide_control(80, 60, rori=0, thresholds=TH, state={'pump': 'on'})
    assert out['pump']['state'] == 'ok'
    assert out['pump']['command'] == ''


def test_decide_control_pump_hysteresis_no_repeat_command():
    """同一水位区间重复判定不得重复下发指令。"""
    first = ir.decide_control(10, 60, rori=0, thresholds=TH, state={'pump': 'ok'})
    assert first['pump']['command'] == 'ON'
    second = ir.decide_control(12, 60, rori=0, thresholds=TH, state={'pump': 'on'})
    assert second['pump']['state'] == 'on'
    assert second['pump']['changed'] is False
    assert second['pump']['command'] == ''


def test_decide_control_pump_hold_on_forecast_rain():
    """水位低于下限但预测有雨 -> hold（控水等雨），不下发开泵。"""
    dt = ir.compute_dynamic_threshold(40, 80, [10] * 6)
    out = ir.decide_control(10, 60, rori=0, thresholds=TH, state={'pump': 'ok'}, dt=dt)
    assert out['pump']['state'] == 'hold'
    assert out['pump']['command'] == ''


def test_decide_control_pump_hold_reason_mentions_p6d():
    dt = ir.compute_dynamic_threshold(40, 80, [10] * 6)
    out = ir.decide_control(10, 60, rori=0, thresholds=TH, state={}, dt=dt)
    assert 'P6d' in out['pump']['reason']


def test_decide_control_boundary_at_upper_is_idle():
    out = ir.decide_control(150, 60, rori=0, thresholds=TH, state={})
    assert out['pump']['state'] == 'ok'


def test_decide_control_boundary_below_lower_triggers():
    out = ir.decide_control(29.9, 60, rori=0, thresholds=TH, state={})
    assert out['pump']['state'] == 'on'


def test_decide_control_returns_all_keys():
    out = ir.decide_control(50, 60, rori=30, thresholds=TH)
    assert set(out) == {'air', 'pump', 'rori', 'level', 'effective_code'}
    assert set(out['air']) == {'state', 'changed', 'reason'}
    assert set(out['pump']) == {'state', 'command', 'changed', 'reason'}


def test_decide_control_defaults_without_state():
    out = ir.decide_control(50, 60, rori=0, thresholds=TH)
    assert out['air']['changed'] is True
    assert out['pump']['state'] == 'ok'


def test_decide_control_handles_missing_thresholds():
    out = ir.decide_control(50, 60, rori=0, thresholds=None)
    assert out['pump']['state'] == 'ok'


def test_decide_control_clamps_negative_water():
    out = ir.decide_control(-5, 60, rori=0, thresholds=TH, state={})
    assert out['pump']['state'] == 'on'


def test_clamp_helper():
    assert ir.clamp(5, 0, 10) == 5
    assert ir.clamp(-5, 0, 10) == 0
    assert ir.clamp(15, 0, 10) == 10
