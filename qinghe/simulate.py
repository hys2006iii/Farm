"""青禾智灌 —— 外部联调用的遥测序列生成器。

定位（重要）：**本模块是给仓库外的联调脚本/压测脚本用的"数据发生器"，
不是系统功能，也不向运行中的服务端暴露任何接口。** 它只做两件事：

1. `build_series()` 生成一段**带物理合理性**的四路遥测序列（纯函数，无 IO）；
2. `run_simulation()` 直接调用 `iot.ingest_telemetry()` 把序列灌进指定账号，
   走的是与真实 MQTT 上报**完全相同**的落库 / 心跳 / RORI / 告警链路。

因此它可以被 pytest、CI、或开发者自己的外部脚本直接 import 使用，
而系统本身（网页、HTTP 接口）里看不到任何"演示数据 / 无硬件调试"入口。

命令行用法见 `tools/simulate_device.py`：它把本模块当作库，自己负责鉴权与循环，
服务端不提供 `/api/dev/*` 之类的测试接口。
"""

import math
import time

from qinghe import config, iot

#: 内置场景（键为接口参数值）
SCENARIOS = ('normal', 'drought', 'anaerobic', 'storm')

#: 默认灌入的采样条数与相邻采样间隔（秒）
DEFAULT_SAMPLES = 24
MIN_SAMPLES = 1
MAX_SAMPLES = 240
DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 3600

#: 场景说明（给外部脚本做帮助文案）
SCENARIO_META = {
    'normal': {
        'name': '常规运行',
        'desc': '水位与土壤适中、根区有氧，设备按阈值正常待机。',
    },
    'drought': {
        'name': '连续干旱',
        'desc': '水位与土壤湿度持续下降，触发低水位与土壤偏干告警。',
    },
    'anaerobic': {
        'name': '暴雨积水缺氧',
        'desc': '深水覆盖导致溶解氧骤降、Eh 转负，RORI 进入重度厌氧，气泵满载。',
    },
    'storm': {
        'name': '强降雨前馈',
        'desc': '降雨临近、水位上升，演示「控水等雨 / 蓄雨」的前馈逻辑。',
    },
}


def _adc_water(mm: float) -> int:
    """毫米 → 水位 ADC（与 irrigation.adc_to_water_mm 互逆）。"""
    mm = max(0.0, min(float(mm), config.WATER_FS_MM))
    return int(round(mm / config.WATER_FS_MM * config.ADC_MAX))


def _adc_soil(pct: float) -> int:
    """土壤湿润度 % → 电容式 ADC（与 irrigation.adc_to_soil_pct 互逆）。"""
    pct = max(0.0, min(float(pct), 100.0))
    return int(round(config.ADC_MAX - pct / 100.0 * config.ADC_MAX))


def _wave(i: int, samples: int, amp: float, phase: float = 0.0) -> float:
    """一条平滑正弦波动，让曲线看着像真实测量而不是直线。"""
    ratio = i / max(samples - 1, 1)
    return amp * math.sin((ratio * 2.0 * math.pi) + phase)


def clamp_samples(samples) -> int:
    """把采样条数收敛到 [MIN_SAMPLES, MAX_SAMPLES]；缺失或非数字用默认值。

    注意：`0` / 负数属于「显式给出的非法条数」，夹到下限 1；
    只有 `None` 或无法解析为整数的值才回退 `DEFAULT_SAMPLES`。
    """
    if samples is None:
        return DEFAULT_SAMPLES
    try:
        value = int(samples)
    except (TypeError, ValueError):
        return DEFAULT_SAMPLES
    return max(MIN_SAMPLES, min(value, MAX_SAMPLES))


def clamp_interval(interval) -> int:
    """把采样间隔（秒）收敛到 [MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS]。"""
    if interval is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        value = int(interval)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(value, MAX_INTERVAL_SECONDS))


