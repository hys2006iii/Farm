"""青禾智灌 —— 外部接入的连通性自检。

设置页的「物联网接入 / 气象与降雨预测 / AI 助手 / 告警推送」四块都依赖外部服务，
填完参数后用户无法判断「到底通不通」：要等到设备数据不来、预报为空、AI 不回话
才发现填错了。本模块提供一组**只读探测**，用当前配置真连一次并把结果翻译成
人话（成功 / 失败原因 / 耗时），供设置页的「测试连接」按钮调用。

设计约束：
- 全部带 `timeout`，异常一律吞掉后返回结构化结果，绝不向上抛到请求栈；
- 探测本身**不写数据库**，也不触发 MQTT 重连、不落告警，纯只读；
- 返回值固定为 `{'ok': bool, 'message': str, 'detail': str}`，前端只需一套渲染逻辑；
- 密钥掩码占位（`config.MASK`）视为「未填写」，避免拿掩码去请求上游。
"""

import time

import requests

from qinghe import ai as ai_mod
from qinghe import config, db

#: 探测结果里 detail 的最大长度，避免把上游整页 HTML 塞进响应
DETAIL_MAX_LEN = 300

#: 四个可自检的目标，与设置页的分组一一对应
TARGETS = ('iot', 'weather', 'ai', 'webhook')


def _result(ok: bool, message: str, detail: str = '') -> dict:
    """构造统一的探测结果。"""
    return {'ok': bool(ok), 'message': message, 'detail': (detail or '')[:DETAIL_MAX_LEN]}


def _real_value(raw) -> str:
    """把配置值归一化成可用于请求的字符串；掩码占位与空白都视为「未填写」。"""
    text = (raw or '').strip() if isinstance(raw, str) else ''
    if not text or text == config.MASK:
        return ''
    return text


def _elapsed_ms(started: float) -> int:
    """把起点时间换算成毫秒耗时（取整，至少 1ms 便于显示非零）。"""
    return max(1, int((time.time() - started) * 1000))


def _load(uid: int):
    """读取用户配置行；没有配置返回 None。"""
    row = db.load_config(uid)
    return dict(row) if row else None


def test_iot(cfg) -> dict:
    """探测华为云 IoTDA 的 MQTT 接入参数是否填全、主机是否可达。

    只做「参数完整性 + TCP 可达性」：真正建立 MQTT 连接会走 `iot.connect_huawei_iot()`，
    它有 60s 级超时且会改变运行时连接状态，不适合放在一次点击里同步做。
    因此这里用 socket 连一下 8883/1883，能连上就说明域名与端口没填错。
    """
    import socket

    host = _real_value(cfg.get('iot_host'))
    device_id = _real_value(cfg.get('iot_device_id'))
    client_id = _real_value(cfg.get('iot_client_id'))
    username = _real_value(cfg.get('iot_user'))
    password = _real_value(cfg.get('iot_pass'))

    missing = []
    if not host:
        missing.append('接入地址')
    if not device_id:
        missing.append('设备 ID')
    if not client_id:
        missing.append('客户端 ID')
    if not username:
        missing.append('用户名')
    if not password:
        missing.append('口令')
    if missing:
        return _result(False, '参数未填全：%s' % '、'.join(missing))

    try:
        port = int(cfg.get('iot_port') or config.IOT_PORT_DEFAULT)
    except (TypeError, ValueError):
        port = config.IOT_PORT_DEFAULT

    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=config.TIMEOUT_WEBHOOK):
            pass
    except socket.gaierror:
        return _result(False, '域名解析失败：%s' % host, '请检查接入地址是否写错')
    except OSError as exc:
        return _result(False, '无法连接 %s:%d' % (host, port), str(exc))
    return _result(True, '接入地址可达（%s:%d，%dms）' % (host, port, _elapsed_ms(started)),
                   '仅验证域名与端口连通，实际 MQTT 登录结果见顶栏「华为云」状态')


def test_weather(cfg) -> dict:
    """用当前配置真请求一次和风天气 7 日预报。"""
    from qinghe import weather as weather_mod

    domain = _real_value(cfg.get('weather_domain')) or config.DEFAULT_WEATHER_DOMAIN
    key = _real_value(cfg.get('weather_key'))
    if not key:
        return _result(False, '未填写天气 API Key')

    lat = cfg.get('farm_lat')
    lon = cfg.get('farm_lng')
    if lat is None or lon is None:
        return _result(False, '未设置地块经纬度', '请先在地块管理里选点或手填经纬度')

    started = time.time()
    payload = weather_mod.fetch_forecast(domain, lon, lat, key)
    if weather_mod.forecast_failed(payload):
        return _result(False, '请求失败', str(payload.get('error') or payload))
    if str(payload.get('code')) != '200':
        return _result(False, '接口返回错误码 %s' % payload.get('code'),
                       str(payload.get('message') or payload)[:DETAIL_MAX_LEN])
    days = payload.get('daily') or []
    return _result(True, '连通正常（返回 %d 天预报，%dms）' % (len(days), _elapsed_ms(started)),
                   '数据源：%s' % domain)


