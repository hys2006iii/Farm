"""青禾智灌 —— 七日灌溉建议。

把「未来 6 日报雨 + 当前水位/土壤 + 阈值 + 动态湿度区间」压成逐日建议，
回答农场管理者最常问的一句话：「这几天该不该灌、灌多少」。

只做**建议**，不下发指令：真正的自动控制仍在 autocontrol / 前端阈值逻辑里，
人工确认后由 `/api/plan/confirm` 执行。

纯函数，无 IO，便于单测。
"""

import datetime

from qinghe import config, irrigation

#: 建议级别 → 中文标签（前端按 level 上色）
LEVEL_LABELS = {
    'irrigate': '需要灌溉',
    'wait_rain': '控水等雨',
    'watch': '观察待定',
    'hold': '正常维持',
}

#: 降雨达到该值视为「有效降雨」，建议等雨而不是抽水
RAIN_EFFECTIVE_MM = 5.0
#: 土壤低于动态下限该幅度（百分点）才判定为「需要灌溉」
SOIL_GAP_PCT = 3.0
#: 降雨小于该值视为「基本不降雨」
RAIN_TINY_MM = 1.0


def _level_for(precip: float, soil_pct, eff_lower, water_mm, wl_down) -> str:
    """按单日降雨与当前墒情判定建议级别。"""
    soil_low = soil_pct is not None and soil_pct < (eff_lower - SOIL_GAP_PCT)
    water_low = water_mm is not None and wl_down is not None and water_mm < wl_down
    if precip >= RAIN_EFFECTIVE_MM:
        return 'wait_rain'
    if soil_low or water_low:
        return 'irrigate' if precip < RAIN_TINY_MM else 'watch'
    if precip >= RAIN_TINY_MM:
        return 'watch'
    return 'hold'


def _text_for(level: str, precip: float, soil_pct, water_mm, eff_lower) -> str:
    """生成一句可执行的说明（数字取整，避免假精确）。"""
    soil_text = '%.0f%%' % soil_pct if soil_pct is not None else '未知'
    water_text = '%.0f mm' % water_mm if water_mm is not None else '未知'
    if level == 'wait_rain':
        return '预报降雨 %.1f mm，先不抽水，靠雨水补墒并蓄墒。' % precip
    if level == 'irrigate':
        return ('土壤 %s 已低于动态下限 %.0f%%，当日基本无雨，建议灌水至田间水位 %s 以上。'
                % (soil_text, eff_lower, water_text))
    if level == 'watch':
        return ('降雨 %.1f mm 不稳定，土壤 %s 接近下限，建议盯一天再决定。'
                % (precip, soil_text))
    return '降雨 %.1f mm，墒情 %s / 水位 %s 在区间内，维持现状。' % (
        precip, soil_text, water_text)


def build_calendar(daily_forecast, water_mm=None, soil_pct=None, thresholds=None,
                   dynamic=None, today=None, has_telemetry=True) -> list:
    """生成逐日灌溉建议。

    参数:
        daily_forecast: 每日降雨列表（mm），索引 0 = 今天；可为空（无天气预报）
        water_mm:       当前渠道水位（mm），未知传 None
        soil_pct:       当前土壤湿润度（%），未知传 None
        thresholds:     `{'waterlevel_down', 'humi_down', ...}`，缺省取系统默认
        dynamic:        `irrigation.compute_dynamic_threshold()` 的结果，缺省重算
        today:          起始日期（`datetime.date`），缺省今天
        has_telemetry:  是否已收到本地块遥测；为 False 时不给灌溉结论（无数据不谈灌溉）
    返回:
        `[{'date','weekday','precip','level','label','text','has_forecast'}]`
    """
    thresholds = dict(thresholds or {})
    wl_down = thresholds.get('waterlevel_down', config.THRESH_DEFAULTS.get('waterlevel_down', 30))
    humi_down = thresholds.get('humi_down', config.THRESH_DEFAULTS.get('humi_down', 40))
    humi_up = thresholds.get('humi_up', config.THRESH_DEFAULTS.get('humi_up', 80))
    precips = [float(p or 0.0) for p in (daily_forecast or [])]
    has_forecast = bool(precips)
    if dynamic is None:
        dynamic = irrigation.compute_dynamic_threshold(humi_down, humi_up, precips[:6])
    eff_lower = float(dynamic.get('effLower', humi_down))
    start = today or datetime.date.today()
    days = max(len(precips), 7)
    calendar = []
    for index in range(min(days, 7)):
        precip = precips[index] if index < len(precips) else 0.0
        if has_telemetry:
            level = _level_for(precip, soil_pct, eff_lower, water_mm, wl_down)
            text = _text_for(level, precip, soil_pct, water_mm, eff_lower)
        else:
            # 没有本地块读数时不给「需要灌溉/可等雨」结论，避免 0 值被当成真实墒情
            level = 'watch'
            text = '尚未收到该地块遥测，先按现有安排观察，设备上报后再判断。'
        day = start + datetime.timedelta(days=index)
        calendar.append({
            'date': day.isoformat(),
            'weekday': '周%s' % '一二三四五六日'[day.weekday()],
            'precip': round(precip, 1),
            'level': level,
            'label': LEVEL_LABELS[level],
            'text': text,
            'has_forecast': has_forecast and index < len(precips),
        })
    return calendar


def summarize(calendar, dynamic=None, has_forecast=True, has_telemetry=True) -> str:
    """把逐日建议压成一句话总览（前端卡片副标题）。"""
    if not calendar:
        return '暂无建议'
    counts = {}
    for item in calendar:
        counts[item['level']] = counts.get(item['level'], 0) + 1
    need = counts.get('irrigate', 0)
    rain = counts.get('wait_rain', 0)
    p6d = (dynamic or {}).get('P6d')
    parts = []
    if p6d is not None:
        parts.append('6 日加权降雨 %.1f mm' % float(p6d))
    if not has_telemetry:
        parts.append('尚未收到本地块遥测，建议先确认设备在线')
    if rain:
        parts.append('%d 天可等雨' % rain)
    if need:
        parts.append('%d 天建议灌溉' % need)
    if has_telemetry and not need and not rain:
        parts.append('未来一周按当前阈值维持即可')
    if not has_forecast:
        parts.append('（未配置天气 Key，建议只按当前墒情参考）')
    return '，'.join(parts)
