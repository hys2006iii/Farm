"""青禾智灌 —— 灌溉决策纯函数层（说明书 3.1~3.4）。

本模块**不含任何 IO 与全局状态**，全部为纯函数，便于单测：
- `compute_rori()`          根区缺氧风险指数 RORI 多维融合
- `classify_rori()`         RORI 分级（表3-1）
- `compute_dynamic_threshold()` 降雨前馈动态阈值（P6d / α / effLower / effUpper）
- `decide_control()`        自动调控策略：气泵按 RORI 分级 + 水泵水位滞回

所有公式与 `templates/index.html` 中前端实现逐字对应，保证前后端判定一致。
"""

from qinghe import config

# ============================================================
# 一、量程换算
# ============================================================


def adc_to_water_mm(water_adc) -> float:
    """水位 ADC -> 毫米（探针式，ADC 越高水越深，满量程 4095 ≈ 300mm）。"""
    try:
        mm = float(water_adc) / config.ADC_MAX * config.WATER_FS_MM
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(mm, config.WATER_FS_MM))


def adc_to_soil_pct(soil_adc) -> float:
    """土壤湿度 ADC -> 湿润度 %（电容式，ADC 越高越干）。"""
    try:
        pct = (config.ADC_MAX - float(soil_adc)) / config.ADC_MAX * 100.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(pct, 100.0))


def clamp(value, low, high):
    """把 value 限制到 [low, high]。"""
    return max(low, min(value, high))


# ============================================================
# 二、RORI 根区缺氧风险指数（说明书 3.1~3.2）
# ============================================================


def risk_eh(eh_mv) -> float:
    """3.1.1 氧化还原电位风险因子 SEh = clamp(0,1,(Ehmax-Eh)/(Ehmax-Ehmin))。"""
    eh = float(eh_mv)
    return clamp((config.EH_SAFE_MV - eh) / config.EH_SPAN_MV, 0.0, 1.0)


def risk_do(do_mgl) -> float:
    """3.1.2 根区溶解氧风险因子 SDO = clamp(0,1,(DOmax-DO)/(DOmax-DOmin))。"""
    do = float(do_mgl)
    return clamp((config.DO_SAFE_MGL - do) / config.DO_SAFE_MGL, 0.0, 1.0)


def risk_water(water_mm) -> float:
    """3.1.3 水位风险：(WaterA0-5)/100，水位 ≤5mm 死区内为 0。"""
    water = float(water_mm)
    if water <= config.WATER_DEADBAND_MM:
        return 0.0
    return clamp(
        (water - config.WATER_DEADBAND_MM) / config.WATER_RISK_SPAN_MM, 0.0, 1.0
    )


def risk_soil(soil_pct) -> float:
    """3.1.3 土壤风险：越湿润（%RH 越高）缺氧风险越高 -> %RH/100。"""
    return clamp(float(soil_pct) / 100.0, 0.0, 1.0)


def compute_rori(water_adc, soil_adc, do_mgl, eh_mv) -> float:
    """3.2 RORI 多维融合，返回 0~100 的风险指数。

    参数:
        water_adc: 水位 ADC 原始值（0~4095）
        soil_adc:  土壤湿度 ADC 原始值（0~4095）
        do_mgl:    根区溶解氧（mg/L，0~20）
        eh_mv:     根区氧化还原电位（mV，-150~300）
    """
    water_mm = adc_to_water_mm(water_adc)
    soil_pct = adc_to_soil_pct(soil_adc)
    s_eh = risk_eh(eh_mv)
    s_do = risk_do(do_mgl)
    r_water = risk_water(water_mm)
    r_soil = risk_soil(soil_pct)
    p_risk = (
        config.W_EH * s_eh
        + config.W_DO * s_do
        + config.W_WATER_SOIL * max(r_water, r_soil)
        + config.GAMMA * r_water * r_soil
    )
    return clamp(p_risk, 0.0, 1.0) * 100.0


def classify_rori(rori) -> dict:
    """表3-1：RORI≥70 重度厌氧 / 40≤RORI<70 中度缺氧 / RORI<40 安全运行。

    返回: {'code': 0|1|2, 'name': str, 'strategy': str}
    """
    value = float(rori)
    if value >= config.RORI_HEAVY:
        return {'code': 2, 'name': '重度厌氧',
                'strategy': '重度厌氧预警，加气机全满载强制增氧'}
    if value >= config.RORI_MODERATE:
        return {'code': 1, 'name': '中度缺氧',
                'strategy': '根区微量缺氧，周期性脉冲加气补氧'}
    return {'code': 0, 'name': '安全运行', 'strategy': '根区有氧环境优良，加气机低耗待机'}


# ============================================================
# 三、降雨前馈动态阈值（说明书 3.3）
# ============================================================