def test_ai(cfg) -> dict:
    """用当前配置发一条最小对话请求，验证域名与 API Key。"""
    domain = _real_value(cfg.get('ai_domain')) or config.DEFAULT_AI_DOMAIN
    key = _real_value(cfg.get('ai_key'))
    if not key:
        return _result(False, '未填写 API Key')

    url = '%s/chat/completions' % ai_mod.normalize_base_url(domain).rstrip('/')
    if not ai_mod.is_public_http_url(url):
        return _result(False, 'AI 域名不允许指向本机或内网地址',
                       '请填写公开可访问的 https 地址')

    started = time.time()
    try:
        resp = requests.post(
            url,
            headers={'Authorization': 'Bearer %s' % key, 'Content-Type': 'application/json'},
            json={
                'model': 'deepseek-chat',
                'messages': [{'role': 'user', 'content': '连通性测试，请只回复 OK'}],
                'max_tokens': 8,
            },
            timeout=config.TIMEOUT_AI,
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败只回报，不向上抛
        return _result(False, '请求失败', '%s（网络不可达或超时）' % type(exc).__name__)

    if resp.status_code == 401:
        return _result(False, 'API Key 无效（HTTP 401）', (resp.text or '')[:DETAIL_MAX_LEN])
    if resp.status_code != 200:
        return _result(False, '接口返回异常（HTTP %s）' % resp.status_code,
                       (resp.text or '(空响应)')[:DETAIL_MAX_LEN])
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return _result(False, '返回非 JSON 内容', (resp.text or '')[:DETAIL_MAX_LEN])
    choices = body.get('choices') or []
    if not choices:
        return _result(False, '返回内容里没有 choices', str(body)[:DETAIL_MAX_LEN])
    return _result(True, '连通正常（%dms）' % _elapsed_ms(started), '模型已正常应答')


def test_webhook(cfg) -> dict:
    """向配置的 webhook 发一条测试消息。

    与 `alerts.notify_webhook()` 走同一套地址校验与请求格式，但**带关键词前缀**，
    满足钉钉机器人「消息必须包含关键词」的安全设置，否则会返回 310000 错误码
    而让人误判成「webhook 填错了」。
    """
    url = _real_value(cfg.get('webhook_url'))
    if not url:
        return _result(False, '未填写 Webhook 地址')
    if not (url.startswith('http://') or url.startswith('https://')):
        return _result(False, 'Webhook 地址必须以 http:// 或 https:// 开头')
    if not ai_mod.is_public_http_url(url):
        return _result(False, 'Webhook 不允许指向本机或内网地址',
                       '请填写公开可访问的地址')

    payload = {
        'msgtype': 'text',
        'text': {'content': '%s连通性测试\n'
                            '如果你在群里看到这条消息，说明告警推送配置正确。'
                            % config.ALERT_KEY_PREFIX},
    }
    started = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=config.TIMEOUT_WEBHOOK)
    except Exception as exc:  # noqa: BLE001
        return _result(False, '请求失败', '%s（网络不可达或超时）' % type(exc).__name__)

    if resp.status_code not in (200, 201):
        return _result(False, '推送失败（HTTP %s）' % resp.status_code,
                       (resp.text or '')[:DETAIL_MAX_LEN])
    # 钉钉/企业微信即使业务失败也回 200，真正的结果在 body 的 errcode/code 里
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - 有的机器人回空 body，HTTP 200 即视为成功
        return _result(True, '推送成功（%dms）' % _elapsed_ms(started), '请到群里确认收到消息')
    code = body.get('errcode', body.get('code', 0))
    if str(code) not in ('0', 'None'):
        return _result(False, '平台拒绝推送（code=%s）' % code,
                       str(body.get('errmsg') or body.get('msg') or body)[:DETAIL_MAX_LEN])
    return _result(True, '推送成功（%dms）' % _elapsed_ms(started), '请到群里确认收到消息')


#: 目标名 → 探测函数。新增目标时同时补 TARGETS 与前端按钮即可。
_HANDLERS = {
    'iot': test_iot,
    'weather': test_weather,
    'ai': test_ai,
    'webhook': test_webhook,
}


def run_test(uid: int, target: str) -> dict:
    """按目标名执行一次连通性探测。

    返回 `{'ok': bool, 'message': str, 'detail': str}`；未知目标返回 ok=False，
    由路由层翻译成 400。
    """
    handler = _HANDLERS.get((target or '').strip().lower())
    if handler is None:
        return _result(False, '未知的测试目标：%s' % target)
    cfg = _load(uid)
    if not cfg:
        return _result(False, '未找到配置，请先保存一次设置')
    try:
        return handler(cfg)
    except Exception as exc:  # noqa: BLE001 - 任何意外都翻译成可读失败，不抛 500
        return _result(False, '自检异常', '%s: %s' % (type(exc).__name__, exc))
