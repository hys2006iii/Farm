"""青禾智灌 —— NF7 服务端自动调控引擎（可选托管）。

背景：前端 JS 已经有一套自动调控，若服务端也自动下发会「双重下发」互相打架。
因此本引擎**默认关闭**（`is_enabled()` 查库无记录返回 False），必须由用户在界面上
显式开启后才接管。

工作方式：`evaluate(uid, telemetry)` 仅在开启时生效 ——
1. 用 `irrigation.decide_control` 依据 RORI / 水位滞回 / 降雨前馈算出目标动作；
2. 对同一设备加**滞回**：两次动作间隔不足 `AUTO_MIN_INTERVAL_SECONDS`（默认 60 秒）直接跳过；
3. 通过 `iot.send_property_command` 下发，成功才更新状态并写日志。

本模块不发起任何网络请求，无外部密钥时同样可用。
"""

import json
import threading
import time
from contextlib import closing

from qinghe import config, db, irrigation

# ============================================================
# 一、常量与模块级状态
# ============================================================

#: 同一设备两次自动动作的最小间隔（秒），防止抖动式反复开关
AUTO_MIN_INTERVAL_SECONDS = 60

#: 允许自动控制的设备
DEVICES = ('air_pump', 'water_pump')

#: 建表一次性标记
_schema_ready = False
_schema_lock = threading.Lock()

#: 评估串行锁：同一进程内避免两个线程同时下发
_eval_lock = threading.Lock()


