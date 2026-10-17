"""NF4 AI 决策预案闭环的单元测试（规则回退、确认、拒绝、列表）。"""

import json
import time

import pytest

from helpers import execute, fetch_all, fetch_one, user_id_of
from qinghe import iot, planner


@pytest.fixture(autouse=True)
def _fresh_planner(flask_app):
    """每个用例重置模块级建表标记与遥测缓存（临时库每个用例都是新的）。"""
    planner._schema_ready = False
    with planner._latest_lock:
        planner._latest.clear()
    yield
    planner._schema_ready = False
    with planner._latest_lock:
        planner._latest.clear()


def _uid(client, registered):
    """取当前登录用户 id。"""
    return user_id_of(registered[0])


def _insert_plan(uid, ts=None, status='pending', actions=None, reasoning='手工预案'):
    """直接插入一条预案（ts 缺省为当前时间，避免误触 TTL）。"""
    planner._ensure_schema()
    proposal = {'actions': actions or [], 'summary': '手工', 'risk': 'low'}
    stamp = int(time.time() * 1000) if ts is None else int(ts)
    execute(
        'INSERT INTO plans (user_id, ts, status, context_json, reasoning, proposal_json)'
        ' VALUES (?, ?, ?, ?, ?, ?)',
        (uid, stamp, status, '{}', reasoning, json.dumps(proposal, ensure_ascii=False)),
    )
    return fetch_one('SELECT id FROM plans WHERE user_id=? ORDER BY id DESC LIMIT 1', (uid,))['id']


def _dry_telemetry(uid):
    """灌一个「水位偏低、缺氧」的遥测快照，触发规则回退动作。"""
    planner.update_telemetry(
        uid, water_adc=100, soil_adc=1000, do_mgl=2.0, eh_mv=-50,
        air_pump='off', water_pump='off',
    )


def test_rule_fallback_proposal_contains_numeric_reasoning(client, registered):
    """无 AI Key 时走规则回退：ai_used=False、actions 非空、reasoning 含数值依据。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    _dry_telemetry(uid)

    result = planner.propose_plan(uid, '')

    assert result['ai_used'] is False
    assert result['status'] == 'pending'
    assert result['actions'], '规则回退必须产出动作'
    devices = {item['device'] for item in result['actions']}
    assert devices <= {'air_pump', 'water_pump'}
    assert 'RORI=' in result['reasoning']
    assert '水位滞回' in result['reasoning']
    assert '降雨前馈' in result['reasoning']
    assert '7.3' in result['reasoning'] or '7.33' in result['reasoning']

    row = fetch_one('SELECT * FROM plans WHERE id=?', (result['plan_id'],))
    assert row['status'] == 'pending'
    assert row['user_id'] == uid
    stored = json.loads(row['proposal_json'])
    assert stored['actions'] == result['actions']


def test_propose_falls_back_when_ai_request_fails(client, registered, monkeypatch):
    """配置了 AI Key 但网络失败时同样回退规则方案。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    execute('UPDATE configs SET ai_key=?, ai_domain=? WHERE user_id=?',
            ('fake-key', 'https://api.example.invalid', uid))
    _dry_telemetry(uid)

    def boom(*args, **kwargs):
        raise RuntimeError('network down')

    monkeypatch.setattr(planner.requests, 'post', boom)
    result = planner.propose_plan(uid, '要不要补水？')

    assert result['ai_used'] is False
    assert result['actions']
    assert '【规则回退·非 AI 推理】' in result['reasoning']


def test_propose_uses_ai_json_when_available(client, registered, monkeypatch):
    """AI 返回合法 JSON 时采信 AI 方案，并过滤白名单外的动作。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    execute('UPDATE configs SET ai_key=?, ai_domain=? WHERE user_id=?',
            ('fake-key', 'https://api.deepseek.com', uid))
    _dry_telemetry(uid)

    payload = {
        'reasoning': '水位 7.33mm 低于下限 30mm，建议补水。',
        'actions': [
            {'device': 'water_pump', 'action': 'on', 'reason': '补水'},
            {'device': 'valve', 'action': 'on', 'reason': '非法设备'},
        ],
        'summary': '开泵补水',
        'risk': 'medium',
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return {'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}}]}

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured['timeout'] = timeout
        return FakeResponse()

    monkeypatch.setattr(planner.requests, 'post', fake_post)
    result = planner.propose_plan(uid, '')

    assert result['ai_used'] is True
    assert result['risk'] == 'medium'
    assert [item['device'] for item in result['actions']] == ['water_pump']
    assert captured['timeout'] == planner.AI_TIMEOUT_SECONDS == 25


def test_confirm_plan_applies_and_persists(client, registered, monkeypatch):
    """确认预案会逐条下发、更新状态并记录 apply_result。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    _dry_telemetry(uid)
    result = planner.propose_plan(uid)
    assert result['actions']

    calls = []

    def fake_send(uid_arg, props):
        calls.append((uid_arg, props))
        return True

    monkeypatch.setattr(iot, 'send_property_command', fake_send)
    confirmed = planner.confirm_plan(uid, result['plan_id'])

    assert confirmed['ok'] is True
    assert len(confirmed['applied']) == len(result['actions'])
    assert len(calls) == len(result['actions'])
    assert confirmed['failed'] == []
    row = fetch_one('SELECT * FROM plans WHERE id=?', (result['plan_id'],))
    assert row['status'] == 'confirmed'
    assert row['decided_ts'] > 0
    apply_result = json.loads(row['apply_result'])
    assert apply_result['applied'] == confirmed['applied']