def compute_p6d(daily_precips) -> float:
    """P6d = Σ(t=1..6) ω_t·P_t，时间衰减加权 6 日累计降雨（mm）。"""
    total = 0.0
    for i, precip in enumerate(daily_precips or []):
        if i >= len(config.RAIN_WEIGHTS):
            break
        try:
            total += config.RAIN_WEIGHTS[i] * (float(precip) or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def alpha_of(p6d: float) -> float:
    """动态降雨有效利用系数 α 分段定界：≤10 → 0.95；≤50 → 0.75；否则 0.45。"""
    if p6d <= config.ALPHA_LOW_MAX:
        return config.ALPHA_LOW
    if p6d <= config.ALPHA_MID_MAX:
        return config.ALPHA_MID
    return config.ALPHA_HIGH


def compute_dynamic_threshold(humi_down, humi_up, daily_precips) -> dict:
    """降雨前馈动态阈值。

    返回字段（与前端 window.dynamicThreshold 一致）:
        P6d, alpha, effLower, effUpper, baseLower, baseUpper, hasForecast, rainComing
    """
    fc = list(daily_precips or [])
    p6d = compute_p6d(fc)
    alpha = alpha_of(p6d)
    # 前馈控水等雨：预测有雨则下调灌溉触发下限（限位 45% 防枯萎保底）
    eff_lower = max(
        config.EFF_LOWER_FLOOR, humi_down - (alpha * p6d / config.H_ROOT) * 100.0
    )
    # 蓄雨型控灌：强降雨前馈(P6d≥15mm)放宽蓄水上限
    if p6d >= config.EFF_UPPER_RAIN:
        eff_upper = min(config.EFF_UPPER_CAP, humi_up + config.EFF_UPPER_BONUS)
    else:
        eff_upper = humi_up
    return {
        'P6d': p6d,
        'alpha': alpha,
        'effLower': eff_lower,
        'effUpper': eff_upper,
        'baseLower': humi_down,
        'baseUpper': humi_up,
        'hasForecast': len(fc) > 0,
        'rainComing': p6d > 0,
    }


# ============================================================
# 四、自动调控策略（说明书 3.4）
# ============================================================

#: 水泵自动状态取值：on / off / hold（前馈控水等雨）/ ok（区间内待命）
PUMP_STATE_ON = 'on'
PUMP_STATE_OFF = 'off'
PUMP_STATE_HOLD = 'hold'
PUMP_STATE_OK = 'ok'


def decide_control(water_mm, soil_pct, rori, thresholds: dict,
                   state: dict = None, dt: dict = None) -> dict:
    """自动调控策略（纯函数，无副作用）。

    参数:
        water_mm:   当前水位（mm）
        soil_pct:   当前土壤湿润度（%）
        rori:       RORI 指数（0~100）
        thresholds: {'waterlevel_down','waterlevel_up','humi_down','humi_up'}
        state:      上一轮状态 {'pump': 'on'|'off'|'hold'|'ok', 'air': 'ON'|'OFF'}
        dt:         动态阈值字典（compute_dynamic_threshold 的输出），可选

    返回:
        {
          'air': {'state': 'ON'|'OFF', 'changed': bool, 'reason': str},
          'pump': {'state': 'on'|'off'|'hold'|'ok', 'command': 'ON'|'OFF'|'',
                   'changed': bool, 'reason': str},
          'rori': float, 'level': dict, 'effective_code': int
        }

    策略要点（与前端一致）：
    - 气泵：RORI 分级 → code≥1 开、否则关；若预测有降雨则**提前一级**增氧；
    - 水泵：水位 < 下限 → 无雨则开泵、有雨则 hold（控水等雨）；
            水位 > 上限 → 关泵；区间内 → ok（滞回，不动作）。
    """
    state = state or {}
    dt = dt or {}
    thresholds = thresholds or {}

    rori = float(rori)
    level = classify_rori(rori)
    eff_code = level['code']
    rain_coming = bool(dt.get('rainComing'))
    if rain_coming and eff_code < 2:
        eff_code += 1

    air_new = 'ON' if eff_code >= 1 else 'OFF'
    air_old = state.get('air')
    air_changed = air_old != air_new
    air_reason = 'RORI %.2f 分级[%s]' % (rori, level['name'])
    if rain_coming and eff_code > level['code']:
        air_reason += '；降雨前馈提前一级增氧'

    wl_down = thresholds.get('waterlevel_down', config.THRESH_DEFAULTS['waterlevel_down'])
    wl_up = thresholds.get('waterlevel_up', config.THRESH_DEFAULTS['waterlevel_up'])
    water = float(water_mm or 0.0)

    pump_state = state.get('pump')
    pump_cmd = ''
    pump_reason = ''
    if water < wl_down:
        if rain_coming:
            new_state = PUMP_STATE_HOLD
            pump_reason = '水位 %.1fmm < 下限 %smm，但预测降雨 P6d=%.1fmm，暂缓补水' % (
                water, wl_down, dt.get('P6d', 0.0))
        else:
            new_state = PUMP_STATE_ON
            pump_cmd = 'ON'
            pump_reason = '水位 %.1fmm < 下限 %smm，自动开启水泵灌水' % (water, wl_down)
    elif water > wl_up:
        new_state = PUMP_STATE_OFF
        pump_cmd = 'OFF'
        pump_reason = '水位 %.1fmm > 上限 %smm，自动关闭水泵' % (water, wl_up)
    else:
        new_state = PUMP_STATE_OK
        pump_reason = '水位 %.1fmm 处于 [%s, %s] 区间，水泵待命' % (water, wl_down, wl_up)

    pump_changed = pump_state != new_state
    # 仅在状态真正变化时才下发指令，避免高频重复刷指令
    if not pump_changed:
        pump_cmd = ''

    return {
        'air': {'state': air_new, 'changed': air_changed, 'reason': air_reason},
        'pump': {
            'state': new_state,
            'command': pump_cmd,
            'changed': pump_changed,
            'reason': pump_reason,
        },
        'rori': rori,
        'level': level,
        'effective_code': eff_code,
    }
