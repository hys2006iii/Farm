"""青禾智灌 —— 请求入参校验工具。

集中处理「JSON 字段类型混淆」这一类输入：`data.get(key) or ''` 只能兜住 falsy
值（None / '' / 0 / False），对 int / list / dict 等 truthy 的非字符串会直接
`.strip()` 抛 `AttributeError` → 500。所有写接口都应经本模块取值，非法类型
返回 400 而不是 500（AGENTS.md 硬性规则）。

本模块**不得**导入其他 qinghe 子模块，以免形成循环依赖。
"""


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
