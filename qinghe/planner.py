"""青禾智灌 —— NF4 AI 决策预案闭环（Human-in-the-Loop Planner）。

职责：
- `update_telemetry()` 维护模块级最新遥测缓存（供 MQTT 回调线程写入）；
- `build_context()` 汇总感知上下文快照（遥测缓存 + 阈值 + 可选天气前馈）；
- `propose_plan()` 生成「待人工确认」的预案：优先调用用户配置的 AI（要求只输出 JSON），
  无 Key / 网络失败 / 解析失败时**回退到规则方案**（RORI 分级 + 水位滞回 + 降雨前馈）；
- `confirm_plan()` 人工确认后逐条下发（只允许 air_pump / water_pump 的 on / off），
  校验归属、pending 状态与 600 秒 TTL；
- `reject_plan()` / `list_plans()` 人工拒绝与列表查询。

设计要点：本模块在**无网络、无外部密钥**的环境下必须可用，规则回退路径可离线演示；
日志与告警由 NF1/NF2 提供，这里用惰性 try/except 导入，拿不到就静默跳过。
"""

import json
import threading
import time
from contextlib import closing

import requests

from qinghe import ai, config, db, irrigation, weather

# ============================================================
# 一、常量与模块级状态
# ============================================================

#: 预案有效期（秒）：超过该时长仍未确认的预案自动置 expired 并拒绝执行
PLAN_TTL_SECONDS = 600

#: 允许下发的设备与动作白名单（防止模型幻觉或越权写设备）
ALLOWED_DEVICES = ('air_pump', 'water_pump')
ALLOWED_ACTIONS = ('on', 'off')

#: AI 调用超时（秒）。预案要输出结构化 JSON，比通用对话留更多时间
AI_TIMEOUT_SECONDS = 25

#: plans.status 取值
STATUS_PENDING = 'pending'
STATUS_CONFIRMED = 'confirmed'
STATUS_REJECTED = 'rejected'
STATUS_EXPIRED = 'expired'
STATUS_FAILED = 'failed'

#: 预案系统提示词：强制只输出 JSON，并限定可控制设备
PLANNER_SYSTEM_PROMPT = (
    '你是智慧灌溉系统的决策助手。只输出一个 JSON 对象，不要输出解释文字、Markdown 或代码块围栏。'
    'JSON 结构：{"reasoning": "推理过程（中文，必须含具体数值依据）", '
    '"actions": [{"device": "air_pump|water_pump", "action": "on|off", "reason": "理由"}], '
    '"summary": "一句话结论", "risk": "low|medium|high"}。'
    '只允许控制 air_pump（增氧气泵）与 water_pump（水泵），动作只能是 on 或 off。'
)

#: 遥测缓存：{uid: {字段: 值}}，由 MQTT 回调线程写入，请求线程读取
_latest = {}
_latest_lock = threading.Lock()

#: 建表一次性标记（模块级 + 锁，避免并发首次请求重复 DDL）
_schema_ready = False
_schema_lock = threading.Lock()

#: 遥测字段别名：语义名 + MQTT 物模型属性名
_WATER_ALIASES = ('water_adc', 'waterlevel', 'waterAdc')
_SOIL_ALIASES = ('soil_adc', 'humidity', 'soilAdc')
_AIR_ALIASES = ('air_pump', 'airPump', 'air')
_PUMP_ALIASES = ('water_pump', 'waterPump', 'pump')


def _ensure_schema() -> None:
    """懒建 plans 表与索引（幂等，每个公开函数入口调用）。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with closing(db.get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    context_json TEXT NOT NULL,
                    reasoning TEXT NOT NULL DEFAULT '',
                    proposal_json TEXT NOT NULL,
                    decided_ts INTEGER,
                    apply_result TEXT DEFAULT ''
                )'''
            )
            conn.execute('CREATE INDEX IF NOT EXISTS idx_plans_user_ts ON plans(user_id, ts)')
            conn.commit()
        _schema_ready = True


# ============================================================
# 二、通用小工具
# ============================================================


def _row_value(row, key, default=None):
    """安全读取 sqlite3.Row 的列；行缺失、列不存在或值为 NULL 时返回默认值。"""
    if row is None:
        return default
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _to_float(value):
    """尽力转 float，失败返回 None。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_value(snap: dict, *keys):
    """按候选键顺序取第一个非 None 值。"""
    for key in keys:
        if key in snap and snap[key] is not None:
            return snap[key]
    return None


