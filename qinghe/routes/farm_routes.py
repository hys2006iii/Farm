"""青禾智灌 —— 多农场（地块）HTTP 接口。

一个账号可以管理多块地；`configs` 只保存「当前生效地块」的名称与经纬度镜像，
真实地块清单在 `farms` 表。切地块后天气、逆地理、看板都自动跟着换。

统一约定：
- 未登录返回 401 + `{'status': 'error', 'message': '未授权'}`；
- 入参非法返回 400；业务不存在（地块不属于本人 / 只有最后一块）返回 400 而不是 500；
- 成功响应统一 `{'status': 'success', ...}`。
"""

import json

from flask import Blueprint, jsonify, request, session

from qinghe import config, db, validators

bp = Blueprint('farm_api', __name__)


def _current_uid():
    """取当前会话用户 id，未登录返回 None。"""
    return session.get('user_id')


def _fail(message, status=400):
    """统一错误响应。"""
    return jsonify({'status': 'error', 'message': message}), status


def _json_body():
    """解析 JSON 对象请求体。

    合法 JSON 但不是对象（字符串/数字/数组）时返回 (None, 400 响应)，
    避免下游 `data.get(...)` 抛 AttributeError → 500。
    """
    try:
        return validators.get_json_object(request), None
    except validators.ValidationError as exc:
        return None, _fail(exc.message, exc.status)


def _farm_id(data):
    """取并校验 farm_id：接受数字或数字字符串，必须在安全区间内。"""
    farm_id = validators.as_int(data, 'farm_id')
    if farm_id is None:
        return None
    if not (validators.FARM_ID_MIN <= farm_id <= validators.FARM_ID_MAX):
        raise validators.ValidationError(
            'farm_id 需在 %d~%d 之间' % (validators.FARM_ID_MIN, validators.FARM_ID_MAX)
        )
    return farm_id


def _validate_name(data):
    """校验地块名称：1–20 字符。"""
    name = validators.as_stripped(data, 'name')
    if not (config.FARM_NAME_MIN_LEN <= len(name) <= config.FARM_NAME_MAX_LEN):
        raise validators.ValidationError(
            '地块名称长度需为 %d-%d 字符'
            % (config.FARM_NAME_MIN_LEN, config.FARM_NAME_MAX_LEN)
        )
    return name


def _validate_pair(lat, lon):
    """校验经纬度范围，返回规整后的 (lat, lon) 或 (None, None)。"""
    if lat is None and lon is None:
        return None, None
    if lat is None or lon is None:
        raise validators.ValidationError('经纬度需要成对填写')
    lat_min, lat_max = config.FARM_LAT_RANGE
    lon_min, lon_max = config.FARM_LON_RANGE
    if not (lat_min <= lat <= lat_max):
        raise validators.ValidationError('纬度需在 -90 ~ 90 之间')
    if not (lon_min <= lon <= lon_max):
        raise validators.ValidationError('经度需在 -180 ~ 180 之间')
    return round(float(lat), 6), round(float(lon), 6)


def _validate_area(data):
    """校验地块面积（平方米），缺省 0。"""
    area = validators.as_float(data, 'area_m2', 0.0)
    if not (0 <= area <= config.FARM_AREA_MAX_M2):
        raise validators.ValidationError('地块面积需在 0 ~ 1000000 m² 之间')
    return round(float(area), 2)


def _normalize_polygon(value) -> str:
    """把前端传来的边界点序列规整成 JSON 字符串。

    接受两种形态：JSON 字符串（`'[[23.1,113.2], ...]'`）或已解析的 list。
    空值返回空串（表示只选了一个中心点，没有圈地）。
    """
    if value in (None, '', []):
        return ''
    if isinstance(value, str):
        if len(value) > config.FARM_POLYGON_MAX_LEN:
            raise validators.ValidationError('地块边界数据过长')
        try:
            points = json.loads(value)
        except ValueError:
            raise validators.ValidationError('地块边界不是合法 JSON') from None
    else:
        points = value
    if not isinstance(points, list):
        raise validators.ValidationError('地块边界应为坐标点数组')
    if len(points) > config.FARM_POLYGON_MAX_POINTS:
        raise validators.ValidationError('地块边界点数过多（上限 %d）'
                                         % config.FARM_POLYGON_MAX_POINTS)
    cleaned = []
    lat_min, lat_max = config.FARM_LAT_RANGE
    lon_min, lon_max = config.FARM_LON_RANGE
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise validators.ValidationError('地块边界点格式应为 [lat, lon]')
        try:
            plat, plon = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            raise validators.ValidationError('地块边界点必须是数字') from None
        if not (lat_min <= plat <= lat_max and lon_min <= plon <= lon_max):
            raise validators.ValidationError('地块边界点超出经纬度范围')
        cleaned.append([round(plat, 6), round(plon, 6)])
    return json.dumps(cleaned, ensure_ascii=False)


def _payload(farm):
    """地块 dict 加上是否当前生效的标记。"""
    if farm is None:
        return None
    return dict(farm)