def _ensure_schema() -> None:
    """懒建 auto_control 表（幂等，每个公开函数入口调用）。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with closing(db.get_db()) as conn:
            conn.execute(
                '''CREATE TABLE IF NOT EXISTS auto_control (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    last_action_ts INTEGER DEFAULT 0,
                    state_json TEXT DEFAULT ''
                )'''
            )
            conn.commit()
        _schema_ready = True


# ============================================================
# 二、小工具
# ============================================================


def _row_value(row, key, default=None):
    """安全读取 sqlite3.Row 的列；缺失或 NULL 返回默认值。"""
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


def _load_row(uid: int):
    """读取自动调控配置行，不存在返回 None。"""
    with closing(db.get_db()) as conn:
        return conn.execute(
            'SELECT * FROM auto_control WHERE user_id = ?', (int(uid),)
        ).fetchone()


def _load_state(uid: int) -> dict:
    """解析 state_json，异常或空值返回空 dict。"""
    row = _load_row(uid)
    try:
        data = json.loads(_row_value(row, 'state_json', '') or '{}')
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(uid: int, state: dict, last_action_ts) -> None:
    """写回状态 JSON 与最近动作时间（时间戳走毫秒）。"""
    payload = json.dumps(state, ensure_ascii=False)
    with closing(db.get_db()) as conn:
        cursor = conn.execute(
            'UPDATE auto_control SET last_action_ts = ?, state_json = ? WHERE user_id = ?',
            (int(last_action_ts or 0), payload, int(uid)),
        )
        if cursor.rowcount == 0:
            conn.execute(
                'INSERT INTO auto_control (user_id, enabled, last_action_ts, state_json)'
                ' VALUES (?, 1, ?, ?)',
                (int(uid), int(last_action_ts or 0), payload),
            )
        conn.commit()


def _add_log(uid: int, message: str, level: str = 'info') -> None:
    """写运行日志（NF2 未就绪时静默跳过，绝不向上抛）。"""
    try:
        from qinghe import logbook

        logbook.add_log(uid, message, level=level, source='auto')
    except Exception:
        pass


def _load_thresholds(uid: int) -> dict:
    """读取用户阈值，缺省回落到 config.THRESH_DEFAULTS。"""
    row = None
    try:
        row = db.load_thresholds(uid)
    except Exception:
        row = None
    return {key: _row_value(row, key, default) for key, default in config.THRESH_DEFAULTS.items()}


# ============================================================
# 三、开关与状态
# ============================================================


def set_enabled(uid: int, enabled: bool) -> None:
    """开启 / 关闭服务端自动调控（默认关闭；关闭后 `evaluate` 立即不动作）。"""
    _ensure_schema()
    uid = int(uid)
    flag = 1 if enabled else 0
    with closing(db.get_db()) as conn:
        conn.execute(
            'INSERT INTO auto_control (user_id, enabled, last_action_ts, state_json)'
            ' VALUES (?, ?, 0, ?)'
            ' ON CONFLICT(user_id) DO UPDATE SET enabled = excluded.enabled',
            (uid, flag, ''),
        )
        conn.commit()
    _add_log(uid, '服务端自动调控已%s' % ('开启' if flag else '关闭'))


def is_enabled(uid: int) -> bool:
    """查询是否开启；查库无记录（从未设置）一律返回 False。"""
    _ensure_schema()
    try:
        row = _load_row(int(uid))
    except Exception:
        return False
    return bool(int(_row_value(row, 'enabled', 0) or 0))


def status(uid: int) -> dict:
    """返回 `{'enabled','last_action_ts','state'}`（未设置时 enabled=False）。"""
    _ensure_schema()
    uid = int(uid)
    try:
        row = _load_row(uid)
    except Exception:
        row = None
    state = {}
    try:
        parsed = json.loads(_row_value(row, 'state_json', '') or '{}')
        state = parsed if isinstance(parsed, dict) else {}
    except Exception:
        state = {}
    return {
        'enabled': bool(int(_row_value(row, 'enabled', 0) or 0)),
        'last_action_ts': int(_row_value(row, 'last_action_ts', 0) or 0),
        'state': state,
    }


# ============================================================
# 四、一次评估
# ============================================================


def evaluate(uid: int, telemetry: dict) -> list:
    """按最新遥测评估并下发动作，返回**实际下发成功**的动作列表。

    仅当用户开启自动调控时工作；同一设备距上次动作不足
    `AUTO_MIN_INTERVAL_SECONDS` 秒则跳过（滞回）。发送失败不更新状态，留待下次重试。
    """
    _ensure_schema()
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return []
    if not is_enabled(uid):
        return []
    if not isinstance(telemetry, dict):
        return []

    thresholds = _load_thresholds(uid)
    with _eval_lock:
        state = _load_state(uid)
        air_state = _normalize_switch((state.get('air_pump') or {}).get('state'))
        pump_state = _normalize_switch((state.get('water_pump') or {}).get('state'))
        # 状态缓存缺失时回落到本次遥测里的设备实际状态（避免误判为「变化」而重复下发）
        if air_state is None:
            air_state = _normalize_switch(telemetry.get('air_pump'))
        if pump_state is None:
            pump_state = _normalize_switch(telemetry.get('water_pump'))

        water_mm = _to_float(telemetry.get('water_mm'))
        if water_mm is None:
            water_mm = irrigation.adc_to_water_mm(telemetry.get('water_adc'))
        soil_pct = _to_float(telemetry.get('soil_pct'))
        if soil_pct is None:
            soil_pct = irrigation.adc_to_soil_pct(telemetry.get('soil_adc'))
        rori = _to_float(telemetry.get('rori'))
        water_adc = telemetry.get('water_adc')
        soil_adc = telemetry.get('soil_adc')
        rori_known = rori is not None
        if not rori_known:
            # 缺 RORI 时用溶解氧 + 氧化还原电位现算；两者也缺则视为「水质未知」，不碰气泵
            do_mgl = _to_float(telemetry.get('do_mgl'))
            if do_mgl is None:
                do_mgl = _to_float(telemetry.get('do'))
            eh_mv = _to_float(telemetry.get('eh_mv'))
            if eh_mv is None:
                eh_mv = _to_float(telemetry.get('eh'))
            if None not in (water_adc, soil_adc, do_mgl, eh_mv):
                rori = irrigation.compute_rori(water_adc, soil_adc, do_mgl, eh_mv)
                rori_known = True
        precips = telemetry.get('precips')
        if not isinstance(precips, list):
            precips = []
        dt = irrigation.compute_dynamic_threshold(
            thresholds['humi_down'], thresholds['humi_up'], precips
        )
        decision = irrigation.decide_control(
            float(water_mm or 0.0), float(soil_pct or 0.0), float(rori or 0.0),
            thresholds,
            {'air': air_state.upper() if air_state else None, 'pump': pump_state},
            dt,
        )

        candidates = []
        air = decision.get('air') or {}
        if air.get('changed') and rori_known:
            candidates.append({
                'device': 'air_pump',
                'action': 'on' if air.get('state') == 'ON' else 'off',
                'reason': air.get('reason') or '',
            })
        pump = decision.get('pump') or {}
        if pump.get('command'):
            candidates.append({
                'device': 'water_pump',
                'action': 'on' if pump.get('command') == 'ON' else 'off',
                'reason': pump.get('reason') or '',
            })
        if not candidates:
            return []

        now_ms = int(time.time() * 1000)
        applied = []
        for item in candidates:
            device = item['device']
            if device not in DEVICES:
                continue
            device_slot = state.get(device)
            if not isinstance(device_slot, dict):
                device_slot = {}
            last_ts = int(_to_float(device_slot.get('ts')) or 0)
            if last_ts and now_ms - last_ts < AUTO_MIN_INTERVAL_SECONDS * 1000:
                continue
            ok = False
            try:
                from qinghe import iot

                ok = bool(iot.send_property_command(uid, {device: item['action']}))
            except Exception:
                ok = False
            if not ok:
                continue
            device_slot['state'] = item['action']
            device_slot['ts'] = now_ms
            state[device] = device_slot
            applied.append(item)
            _add_log(uid, '自动调控下发 %s→%s（%s）' % (device, item['action'], item['reason']))

        if applied:
            _save_state(uid, state, now_ms)
        return applied
