"""青禾智灌 —— 请求入参校验工具。

集中处理「JSON 字段类型混淆」这一类输入：`data.get(key) or ''` 只能兜住 falsy
值（None / '' / 0 / False），对 int / list / dict 等 truthy 的非字符串会直接
`.strip()` 抛 `AttributeError` → 500。所有写接口都应经本模块取值，非法类型
返回 400 而不是 500（AGENTS.md 硬性规则）。

本模块**不得**导入其他 qinghe 子模块，以免形成循环依赖。
"""

import math

# 地块 id 的合法区间：既要挡住 SQLite INTEGER 溢出（|id| > 2**63-1 会
# OverflowError → 500），也要留足业务余量。与 qinghe/config.py 解耦，
# 避免校验工具反向依赖业务配置。
FARM_ID_MIN = 1
FARM_ID_MAX = 999999999


class ValidationError(ValueError):
    """入参校验失败。`message` 为可直接返回给前端的固定文案。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def as_str(data, key, default=''):
    """从 JSON 字典取字符串字段。

    仅接受 `str`；`None` 与字段缺失返回 `default`；其他类型（int / float /
    list / dict / bool）抛 `ValidationError`，避免下游 `.strip()` 抛 500。

    :param data: 已解析的请求体字典（`request.json or {}`）
    :param key: 字段名
    :param default: 字段缺失或为 None 时的返回值
    """
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValidationError('参数 %s 类型错误，应为字符串' % key)
    return value


def as_stripped(data, key, default=''):
    """取字符串字段并去掉首尾空白（登录/注册用户名的常用形态）。"""
    return as_str(data, key, default).strip()


def as_int(data, key, default=None):
    """取整数字段。

    接受 `int`（排除 `bool`）与可解析的纯数字字符串；`None` / 缺失返回
    `default`；其他类型或不可解析的字符串抛 `ValidationError`。
    """
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValidationError('参数 %s 类型错误，应为整数' % key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise ValidationError('参数 %s 类型错误，应为整数' % key)
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            raise ValidationError('参数 %s 类型错误，应为整数' % key) from None
    raise ValidationError('参数 %s 类型错误，应为整数' % key)


def as_float(data, key, default=None):
    """取浮点字段。

    接受 `int`/`float`（`bool` 视为非法）与可解析的纯数字字符串；`None` /
    缺失返回 `default`；其他类型或不可解析的值抛 `ValidationError`。
    """
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValidationError('参数 %s 类型错误，应为数字' % key)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            raise ValidationError('参数 %s 类型错误，应为数字' % key) from None
    raise ValidationError('参数 %s 类型错误，应为数字' % key)


def as_bool(data, key, default=False):
    """取布尔字段。只接受真正的 `bool`，其他类型抛 `ValidationError`。"""
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValidationError('参数 %s 类型错误，应为布尔值' % key)


def truncated(data, key, default='', max_len=None):
    """取字符串字段并截断到 `max_len`（告警文案等自由文本用）。"""
    text = as_str(data, key, default)
    if max_len is not None:
        return text[:max_len]
    return text


def get_json_object(request):
    """解析请求体并要求其是 JSON 对象。

    - 请求体不是 JSON / Content-Type 不符时沿用 Flask 默认错误（415/400），
      与旧版行为一致；
    - 合法 JSON 但类型是字符串/数字/数组等非对象时抛 `ValidationError`，
      由调用方转成 400，而不是在 `data.get(...)` 处抛 500；
    - 空 body 被解析成 `None` 时按空对象处理（兼容旧版 `request.json or {}`）。

    :param request: Flask 的 `request` 对象
    """
    data = request.get_json()
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValidationError('请求体必须是 JSON 对象')
    return data


def _to_strict_int(value, name):
    """把入参转成 int，bool / 空值 / 非数字字符串一律抛 `ValidationError`。"""
    if value is None or isinstance(value, bool):
        raise ValidationError('%s 必须是整数' % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError('%s 必须是整数' % name)
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError('%s 必须是整数' % name)
        try:
            return int(text)
        except ValueError:
            raise ValidationError('%s 必须是整数' % name) from None
    raise ValidationError('%s 必须是整数' % name)


def parse_int_range(value, lo, hi, name='参数'):
    """把入参解析为 `[lo, hi]` 区间内的整数。

    `None` / 空串 / 布尔 / 非整数数字 / 非数字字符串 / 越界值都抛
    `ValidationError`，不会静默回退默认值或 clamp。

    :param value: 待校验的原始值
    :param lo: 允许的最小值（含）
    :param hi: 允许的最大值（含）
    :param name: 错误文案里的字段中文名
    """
    number = _to_strict_int(value, name)
    if not (lo <= number <= hi):
        raise ValidationError('%s 需在 %s~%s 之间' % (name, lo, hi))
    return number


def parse_float_range(value, lo, hi, name='参数'):
    """把入参解析为 `[lo, hi]` 区间内的有限浮点数。

    接受数字与数字字符串；`None`、布尔、空串、非数字、nan/inf、越界值都抛
    `ValidationError`。

    :param value: 待校验的原始值
    :param lo: 允许的最小值（含）
    :param hi: 允许的最大值（含）
    :param name: 错误文案里的字段中文名
    """
    if value is None or isinstance(value, bool):
        raise ValidationError('%s 必须是数字' % name)
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError('%s 必须是数字' % name)
        try:
            number = float(text)
        except ValueError:
            raise ValidationError('%s 必须是数字' % name) from None
    else:
        raise ValidationError('%s 必须是数字' % name)
    if not math.isfinite(number):
        raise ValidationError('%s 必须是有限数字' % name)
    if not (lo <= number <= hi):
        raise ValidationError('%s 需在 %s~%s 之间' % (name, lo, hi))
    return number


def parse_str_field(value, name, min_len=0, max_len=None, strip=False):
    """校验字符串字段并返回规整后的文本。

    - `None` 视为清空，返回空串；
    - 仅接受 `str`，数字/布尔/dict/list 抛 `ValidationError`（不再静默
      `str()` 成 "123" 后落库）；
    - `strip=True` 时去掉首尾空白，长度按去空白后的字符数计算；
    - 长度不在 `[min_len, max_len]` 内抛 `ValidationError`。

    :param value: 待校验的原始值
    :param name: 错误文案里的字段中文名
    :param min_len: 最小长度（含）
    :param max_len: 最大长度（含），None 表示不限制
    :param strip: 是否去掉首尾空白
    """
    if value is None:
        text = ''
    elif isinstance(value, str):
        text = value.strip() if strip else value
    else:
        raise ValidationError('%s 必须是字符串' % name)
    length = len(text)
    if max_len is None:
        if length < min_len:
            raise ValidationError('%s 长度不能少于 %d 字符' % (name, min_len))
    elif not (min_len <= length <= max_len):
        raise ValidationError('%s 长度需为 %d-%d 字符' % (name, min_len, max_len))
    return text


def parse_bool_strict(value, name, default=False):
    """严格布尔解析：只接受 true/false 与数字 0/1。

    字符串 `"true"` / `"false"` / `"0"` / `"1"` 以及其它数字一律抛
    `ValidationError`，避免 `"false"` 被 truthy 判断当成开启。
    `None` / 字段缺失返回 `default`。

    :param value: 待校验的原始值
    :param name: 错误文案里的字段中文名
    :param default: 入参为 None 时的返回值
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    raise ValidationError('%s 只接受 true/false/0/1' % name)
