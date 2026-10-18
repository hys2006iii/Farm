"""青禾智灌 —— 配置与阈值 HTTP 接口。

覆盖：/api/get_config、/api/save_config、/api/thresh_settings(GET/POST)。
修复点：非 dict 请求体不再 500（统一 400）、配置字段严格类型/长度/范围校验、
阈值与 manual_mode 严格校验、iot_port 类型/范围校验（非法值保留旧值）。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import config, db, irrigation, iot, validators

bp = Blueprint('config_api', __name__)

# 经纬度列的合法范围；与 farm_routes 共用同一套范围常量，避免两处校验漂移
_COORD_FIELDS = {'farm_lat': config.FARM_LAT_RANGE, 'farm_lng': config.FARM_LON_RANGE}
_WEBHOOK_URL_MAX_LEN = 500


def _reconnect_async(uid):
    """在后台守护线程里重建 MQTT 连接。

    `iot.connect_huawei_iot()` 内部的 `client.connect()` 超时可达 60 秒，
    同步执行会把 HTTP 请求线程一起卡死（华为云不可达时尤其明显）。这里改成
    异步：接口立即返回，连接结果由 SocketIO 的 `device_status` 事件推给前端。
    """
    import threading

    try:
        thread = threading.Thread(
            target=iot.connect_huawei_iot,
            args=(uid,),
            name='iot-reconnect-%s' % uid,
            daemon=True,
        )
        thread.start()
    except Exception:  # noqa: BLE001 - 线程起不来也不能影响配置保存结果
        pass


def _to_int(value, default=None):
    """宽松转 int：接受 int/float/数字字符串，其它返回 default。"""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value, default=None):
    """宽松转 float：接受 int/float/数字字符串，空值或非法返回 default。"""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


# 配置里所有文本字段的长度上限；未列出的列不限制（如阈值走专门接口）
_TEXT_FIELD_MAX = {
    'farm_name': config.FARM_NAME_MAX_LEN,
    'weather_domain': 200, 'ai_domain': 200, 'iot_host': 200,
    'iot_client_id': 100, 'iot_user': 100, 'iot_pass': 200, 'iot_device_id': 100,
    'iot_target_device_id': 100, 'iot_m2m_topic': 200, 'iot_cmd_topic': 200,
    'weather_key': 200, 'ai_key': 200, 'webhook_url': _WEBHOOK_URL_MAX_LEN,
    'pump_port': 20, 'air_pump_port': 20, 'water_sensor_port': 20, 'soil_sensor_port': 20,
}
_COORD_FIELD_NAMES = {'farm_lat': '纬度', 'farm_lng': '经度'}


def _validate_text_fields(data, values):
    """校验显式提交的文本字段（类型、长度、Webhook 前缀），合法值就地写回 values。"""
    for key, max_len in _TEXT_FIELD_MAX.items():
        if key not in data or data[key] is None or data[key] == config.MASK:
            continue
        text = validators.parse_str_field(data[key], key, max_len=max_len, strip=True)
        if key == 'webhook_url' and text and not text.startswith(('http://', 'https://')):
            raise validators.ValidationError('Webhook 地址必须以 http:// 或 https:// 开头')
        values[key] = text


def _validate_coords(data, values):
    """校验显式提交的经纬度（数字或数字字符串）；非法值 400 而不是写脏数据。"""
    for key, (low, high) in _COORD_FIELDS.items():
        if key not in data or data[key] is None or data[key] == config.MASK:
            continue
        raw = data[key]
        # 空字符串表示「清空坐标」，保留历史语义
        if isinstance(raw, str) and not raw.strip():
            values[key] = ''
            continue
        value = validators.parse_float_range(raw, low, high, _COORD_FIELD_NAMES[key])
        # 字符串按原样（去空格）写回，数字统一保留 6 位小数
        values[key] = raw.strip() if isinstance(raw, str) else round(value, 6)


#: 「本次显式提交了该坐标，但值为空（用户清空）」的哨兵。
#: 不能用 None：`db.save_active_farm_meta()` 把 None 解释成「不改动」，
#: 两者语义不同，混用会导致清空坐标后 farms 表仍留旧值。
_COORD_CLEARED = object()


def _explicit_coords(data) -> dict:
    """取出本次**显式提交**的经纬度（用于同步到地块记录）。

    三种情况分开表达：
      - 字段未提交 / 值为 None / 掩码占位 → 不出现在返回值里（不改动）；
      - 提交了空串 → 值为 `_COORD_CLEARED`（显式清空）；
      - 提交了数字 → 值为 float。

    `_validate_coords()` 为了兼容「空串 = 清空坐标」的语义会把空串写成 `''`；
    若这里再把它折成 `None` 传给 `db.save_active_farm_meta()`，会因为
    「参数为 None 表示不改动」的约定而**保留旧坐标** —— 用户清空经纬度后，
    `farms` 表里仍留着旧值，下次登录镜像回 `configs` 时坐标又冒出来。
    """
    out = {}
    for key in _COORD_FIELDS:
        if key not in data or data[key] is None or data[key] == config.MASK:
            continue
        raw = data[key]
        if isinstance(raw, str) and not raw.strip():
            out[key] = _COORD_CLEARED
        else:
            out[key] = _to_float(raw)
    return out


@bp.route('/api/get_config', methods=['GET'])
def api_get_config():
    """读取当前用户配置；敏感凭据不回显明文，已设置则返回掩码占位。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    cfg = db.load_config(session['user_id'])
    if not cfg:
        return jsonify({'error': '未找到配置'}), 404
    cfg = dict(cfg)
    # webhook_url 里常带钉钉机器人 access_token，与其它凭据一样不回显明文
    for key in ('iot_pass', 'weather_key', 'ai_key', 'webhook_url'):
        if cfg.get(key):
            cfg[key] = config.MASK
    return jsonify(cfg)


