"""青禾智灌 —— 七日灌溉建议 HTTP 接口。

覆盖：GET /api/advice/calendar。

数据来源：当前地块的 6 日报雨（和风天气，可缺省）+ 实时水位/土壤（遥测缓存）+
用户阈值。天气接口不可用时仍返回按当前墒情给出的建议，并标记
`has_forecast: false` 让前端提示「未配置天气 Key」。
"""

from flask import Blueprint, jsonify, session

from qinghe import advice, db, planner

bp = Blueprint('advice_api', __name__)


@bp.route('/api/advice/calendar', methods=['GET'])
def api_advice_calendar():
    """返回未来 7 天的逐日灌溉建议与一句话总览。"""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    uid = session['user_id']

    precips = planner.forecast_precips(uid) or []
    ctx = planner.build_context(uid, precips=precips)

    thresh_row = db.load_thresholds(uid)
    thresh = dict(thresh_row) if thresh_row is not None else {}
    dynamic = {
        'P6d': ctx.get('p6d'),
        'alpha': ctx.get('alpha'),
        'effLower': ctx.get('eff_lower'),
        'effUpper': ctx.get('eff_upper'),
    }
    calendar = advice.build_calendar(
        precips,
        water_mm=ctx.get('water_mm'),
        soil_pct=ctx.get('soil_pct'),
        thresholds=thresh,
        dynamic=dynamic,
    )
    summary = advice.summarize(calendar, dynamic, bool(precips))
    # 灌水建议只看墒情与水情，但根区缺氧是独立风险：RORI 偏高时要单独提示增氧，
    # 否则会出现「RORI 76 重度厌氧」却写「正常维持」的自相矛盾。
    rori = ctx.get('rori')
    try:
        rori_value = float(rori) if rori is not None else None
    except (TypeError, ValueError):
        rori_value = None
    if rori_value is not None and rori_value >= 40:
        oxygen = '根区缺氧风险 %.0f 分，建议开启加气泵增氧' % rori_value
        summary = summary + '；' + oxygen

    return jsonify({
        'status': 'success',
        'has_forecast': bool(precips),
        'water_mm': ctx.get('water_mm'),
        'soil_pct': ctx.get('soil_pct'),
        'rori': ctx.get('rori'),
        'rori_level': ctx.get('rori_level'),
        'p6d': ctx.get('p6d'),
        'alpha': ctx.get('alpha'),
        'eff_lower': ctx.get('eff_lower'),
        'eff_upper': ctx.get('eff_upper'),
        'summary': summary,
        'days': calendar,
    })