def build_series(scenario: str = 'normal', samples: int = DEFAULT_SAMPLES) -> list:
    """按场景生成遥测序列（列表元素为 MQTT 属性字典）。

    每条记录的键与设备上报一致：`waterlevel` / `humidity` / `do` / `eh` /
    `air_pump` / `water_pump` / `temperature` / `humidity_air`。
    """
    scenario = scenario if scenario in SCENARIOS else 'normal'
    samples = clamp_samples(samples)
    series = []
    for i in range(samples):
        progress = i / max(samples - 1, 1)
        if scenario == 'drought':
            water_mm = 120.0 - 95.0 * progress + _wave(i, samples, 2.0)
            soil_pct = 60.0 - 32.0 * progress + _wave(i, samples, 1.2, 0.6)
            do_mgl = 5.2 - 1.1 * progress + _wave(i, samples, 0.15, 1.1)
            eh_mv = 180.0 + 40.0 * progress + _wave(i, samples, 4.0, 0.4)
        elif scenario == 'anaerobic':
            water_mm = 165.0 + 95.0 * progress + _wave(i, samples, 3.0)
            soil_pct = 92.0 + 6.0 * progress + _wave(i, samples, 0.8)
            do_mgl = 5.4 - 4.6 * progress + _wave(i, samples, 0.12, 0.8)
            eh_mv = 160.0 - 260.0 * progress + _wave(i, samples, 6.0, 0.3)
        elif scenario == 'storm':
            water_mm = 55.0 + 50.0 * progress + _wave(i, samples, 2.5)
            soil_pct = 66.0 + 18.0 * progress + _wave(i, samples, 1.0, 0.5)
            do_mgl = 5.8 - 0.8 * progress + _wave(i, samples, 0.12, 1.2)
            eh_mv = 210.0 - 60.0 * progress + _wave(i, samples, 3.0)
        else:  # normal
            water_mm = 108.0 + _wave(i, samples, 6.0)
            soil_pct = 58.0 + _wave(i, samples, 4.0, 0.7)
            do_mgl = 5.9 + _wave(i, samples, 0.25, 1.4)
            eh_mv = 205.0 + _wave(i, samples, 8.0, 0.2)

        do_mgl = max(0.2, do_mgl)
        air_on = do_mgl < 3.0 or eh_mv < 0
        water_on = water_mm < 45.0
        series.append({
            'waterlevel': _adc_water(max(0.0, water_mm)),
            'humidity': _adc_soil(soil_pct),
            'do': round(do_mgl, 2),
            'eh': int(round(eh_mv)),
            'air_pump': 'on' if air_on else 'off',
            'water_pump': 'on' if water_on else 'off',
            'temperature': round(24.0 + _wave(i, samples, 2.5, 0.9), 1),
            'humidity_air': int(round(68.0 + _wave(i, samples, 6.0, 1.3))),
        })
    return series


def describe_scenarios() -> list:
    """返回场景清单（供外部脚本打印帮助）。"""
    return [
        {'key': key, 'name': SCENARIO_META[key]['name'], 'desc': SCENARIO_META[key]['desc']}
        for key in SCENARIOS
    ]


def run_simulation(uid, scenario: str = 'normal', samples: int = DEFAULT_SAMPLES,
                   interval: int = DEFAULT_INTERVAL_SECONDS, emit=None) -> dict:
    """把一段模拟遥测灌进指定账号，返回本次注入的概要。

    参数:
        uid:      用户 id（该账号的历史库与看板都会看到这批数据）
        scenario: `SCENARIOS` 之一，非法值按 `normal` 处理
        samples:  采样条数，夹到 1–240（None 用默认 24）
        interval: 相邻采样间隔（秒），夹到 1–3600（None 用默认 60）
        emit:     前端推送函数；默认用 `realtime.emit_hw_data`，传 False 关闭

    返回: `{'scenario', 'samples', 'interval', 'first_ts', 'last_ts', 'latest'}`
    """
    scenario = scenario if scenario in SCENARIOS else 'normal'
    samples = clamp_samples(samples)
    interval = clamp_interval(interval)
    series = build_series(scenario, samples)

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (samples - 1) * interval * 1000
    for index, values in enumerate(series):
        iot.ingest_telemetry(uid, values, start_ms + index * interval * 1000, emit=emit)

    # 批量队列异步落库，这里主动刷一次，保证紧接着查询能看到数据
    try:
        iot.flush_history()
    except Exception:  # noqa: BLE001 - 落库失败不影响返回概要
        pass

    return {
        'scenario': scenario,
        'samples': samples,
        'interval': interval,
        'first_ts': start_ms,
        'last_ts': now_ms,
        'latest': series[-1],
    }
