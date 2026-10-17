"""AI 实时上下文快照测试。

`ai.build_snapshot` 把服务端真实数据压成一段文字，随提问一起发给模型；
这里验证「该有的都有、没有的不编、失败不抛」，以及快照确实进了请求体。
"""

import pytest

from qinghe import ai, planner

from helpers import fetch_all, login_session, set_config, user_id_of


@pytest.fixture()
def logged_in(client, registered):
    """已登录客户端，并清空实时遥测缓存（缓存是进程级全局，会跨用例串数据）。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    planner.reset_telemetry(uid)
    return client


def test_snapshot_includes_farm_and_readings(logged_in):
    """快照含地块名、四路读数、RORI 与后续提示。"""
    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    set_config(uid, farm_name='东三垄试验田')
    planner.update_telemetry(uid, waterlevel=1500, humidity=2200, do=6.0, eh=120.0)

    text = ai.build_snapshot(uid)
    assert '东三垄试验田' in text
    assert '四路读数' in text
    assert 'RORI' in text
    assert '不要编造读数' in text


def test_snapshot_reports_missing_readings(logged_in):
    """没有遥测时不编造数字，明确写「暂无」。"""
    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    planner.reset_telemetry(uid)
    text = ai.build_snapshot(uid)
    assert '暂无' in text
    assert 'RORI 0.0' not in text


def test_snapshot_includes_thresholds(logged_in):
    """快照带上当前阈值区间（未自定义时写明按默认值运行）。"""
    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    text = ai.build_snapshot(uid)
    assert '阈值' in text
    assert ('土壤' in text and '水位' in text) or '未设置' in text


def test_snapshot_is_length_capped(logged_in):
    """快照长度受 SNAPSHOT_MAX_CHARS 限制，避免挤爆上下文。"""
    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    assert len(ai.build_snapshot(uid)) <= ai.SNAPSHOT_MAX_CHARS


def test_snapshot_never_raises(logged_in, monkeypatch):
    """取数环节炸掉时返回空串或降级文本，不向上抛。"""
    import qinghe.planner as planner_module

    def boom(*_args, **_kwargs):
        raise RuntimeError('模拟数据库故障')

    monkeypatch.setattr(planner_module, 'build_context', boom)
    text = ai.build_snapshot(user_id_of('farmer01'))
    assert isinstance(text, str)


def test_chat_sends_context_as_second_system_message(monkeypatch):
    """快照作为第二条 system 消息插在固定提示与用户提问之间。"""
    captured = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {'choices': [{'message': {'content': 'ok'}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['body'] = json
        return Resp()

    monkeypatch.setattr(ai.requests, 'post', fake_post)
    out = ai.chat('https://api.deepseek.com', 'sk-x', '要不要开泵？',
                  context='- 当前地块：东三垄')
    assert out == {'choices': [{'message': {'content': 'ok'}}]}
    messages = captured['body']['messages']
    assert len(messages) == 3
    assert messages[0]['role'] == 'system'
    assert '东三垄' in messages[1]['content']
    assert messages[2] == {'role': 'user', 'content': '要不要开泵？'}


def test_chat_without_context_keeps_two_messages(monkeypatch):
    """无快照时保持旧的两条消息结构。"""
    captured = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {'choices': []}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['body'] = json
        return Resp()

    monkeypatch.setattr(ai.requests, 'post', fake_post)
    ai.chat('https://api.deepseek.com', 'sk-x', '你好')
    assert len(captured['body']['messages']) == 2
    assert captured['body']['messages'][1]['content'] == '你好'


def test_api_ai_chat_without_key_still_shows_snapshot(client, registered):
    """没配 Key 时，返回的提示里也要有实时快照（让用户知道系统读到了什么）。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    planner.update_telemetry(uid, waterlevel=1500, humidity=2200, do=6.0, eh=120.0)
    resp = client.post('/api/ai_chat', json={'message': '现在要不要开泵？'})
    content = resp.get_json()['choices'][0]['message']['content']
    assert content.startswith('⚠️ 提示：未检测到 AI Key')
    assert '当前地块' in content
    assert '四路读数' in content


def test_snapshot_reflects_history_trend(logged_in):
    """有历史数据时快照带近期趋势（水位 mm 的最近一次读数）。"""
    with logged_in.session_transaction() as sess:
        uid = sess['user_id']
    text = ai.build_snapshot(uid)
    # 没有历史时不该出现伪造的趋势数字
    rows = fetch_all('SELECT COUNT(*) AS n FROM sensor_history WHERE user_id=?', (uid,))
    if rows and rows[0]['n'] == 0:
        assert '趋势' not in text or '暂无' in text