@bp.route('/api/farms', methods=['GET'])
def api_list_farms():
    """列出本人所有地块与当前生效地块 id。"""
    uid = _current_uid()
    if uid is None:
        return _fail('未授权', 401)
    db.ensure_default_farm(uid)
    farms = db.list_farms(uid)
    return jsonify({
        'status': 'success',
        'active_id': db.get_active_farm_id(uid),
        'farms': farms,
    })


@bp.route('/api/farms', methods=['POST'])
def api_create_farm():
    """新建地块；第一条地块自动生效。"""
    uid = _current_uid()
    if uid is None:
        return _fail('未授权', 401)
    data, error = _json_body()
    if error:
        return error
    try:
        name = _validate_name(data)
        lat, lon = _validate_pair(
            validators.as_float(data, 'lat'), validators.as_float(data, 'lon')
        )
        area = _validate_area(data)
        polygon = _normalize_polygon(data.get('polygon'))
    except validators.ValidationError as exc:
        return _fail(exc.message, exc.status)
    if db.count_farms(uid) >= config.FARM_MAX_COUNT:
        return _fail('地块数量已达上限（%d 块）' % config.FARM_MAX_COUNT)
    farm_id = db.create_farm(uid, name, lat, lon, area, polygon)
    if not db.get_active_farm_id(uid):
        db.set_active_farm(uid, farm_id)
    return jsonify({
        'status': 'success',
        'message': '地块已创建',
        'farm': db.get_farm(uid, farm_id),
        'active_id': db.get_active_farm_id(uid),
    })


@bp.route('/api/farms/switch', methods=['POST'])
def api_switch_farm():
    """切换当前地块：同步镜像名称与坐标，并清空上一块地的实时遥测缓存。"""
    uid = _current_uid()
    if uid is None:
        return _fail('未授权', 401)
    data, error = _json_body()
    if error:
        return error
    try:
        farm_id = _farm_id(data)
    except validators.ValidationError as exc:
        return _fail(exc.message, exc.status)
    if farm_id is None:
        return _fail('缺少 farm_id')
    if not db.set_active_farm(uid, farm_id):
        return _fail('地块不存在', 400)
    # 切地后旧遥测不属于新地块，清掉避免看板串数据
    try:
        from qinghe import planner

        planner.reset_telemetry(uid)
    except Exception:  # noqa: BLE001 - 清缓存失败不应影响切换
        pass
    return jsonify({
        'status': 'success',
        'message': '已切换地块',
        'farm': db.get_farm(uid, farm_id),
        'active_id': farm_id,
    })


@bp.route('/api/farms/update', methods=['POST'])
def api_update_farm():
    """更新地块信息（名称 / 坐标 / 面积 / 圈地边界）。"""
    uid = _current_uid()
    if uid is None:
        return _fail('未授权', 401)
    data, error = _json_body()
    if error:
        return error
    try:
        farm_id = _farm_id(data)
    except validators.ValidationError as exc:
        return _fail(exc.message, exc.status)
    if not farm_id:
        farm_id = db.get_active_farm_id(uid)
    farm = db.get_farm(uid, farm_id) if farm_id else None
    if farm is None:
        return _fail('地块不存在')
    try:
        name = _validate_name(data) if 'name' in data else farm['name']
        if 'lat' in data or 'lon' in data:
            lat, lon = _validate_pair(
                validators.as_float(data, 'lat'), validators.as_float(data, 'lon')
            )
        else:
            lat, lon = farm['lat'], farm['lon']
        area = (_validate_area(data) if data.get('area_m2') is not None
                else farm['area_m2'])
        polygon = (_normalize_polygon(data.get('polygon'))
                   if 'polygon' in data else farm['polygon'])
    except validators.ValidationError as exc:
        return _fail(exc.message, exc.status)
    db.update_farm(uid, farm_id, name, lat, lon, area, polygon)
    if farm_id == db.get_active_farm_id(uid):
        db.set_active_farm(uid, farm_id)
    return jsonify({
        'status': 'success',
        'message': '地块信息已保存',
        'farm': db.get_farm(uid, farm_id),
    })


@bp.route('/api/farms/delete', methods=['POST'])
def api_delete_farm():
    """删除地块；最后一块不允许删。"""
    uid = _current_uid()
    if uid is None:
        return _fail('未授权', 401)
    data, error = _json_body()
    if error:
        return error
    try:
        farm_id = _farm_id(data)
    except validators.ValidationError as exc:
        return _fail(exc.message, exc.status)
    if not farm_id:
        return _fail('缺少 farm_id')
    if db.get_farm(uid, farm_id) is None:
        return _fail('地块不存在')
    if db.count_farms(uid) <= 1:
        return _fail('至少保留一块地，不能删除')
    db.delete_farm(uid, farm_id)
    if db.get_active_farm_id(uid) == farm_id:
        remaining = db.list_farms(uid)
        if remaining:
            db.set_active_farm(uid, remaining[0]['id'])
    return jsonify({
        'status': 'success',
        'message': '地块已删除',
        'active_id': db.get_active_farm_id(uid),
        'farms': db.list_farms(uid),
    })
