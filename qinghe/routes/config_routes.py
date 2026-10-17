"""青禾智灌 —— 配置与阈值 HTTP 接口。

覆盖：/api/get_config、/api/save_config、/api/thresh_settings(GET/POST)。
修复点：iot_port 类型/范围校验（非法值保留旧值）、阈值 int() 500 与 clamp、
所有连接一律关闭。
"""

from flask import Blueprint, jsonify, request, session

from qinghe import config, db, iot, irrigation

bp = Blueprint('config_api', __name__)


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


@bp.route('/api/get_config', methods=['GET'])
def api_get_config():
    """读取当前用户配置；敏感凭据不回显明文，已设置则返回掩码占位。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    cfg = db.load_config(session['user_id'])
    if not cfg:
        return jsonify({'error': '未找到配置'}), 404
    cfg = dict(cfg)
    for key in ('iot_pass', 'weather_key', 'ai_key'):
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
    data = request.json or {}
    uid = session['user_id']

    old_row = db.load_config(uid)
    old = dict(old_row) if old_row else {}

    def val(key):
        v = data.get(key)
        if v == config.MASK or v is None:
            return old.get(key)
        return v

    values = {col: val(col) for col in db.CONFIG_COLUMNS}

    # iot_port：非数字/越界一律保留旧值（旧值非法则回退默认端口）
    port = _to_int(data.get('iot_port'))
    if port is None or not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
        port = _to_int(old.get('iot_port'), config.IOT_PORT_DEFAULT)
        if not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
            port = config.IOT_PORT_DEFAULT
    values['iot_port'] = port

    db.save_config(uid, values)
    # 设置页改的农场名/经纬度同步到当前地块记录，避免 farms 表与 configs 漂移
    try:
        db.save_active_farm_meta(
            uid,
            name=values.get('farm_name') or None,
            lat=_to_float(values.get('farm_lat')),
            lon=_to_float(values.get('farm_lng')),
        )
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
    data = request.json or {}

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
    manual = 1 if data.get('manual_mode') else 0
    # 基本约束：下限不超过上限
    humi_down = min(humi_down, humi_up)
    wl_down = min(wl_down, wl_up)

    db.save_thresholds(uid, humi_down, humi_up, wl_down, wl_up, manual)
    return jsonify({'status': 'success', 'message': '设定已保存'})