def test_confirm_rejects_other_users_plan(client, registered, monkeypatch):
    """越权确认他人预案必须被拒绝，且不改变状态。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    plan_id = _insert_plan(uid, actions=[{'device': 'water_pump', 'action': 'on'}])

    calls = []
    monkeypatch.setattr(iot, 'send_property_command', lambda u, p: calls.append(p) or True)
    result = planner.confirm_plan(uid + 999, plan_id)

    assert result['ok'] is False
    assert 'error' in result
    assert calls == []
    assert fetch_one('SELECT status FROM plans WHERE id=?', (plan_id,))['status'] == 'pending'


def test_confirm_rejects_already_decided_plan(client, registered, monkeypatch):
    """已确认的预案不能再次确认。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    _dry_telemetry(uid)
    first = planner.propose_plan(uid)
    monkeypatch.setattr(iot, 'send_property_command', lambda u, p: True)
    assert planner.confirm_plan(uid, first['plan_id'])['ok'] is True

    again = planner.confirm_plan(uid, first['plan_id'])
    assert again['ok'] is False
    assert '不可确认' in again['error']


def test_confirm_marks_expired_beyond_ttl(client, registered, monkeypatch):
    """超过 600 秒 TTL 的预案置为 expired 并拒绝执行。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    plan_id = _insert_plan(uid, ts=int(time.time() * 1000) - 700_000,
                           actions=[{'device': 'air_pump', 'action': 'on'}])
    monkeypatch.setattr(iot, 'send_property_command', lambda u, p: True)

    result = planner.confirm_plan(uid, plan_id)

    assert result['ok'] is False
    assert '过期' in result['error']
    assert fetch_one('SELECT status FROM plans WHERE id=?', (plan_id,))['status'] == 'expired'


def test_confirm_filters_non_whitelisted_actions(client, registered, monkeypatch):
    """白名单外的设备 / 动作不会下发，记为 failed。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    plan_id = _insert_plan(uid, actions=[
        {'device': 'valve', 'action': 'on'},
        {'device': 'water_pump', 'action': 'toggle'},
        {'device': 'water_pump', 'action': 'on'},
    ])
    monkeypatch.setattr(iot, 'send_property_command', lambda u, p: True)

    result = planner.confirm_plan(uid, plan_id)

    assert result['ok'] is True
    assert result['applied'] == [{'device': 'water_pump', 'action': 'on'}]
    assert len(result['failed']) == 2


def test_reject_plan_appends_reason_and_blocks_second_reject(client, registered):
    """拒绝预案写入原因；重复拒绝返回 False。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    _dry_telemetry(uid)
    result = planner.propose_plan(uid)

    assert planner.reject_plan(uid, result['plan_id'], '水量够，不用灌') is True
    row = fetch_one('SELECT * FROM plans WHERE id=?', (result['plan_id'],))
    assert row['status'] == 'rejected'
    assert '人工拒绝' in row['reasoning']
    assert '水量够，不用灌' in row['reasoning']
    assert planner.reject_plan(uid, result['plan_id']) is False
    assert planner.reject_plan(uid + 999, result['plan_id']) is False


def test_list_plans_orders_desc_and_limits(client, registered):
    """列表按 ts 倒序，limit 生效，rid 为 1 基序号。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    for index in range(3):
        _insert_plan(uid, 1_700_000_000_000 + index * 1000)

    plans = planner.list_plans(uid, limit=2)
    assert len(plans) == 2
    assert [item['rid'] for item in plans] == [1, 2]
    assert plans[0]['ts'] > plans[1]['ts']
    assert planner.list_plans(uid, limit=999) and len(planner.list_plans(uid, limit=999)) == 3


def test_update_telemetry_aliases_and_context_defaults(client, registered):
    """遥测缓存支持 MQTT 别名；缺失字段给安全默认值而不抛异常。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)

    empty = planner.build_context(uid)
    assert empty['water_mm'] == 0.0
    assert empty['rori'] is None
    assert empty['manual_mode'] in (0, 1)

    planner.update_telemetry(uid, waterlevel=4095, humidity=0, do_mgl=6.0, eh_mv=200)
    filled = planner.build_context(uid)
    assert filled['water_mm'] == 300.0
    assert filled['soil_pct'] == 100.0
    assert filled['do_mgl'] == 6.0
    assert filled['eh_mv'] == 200.0
    assert filled['rori'] is not None
    assert 0.0 <= filled['rori'] <= 100.0
    assert filled['rori_level']['code'] in (0, 1, 2)


def test_confirm_empty_action_plan_is_confirmed(client, registered, monkeypatch):
    """无动作预案确认后置 confirmed（无需下发）。"""
    client.post('/api/login', json={'username': registered[0], 'password': registered[1]})
    uid = _uid(client, registered)
    plan_id = _insert_plan(uid, actions=[])

    calls = []
    monkeypatch.setattr(iot, 'send_property_command', lambda u, p: calls.append(p) or True)
    result = planner.confirm_plan(uid, plan_id)

    assert result['ok'] is True
    assert result['applied'] == []
    assert calls == []
    assert fetch_one('SELECT status FROM plans WHERE id=?', (plan_id,))['status'] == 'confirmed'