@bp.route('/api/save_config', methods=['POST'])
def api_save_config():
    """保存配置。

    - 敏感字段值为掩码占位（前端未改动）或 None 时保留数据库原值；
    - iot_port 校验为 1~65535 的整数，非法值保留旧值（避免 connect_huawei_iot
      里 int() 抛异常）。
    """
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    try:
        data = validators.get_json_object(request)
    except validators.ValidationError as exc:
        return jsonify({'error': exc.message}), exc.status
    uid = session['user_id']

    old_row = db.load_config(uid)
    old = dict(old_row) if old_row else {}

    def val(key):
        v = data.get(key)
        if v == config.MASK or v is None:
            return old.get(key)
        return v

    values = {col: val(col) for col in db.CONFIG_COLUMNS}
    try:
        _validate_text_fields(data, values)
        _validate_coords(data, values)
    except validators.ValidationError as exc:
        return jsonify({'error': exc.message}), exc.status

    # iot_port：非数字/越界一律保留旧值（旧值非法则回退默认端口）
    port = _to_int(data.get('iot_port'))
    if port is None or not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
        port = _to_int(old.get('iot_port'), config.IOT_PORT_DEFAULT)
        if not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
            port = config.IOT_PORT_DEFAULT
    values['iot_port'] = port

    db.save_config(uid, values)
    # 设置页改的农场名/经纬度同步到当前地块记录，避免 farms 表与 configs 漂移。
    # 坐标只同步「本次显式提交」的那一维：没提交的一维保持地块记录原值，
    # 提交了空串的一维才真正清空（见 _explicit_coords / _COORD_CLEARED）。
    try:
        coords = _explicit_coords(data)
        farm_meta = {}
        if values.get('farm_name'):
            farm_meta['name'] = values['farm_name']
        # 清空坐标用空串表达（save_active_farm_meta 把 None 解释为「不改动」）
        if coords.get('farm_lat') is _COORD_CLEARED:
            farm_meta['lat'] = ''
        elif 'farm_lat' in coords:
            farm_meta['lat'] = coords['farm_lat']
        if coords.get('farm_lng') is _COORD_CLEARED:
            farm_meta['lon'] = ''
        elif 'farm_lng' in coords:
            farm_meta['lon'] = coords['farm_lng']
        if farm_meta:
            db.save_active_farm_meta(uid, **farm_meta)
    except Exception:  # noqa: BLE001 - 地块同步失败不影响配置保存
        pass
    # 异步重连：避免 connect() 的 60s 超时阻塞请求线程
    _reconnect_async(uid)
    return jsonify({'status': 'success', 'message': '配置已更新'})


@bp.route('/api/thresh_settings', methods=['GET'])
def api_get_thresh():
    """读取当前用户的阈值与自动/手动模式设定。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    row = db.load_thresholds(session['user_id'])
    if not row:
        return jsonify(dict(config.THRESH_DEFAULTS))
    return jsonify(dict(row))


@bp.route('/api/thresh_settings', methods=['POST'])
def api_save_thresh():
    """保存阈值与自动/手动模式。

    所有入参先做类型校验再 clamp 到合法范围（湿度 0~100，水位 0~300），
    非法入参回退默认值而不是抛 500；最后保证下限不超过上限。
    """
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    uid = session['user_id']
    try:
        data = validators.get_json_object(request)
    except validators.ValidationError as exc:
        return jsonify({'error': exc.message}), exc.status

    def pick(key, low, high):
        raw = data.get(key)
        value = _to_int(raw, None)
        if value is None:
            value = config.THRESH_DEFAULTS[key]
        return irrigation.clamp(value, low, high)

    humi_down = pick('humi_down', config.HUMI_MIN, config.HUMI_MAX)
    humi_up = pick('humi_up', config.HUMI_MIN, config.HUMI_MAX)
    wl_down = pick('waterlevel_down', config.WATERLEVEL_MIN, config.WATERLEVEL_MAX)
    wl_up = pick('waterlevel_up', config.WATERLEVEL_MIN, config.WATERLEVEL_MAX)
    try:
        manual = 1 if validators.parse_bool_strict(
            data.get('manual_mode'), 'manual_mode', default=False) else 0
    except validators.ValidationError as exc:
        return jsonify({'error': exc.message}), exc.status
    # 基本约束：下限不超过上限
    humi_down = min(humi_down, humi_up)
    wl_down = min(wl_down, wl_up)

    db.save_thresholds(uid, humi_down, humi_up, wl_down, wl_up, manual)
    return jsonify({'status': 'success', 'message': '设定已保存'})
