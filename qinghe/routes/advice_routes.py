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
        'summary': advice.summarize(calendar, dynamic, bool(precips)),
        'days': calendar,
    })
