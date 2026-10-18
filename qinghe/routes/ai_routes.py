"""青禾智灌 —— AI 对话 HTTP 接口。

覆盖：/api/ai_chat。未配置 AI Key 时返回固定提示，与旧版逐字一致。

提问会**自动附带服务端实时快照**（地块、四路读数、RORI、阈值与降雨前馈、
设备状态、近期趋势），让 AI 的回答落在当前数据上，而不是泛泛而谈。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import ai, config, validators

bp = Blueprint('ai_api', __name__)

NO_KEY_TIP = '⚠️ 提示：未检测到 AI Key，请在【设置】中配置。'


@bp.route('/api/ai_chat', methods=['POST'])
def api_ai_chat():
    """把用户提问（+ 实时数据快照）转发给配置的 AI 接口。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权访问'}), 401
    uid = session['user_id']
    try:
        data = validators.get_json_object(request)
        user_msg = validators.as_str(data, 'message', '')
    except validators.ValidationError as exc:
        return jsonify({'error': exc.message}), exc.status
    if len(user_msg) > config.AI_MSG_MAX_LEN:
        return jsonify({'error': '提问过长，请控制在 %d 字以内' % config.AI_MSG_MAX_LEN}), 400

    # 取快照失败不影响问答：build_snapshot 内部已逐段兜底，返回空串即无上下文
    try:
        snapshot = ai.build_snapshot(uid)
    except Exception:  # noqa: BLE001
        snapshot = ''

    cfg = ai.load_ai_config(uid)
    if not cfg or not cfg['ai_key']:
        # 没配 Key 也要让用户看到「系统此刻读到了什么」，避免提示是空的
        content = NO_KEY_TIP
        if snapshot:
            content = content + '\n\n' + snapshot + '\n\n（配置 AI Key 后，以上快照会自动随问题一起发送。）'
        return jsonify({'choices': [{'message': {'content': content}}]})

    return jsonify(ai.chat(cfg['ai_domain'], cfg['ai_key'], user_msg, context=snapshot))
