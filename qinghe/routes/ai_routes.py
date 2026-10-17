"""青禾智灌 —— AI 对话 HTTP 接口。

覆盖：/api/ai_chat。未配置 AI Key 时返回固定提示，与旧版逐字一致。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import ai

bp = Blueprint('ai_api', __name__)

NO_KEY_TIP = '⚠️ 提示：未检测到 AI Key，请在【设置】中配置。'


@bp.route('/api/ai_chat', methods=['POST'])
def api_ai_chat():
    """把用户提问转发给配置的 AI 接口，异常一律包装成 choices 结构返回。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权访问'}), 401
    user_msg = (request.json or {}).get('message', '')
    cfg = ai.load_ai_config(session['user_id'])
    if not cfg or not cfg['ai_key']:
        return jsonify({'choices': [{'message': {'content': NO_KEY_TIP}}]})
    return jsonify(ai.chat(cfg['ai_domain'], cfg['ai_key'], user_msg))