def _normalize_switch(value):
    """把 on/off/True/False/1/0 归一成 'on' / 'off'，未知返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return 'on' if value else 'off'
    text = str(value).strip().lower()
    if text in ('1', 'true', 'on', 'open'):
        return 'on'
    if text in ('0', 'false', 'off', 'close'):
        return 'off'
    return None


def _normalize_risk(value) -> str:
    """把模型给出的风险等级归一成 low / medium / high。"""
    text = str(value or '').strip().lower()
    if text in ('high', 'danger', '高', '高风险', '严重'):
        return 'high'
    if text in ('medium', 'mid', 'warn', 'warning', '中', '中等', '中风险'):
        return 'medium'
    if text in ('low', 'safe', '低', '低风险', '安全'):
        return 'low'
    return 'low'


def _load_thresholds(uid: int) -> dict:
    """读取用户阈值，缺省回落到 config.THRESH_DEFAULTS，返回纯 dict。"""
    row = None
    try:
        row = db.load_thresholds(uid)
    except Exception:
        row = None
    return {key: _row_value(row, key, default) for key, default in config.THRESH_DEFAULTS.items()}


def _add_log(uid: int, message: str, level: str = 'info', source: str = 'plan') -> None:
    """写运行日志（NF2 未就绪时静默跳过，绝不向上抛）。"""
    try:
        from qinghe import logbook

        logbook.add_log(uid, message, level=level, source=source)
    except Exception:
        pass


def _push_alert(uid: int, level: str, code: str, content: str) -> None:
    """推送告警（NF1 未就绪时静默跳过，绝不向上抛）。"""
    try:
        from qinghe import alert_center

        alert_center.push_alert(uid, level, code, content)
    except Exception:
        pass


# ============================================================
# 三、遥测缓存与上下文
# ============================================================


def update_telemetry(uid: int, **kw) -> None:
    """写入最新遥测到模块级缓存（线程安全，供 MQTT 回调线程调用）。

    只保存非 None 字段；`ts` 缺省为当前毫秒时间戳。字段名同时接受
    MQTT 原始属性名（waterlevel / humidity）与语义名（water_adc / soil_adc）。
    """
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return
    now_ms = int(kw.get('ts') or time.time() * 1000)
    with _latest_lock:
        slot = _latest.setdefault(uid, {})
        for key, value in kw.items():
            if key == 'ts' or value is None:
                continue
            slot[str(key)] = value
        slot['ts'] = now_ms


def reset_telemetry(uid: int) -> None:
    """清空某用户的实时遥测缓存。

    切换地块 / 重置演示数据时调用：旧遥测属于上一块地，留着会让看板与
    AI 上下文串地块。
    """
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return
    with _latest_lock:
        _latest.pop(uid, None)


def _forecast_precips(uid: int):
    """取最近 6 日降雨预报（mm 列表）；无 Key / 请求失败 / 数据异常返回 None。"""
    try:
        row = db.load_weather_config(uid)
    except Exception:
        return None
    if not row:
        return None
    key = _row_value(row, 'weather_key', '')
    if not key:
        return None
    domain = _row_value(row, 'weather_domain', '') or config.DEFAULT_WEATHER_DOMAIN
    lng = _row_value(row, 'farm_lng', '') or '118.78'
    lat = _row_value(row, 'farm_lat', '') or '31.90'
    try:
        data = weather.fetch_forecast(domain, lng, lat, key)
    except Exception:
        return None
    if not isinstance(data, dict) or str(data.get('code')) not in ('200', '0'):
        return None
    precips = []
    for item in data.get('daily') or []:
        precips.append(_to_float((item or {}).get('precip')) or 0.0)
    return precips or None


def forecast_precips(uid: int):
    """公开封装：取未来 6 日报雨（mm 列表）；无 Key / 失败返回 None。

    七日灌溉建议等只读功能复用它，避免和 `build_context()` 各打一次天气接口。
    """
    return _forecast_precips(uid)


def build_context(uid: int, precips=None) -> dict:
    """汇总感知上下文快照（遥测缓存 + 阈值 + 可选天气前馈）。

    返回字段与规格逐字一致：`rori`、`rori_level`（code/name/strategy）、`water_mm`、
    `soil_pct`、`do_mgl`、`eh_mv`、`air_pump`、`water_pump`、`p6d`、`alpha`、
    `eff_lower`、`eff_upper`、`manual_mode`、`ts`。
    遥测缺失的字段按安全默认值填充（数值取 0，无法判定的取 None），不抛异常。

    参数:
        precips: 可选，已取到的 6 日报雨列表；传入则不再请求天气接口。
    """
    _ensure_schema()
    uid = int(uid)
    with _latest_lock:
        snap = dict(_latest.get(uid) or {})

    thresholds = _load_thresholds(uid)
    humi_down = thresholds['humi_down']
    humi_up = thresholds['humi_up']

    water_adc = _first_value(snap, *_WATER_ALIASES)
    soil_adc = _first_value(snap, *_SOIL_ALIASES)
    water_mm = _to_float(snap.get('water_mm'))
    if water_mm is None:
        water_mm = irrigation.adc_to_water_mm(water_adc)
    soil_pct = _to_float(snap.get('soil_pct'))
    if soil_pct is None:
        soil_pct = irrigation.adc_to_soil_pct(soil_adc)
    do_mgl = _to_float(_first_value(snap, 'do_mgl', 'do', 'dissolved_oxygen'))
    eh_mv = _to_float(_first_value(snap, 'eh_mv', 'eh', 'redox'))

    rori = _to_float(snap.get('rori'))
    if rori is None and None not in (water_adc, soil_adc, do_mgl, eh_mv):
        rori = irrigation.compute_rori(water_adc, soil_adc, do_mgl, eh_mv)

    precips = _forecast_precips(uid) if precips is None else precips
    dynamic = irrigation.compute_dynamic_threshold(humi_down, humi_up, precips or [])

    return {
        'rori': None if rori is None else round(float(rori), 2),
        'rori_level': irrigation.classify_rori(0.0 if rori is None else rori),
        'water_mm': round(float(water_mm), 2),
        'soil_pct': round(float(soil_pct), 2),
        'do_mgl': do_mgl,
        'eh_mv': eh_mv,
        'air_pump': _normalize_switch(_first_value(snap, *_AIR_ALIASES)),
        'water_pump': _normalize_switch(_first_value(snap, *_PUMP_ALIASES)),
        'p6d': round(float(dynamic['P6d']), 2),
        'alpha': dynamic['alpha'],
        'eff_lower': round(float(dynamic['effLower']), 2),
        'eff_upper': round(float(dynamic['effUpper']), 2),
        'manual_mode': int(thresholds.get('manual_mode') or 0),
        'ts': int(snap.get('ts') or time.time() * 1000),
        # 是否真的收到过遥测：用来区分「0 mm 的真读数」与「没有数据的安全默认值」
        'has_telemetry': bool(snap),
    }


# ============================================================
# 四、方案生成：AI 优先，规则回退
# ============================================================


def _build_ai_prompt(ctx: dict, question: str) -> str:
    """把上下文快照序列化进提示词，要求模型给出可执行预案。"""
    lines = [
        '当前感知上下文（JSON）：',
        json.dumps(ctx, ensure_ascii=False, sort_keys=True),
        '',
        '阈值约定：RORI≥%d 重度厌氧、≥%d 中度缺氧；水泵按水位滞回控制。'
        % (config.RORI_HEAVY, config.RORI_MODERATE),
    ]
    if question:
        lines.append('用户补充问题：%s' % question)
    lines.append('请判断是否需要开关气泵/水泵，只输出约定结构的 JSON。')
    return '\n'.join(lines)


def _extract_json_object(text):
    """从模型输出里抠出 JSON 对象（容忍 Markdown 代码块围栏与前后废话）。"""
    if not text:
        return None
    raw = str(text).strip()
    if raw.startswith('```'):
        raw = '\n'.join(ln for ln in raw.splitlines() if not ln.strip().startswith('```')).strip()
    start = raw.find('{')
    end = raw.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except Exception:
        return None


def _sanitize_actions(raw_actions) -> list:
    """过滤白名单外的设备/动作，返回干净的 actions 列表（非法项直接丢弃）。"""
    actions = []
    for item in raw_actions or []:
        if not isinstance(item, dict):
            continue
        device = str(item.get('device') or '').strip().lower()
        action = str(item.get('action') or '').strip().lower()
        if device not in ALLOWED_DEVICES or action not in ALLOWED_ACTIONS:
            continue
        actions.append({
            'device': device,
            'action': action,
            'reason': str(item.get('reason') or '').strip()[:300],
        })
    return actions


def _ai_plan(uid: int, ctx: dict, question: str):
    """调用用户配置的 AI 生成预案；无 Key / 网络失败 / 解析失败均返回 None。"""
    try:
        row = db.load_ai_config(uid)
    except Exception:
        return None
    key = _row_value(row, 'ai_key', '')
    if not key:
        return None
    domain = _row_value(row, 'ai_domain', '')
    url = '%s/chat/completions' % ai.normalize_base_url(domain).rstrip('/')
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer %s' % key}
    body = {
        'model': config.DEFAULT_AI_MODEL,
        'messages': [
            {'role': 'system', 'content': PLANNER_SYSTEM_PROMPT},
            {'role': 'user', 'content': _build_ai_prompt(ctx, question)},
        ],
        'stream': False,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=AI_TIMEOUT_SECONDS)
    except Exception:
        return None
    if getattr(resp, 'status_code', 0) != 200:
        return None
    try:
        payload = resp.json()
        text = payload['choices'][0]['message']['content']
    except Exception:
        return None
    data = _extract_json_object(text)
    if not isinstance(data, dict):
        return None
    reasoning = str(data.get('reasoning') or '').strip()
    if not reasoning:
        return None
    return {
        'reasoning': reasoning[:4000],
        'actions': _sanitize_actions(data.get('actions')),
        'summary': str(data.get('summary') or '').strip()[:500],
        'risk': _normalize_risk(data.get('risk')),
    }


def _rule_reasoning(ctx: dict, decision: dict, thresholds: dict, dt: dict, rori) -> str:
    """拼装规则回退推理文本：必须写明 RORI 分级 / 水位滞回 / 降雨前馈的具体数值。"""
    level = decision.get('level') or {}
    water = float(ctx.get('water_mm') or 0.0)
    p6d = float(dt.get('P6d') or 0.0)
    alpha = float(dt.get('alpha') or 0.0)
    if rori is None:
        rori_text = '缺失（按 0.00 保守处理）'
    else:
        rori_text = '%.2f' % float(rori)
    if p6d > 0:
        rain_text = ('P6d=%.1fmm、α=%.2f，预测有降雨：水泵控水等雨、气泵提前一级增氧'
                     % (p6d, alpha))
    else:
        rain_text = 'P6d=0.0mm、α=%.2f，无降雨预报：不触发控水等雨，按基础阈值灌溉' % alpha
    air = decision.get('air') or {}
    pump = decision.get('pump') or {}
    parts = [
        '【规则回退·非 AI 推理】',
        'RORI=%s，分级 %s（重度阈值 %d、中度阈值 %d，含前馈后的有效控制等级 %d）；'
        % (rori_text, level.get('name', '未知'), config.RORI_HEAVY, config.RORI_MODERATE,
           decision.get('effective_code', 0)),
        '水位滞回：当前 %.2fmm 对照 [下限 %smm, 上限 %smm]，区间内不动作；'
        % (water, thresholds.get('waterlevel_down'), thresholds.get('waterlevel_up')),
        '有效湿度区间 [%.1f%%, %.1f%%]；' % (
            float(ctx.get('eff_lower') or 0.0), float(ctx.get('eff_upper') or 0.0)),
        '降雨前馈：%s；' % rain_text,
        '结论：%s；%s。' % (air.get('reason', ''), pump.get('reason', '')),
    ]
    return ''.join(parts)


def _rule_plan(uid: int, ctx: dict) -> dict:
    """规则回退方案：用 irrigation.decide_control 生成 actions（离线可用）。"""
    thresholds = _load_thresholds(uid)
    p6d = float(ctx.get('p6d') or 0.0)
    dt = {
        'P6d': p6d,
        'alpha': ctx.get('alpha'),
        'effLower': ctx.get('eff_lower'),
        'effUpper': ctx.get('eff_upper'),
        'rainComing': p6d > 0,
    }
    air_state = ctx.get('air_pump')
    state = {
        'air': air_state.upper() if air_state else None,
        'pump': ctx.get('water_pump'),
    }
    rori = ctx.get('rori')
    rori_value = float(rori) if rori is not None else 0.0
    decision = irrigation.decide_control(
        ctx.get('water_mm') or 0.0, ctx.get('soil_pct') or 0.0, rori_value,
        thresholds, state, dt,
    )

    actions = []
    air = decision.get('air') or {}
    if air.get('changed'):
        actions.append({
            'device': 'air_pump',
            'action': 'on' if air.get('state') == 'ON' else 'off',
            'reason': air.get('reason') or '',
        })
    pump = decision.get('pump') or {}
    if pump.get('command'):
        actions.append({
            'device': 'water_pump',
            'action': 'on' if pump.get('command') == 'ON' else 'off',
            'reason': pump.get('reason') or '',
        })

    if actions:
        summary = '拟下发 %d 条指令：%s' % (
            len(actions), '；'.join('%s→%s' % (a['device'], a['action']) for a in actions))
    else:
        summary = '当前指标处于目标区间，无需下发指令'
    if rori is not None and rori >= config.RORI_HEAVY:
        risk = 'high'
    elif rori is not None and rori >= config.RORI_MODERATE:
        risk = 'medium'
    else:
        risk = 'low'
    return {
        'reasoning': _rule_reasoning(ctx, decision, thresholds, dt, rori),
        'actions': actions,
        'summary': summary,
        'risk': risk,
    }


def _insert_plan(uid: int, ts: int, ctx: dict, payload: dict) -> int:
    """落库一条待确认预案，返回自增 plan id。"""
    proposal = {
        'actions': payload.get('actions') or [],
        'summary': payload.get('summary') or '',
        'risk': payload.get('risk') or 'low',
    }
    with closing(db.get_db()) as conn:
        cursor = conn.execute(
            'INSERT INTO plans (user_id, ts, status, context_json, reasoning, proposal_json)'
            ' VALUES (?, ?, ?, ?, ?, ?)',
            (
                int(uid), int(ts), STATUS_PENDING,
                json.dumps(ctx, ensure_ascii=False),
                payload.get('reasoning') or '',
                json.dumps(proposal, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def propose_plan(uid: int, question: str = '') -> dict:
    """生成一条待人工确认的决策预案。

    优先走 AI（要求只输出 JSON）；无 Key / 网络失败 / 解析失败一律回退规则方案，
    因此本函数在离线环境 100% 可用。落 `plans` 表（status=pending）并返回
    `{'plan_id','status','reasoning','actions','summary','risk','ai_used'}`。
    """
    _ensure_schema()
    uid = int(uid)
    question = (question or '').strip()[:500]
    ctx = build_context(uid)

    payload = _ai_plan(uid, ctx, question)
    ai_used = payload is not None
    if payload is None:
        payload = _rule_plan(uid, ctx)

    plan_id = _insert_plan(uid, int(time.time() * 1000), ctx, payload)
    return {
        'plan_id': plan_id,
        'status': STATUS_PENDING,
        'reasoning': payload['reasoning'],
        'actions': payload['actions'],
        'summary': payload['summary'],
        'risk': payload['risk'],
        'ai_used': ai_used,
    }


# ============================================================
# 五、人工确认 / 拒绝 / 列表
# ============================================================


def _load_plan(plan_id: int):
    """按 id 取预案行，不存在返回 None。"""
    with closing(db.get_db()) as conn:
        return conn.execute('SELECT * FROM plans WHERE id = ?', (int(plan_id),)).fetchone()


def _load_proposal(row) -> dict:
    """解析 proposal_json，异常时返回空结构。"""
    try:
        data = json.loads(_row_value(row, 'proposal_json', '') or '{}')
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _update_plan(plan_id: int, status: str, decided_ts: int, apply_result=None) -> None:
    """更新预案状态（可选写入下发结果 JSON）。"""
    with closing(db.get_db()) as conn:
        if apply_result is None:
            conn.execute(
                'UPDATE plans SET status=?, decided_ts=? WHERE id=?',
                (status, int(decided_ts), int(plan_id)),
            )
        else:
            conn.execute(
                'UPDATE plans SET status=?, decided_ts=?, apply_result=? WHERE id=?',
                (status, int(decided_ts), apply_result, int(plan_id)),
            )
        conn.commit()


def _format_actions(actions) -> str:
    """把动作列表拼成一行可读文本（写日志用）。"""
    return '、'.join('%s→%s' % (a.get('device'), a.get('action')) for a in actions) or '无'


def confirm_plan(uid: int, plan_id: int) -> dict:
    """人工确认预案：校验归属 / pending 状态 / TTL 后逐条下发。

    只允许下发 `air_pump` / `water_pump` + `on` / `off`，白名单外的动作记为失败；
    成功下发后写日志（source=plan）与告警（code=auto_action）。
    返回 `{'ok','applied','failed','status','error'}`。
    """
    _ensure_schema()
    uid = int(uid)
    plan_id = int(plan_id)
    row = _load_plan(plan_id)
    if row is None:
        return {'ok': False, 'applied': [], 'failed': [], 'error': '预案不存在'}
    if int(_row_value(row, 'user_id', 0)) != uid:
        return {'ok': False, 'applied': [], 'failed': [], 'error': '预案不存在或无权操作'}
    if _row_value(row, 'status', '') != STATUS_PENDING:
        return {
            'ok': False, 'applied': [], 'failed': [],
            'error': '预案状态为 %s，不可确认' % _row_value(row, 'status', ''),
        }

    now_ms = int(time.time() * 1000)
    if now_ms - int(_row_value(row, 'ts', 0)) > PLAN_TTL_SECONDS * 1000:
        _update_plan(plan_id, STATUS_EXPIRED, now_ms)
        return {
            'ok': False, 'applied': [], 'failed': [],
            'error': '预案已过期（超过 %d 秒）' % PLAN_TTL_SECONDS,
        }

    proposal = _load_proposal(row)
    raw_actions = proposal.get('actions') or []
    applied = []
    failed = []
    for item in raw_actions:
        if not isinstance(item, dict):
            failed.append({'device': '', 'action': '', 'error': '非法动作结构'})
            continue
        device = str(item.get('device') or '').strip().lower()
        action = str(item.get('action') or '').strip().lower()
        if device not in ALLOWED_DEVICES or action not in ALLOWED_ACTIONS:
            failed.append({'device': device, 'action': action, 'error': '非法的设备或动作'})
            continue
        ok = False
        try:
            from qinghe import iot

            ok = bool(iot.send_property_command(uid, {device: action}))
        except Exception:
            ok = False
        if ok:
            applied.append({'device': device, 'action': action})
        else:
            failed.append({'device': device, 'action': action, 'error': '下发失败或设备未连接'})

    if applied or not raw_actions:
        status = STATUS_CONFIRMED
    else:
        status = STATUS_FAILED
    apply_result = json.dumps({'applied': applied, 'failed': failed}, ensure_ascii=False)
    _update_plan(plan_id, status, now_ms, apply_result)

    if applied:
        _add_log(uid, '预案 #%d 已确认执行：%s' % (plan_id, _format_actions(applied)), source='plan')
        _push_alert(uid, 'info', 'auto_action',
                    '预案 #%d 已下发 %d 条设备指令' % (plan_id, len(applied)))
    return {
        'ok': status == STATUS_CONFIRMED,
        'applied': applied,
        'failed': failed,
        'status': status,
        'plan_id': plan_id,
    }


def reject_plan(uid: int, plan_id: int, reason: str = '') -> bool:
    """人工拒绝预案：仅限本人 pending 预案，拒绝原因追加到 reasoning 末尾。"""
    _ensure_schema()
    uid = int(uid)
    plan_id = int(plan_id)
    row = _load_plan(plan_id)
    if row is None or int(_row_value(row, 'user_id', 0)) != uid:
        return False
    if _row_value(row, 'status', '') != STATUS_PENDING:
        return False

    note = (reason or '').strip()[:200]
    reasoning = _row_value(row, 'reasoning', '') or ''
    if note:
        reasoning = (reasoning + '\n【人工拒绝】' + note)[:4000]
    with closing(db.get_db()) as conn:
        conn.execute(
            'UPDATE plans SET status=?, decided_ts=?, reasoning=? WHERE id=?',
            (STATUS_REJECTED, int(time.time() * 1000), reasoning, plan_id),
        )
        conn.commit()
    _add_log(uid, '预案 #%d 已被人工拒绝%s' % (plan_id, ('：' + note) if note else ''), source='plan')
    return True


def list_plans(uid: int, limit: int = 20) -> list:
    """按时间倒序列出本人预案（rid 为 1 基序号），limit clamp 到 1~100。"""
    _ensure_schema()
    uid = int(uid)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))
    with closing(db.get_db()) as conn:
        rows = conn.execute(
            'SELECT * FROM plans WHERE user_id = ? ORDER BY ts DESC, id DESC LIMIT ?',
            (uid, limit),
        ).fetchall()

    result = []
    for index, row in enumerate(rows, start=1):
        proposal = _load_proposal(row)
        try:
            context = json.loads(_row_value(row, 'context_json', '') or '{}')
        except Exception:
            context = {}
        result.append({
            'rid': index,
            'id': _row_value(row, 'id'),
            'ts': _row_value(row, 'ts'),
            'status': _row_value(row, 'status', ''),
            'reasoning': _row_value(row, 'reasoning', ''),
            'actions': proposal.get('actions') or [],
            'summary': proposal.get('summary') or '',
            'risk': proposal.get('risk') or '',
            'decided_ts': _row_value(row, 'decided_ts'),
            'apply_result': _row_value(row, 'apply_result', ''),
            'context': context,
        })
    return result
