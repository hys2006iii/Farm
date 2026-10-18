"""青禾智灌 —— AI 助手对话代理。

把前端 `/api/ai_chat` 的提问转发给用户配置的 OpenAI 兼容接口（默认 DeepSeek），
无论上游成功、失败还是返回非 JSON，都包装成前端认识的
`{'choices': [{'message': {'content': '...'}}]}` 结构，绝不向请求栈抛异常。
"""

import ipaddress

import requests

from qinghe import config, db

SYSTEM_PROMPT = '你是一个智能灌溉与水利控制系统助手，请简洁专业地回答中文问题。'


def _wrap(content: str) -> dict:
    """把纯文本包装成前端需要的 choices 结构。"""
    return {'choices': [{'message': {'content': content}}]}


#: 快照文本上限：太长会挤占模型上下文，只保留关键读数
SNAPSHOT_MAX_CHARS = 1800


def _num(value, digits=1, unit=''):
    """把可能为 None 的数值格式化成 `12.3 mm` 形式。"""
    if value is None:
        return '未知'
    try:
        return ('%.*f%s' % (digits, float(value), unit))
    except (TypeError, ValueError):
        return '未知'


def _trend(points, digits=1):
    """把按时间正序的数值序列压缩成「首→末」趋势描述。"""
    series = [p for p in points if p is not None]
    if len(series) < 2:
        return '样本不足'
    return '%.*f→%.*f' % (digits, series[0], digits, series[-1])


def build_snapshot(uid: int) -> str:
    """拼装「实时快照」文本，随用户提问一起交给 AI。

    内容来自服务端真实数据：当前地块、四路读数、RORI 与分级建议、阈值与
    6 日降雨前馈、设备状态、最近 1 小时趋势。任何一步失败都只丢那一行，
    绝不抛异常（AI 问答不能因为取数失败而 500）。

    返回: 快照文本；连地块信息都取不到时返回空串（调用方按无上下文处理）。
    """
    try:
        from qinghe import db, heartbeat, planner
    except Exception:  # noqa: BLE001 - 依赖缺失时退化为无上下文问答
        return ''

    try:
        ctx = planner.build_context(uid)
    except Exception:  # noqa: BLE001
        return ''

    lines = []
    try:
        cfg = db.load_config(uid)
        farm_name = (cfg['farm_name'] if cfg else '') or '未命名地块'
        lng = (cfg['farm_lng'] if cfg else '') or ''
        lat = (cfg['farm_lat'] if cfg else '') or ''
        where = farm_name
        if lng and lat:
            where += '（%s, %s）' % (lng, lat)
        lines.append('当前地块：%s' % where)
    except Exception:  # noqa: BLE001
        pass

    has_telemetry = bool(ctx.get('has_telemetry'))
    level = ctx.get('rori_level') or {}
    if has_telemetry:
        lines.append(
            '四路读数：渠道水位 %s，土壤湿润度 %s，溶解氧 %s，氧化还原电位 %s'
            % (
                _num(ctx.get('water_mm'), 1, ' mm'),
                _num(ctx.get('soil_pct'), 1, '%'),
                _num(ctx.get('do_mgl'), 2, ' mg/L'),
                _num(ctx.get('eh_mv'), 0, ' mV'),
            )
        )
        lines.append(
            'RORI %s（%s）：%s'
            % (
                _num(ctx.get('rori'), 1),
                level.get('name', '未知'),
                level.get('strategy', ''),
            )
        )
    else:
        # 没有遥测时不要拿安全默认值 0 冒充真实读数（会误导模型与用户）
        lines.append('四路读数：暂无（设备尚未上报数据）')
        lines.append('RORI 未知：缺少实时读数，无法判定根区氧环境')
    try:
        thresh = db.load_thresholds(uid)
    except Exception:  # noqa: BLE001
        thresh = None
    if thresh is not None:
        thresh_text = '阈值：土壤湿度 %s–%s%%，水位 %s–%s mm；' % (
            thresh['humi_down'], thresh['humi_up'],
            thresh['waterlevel_down'], thresh['waterlevel_up'],
        )
    else:
        thresh_text = '阈值：未设置（按默认值运行）；'
    lines.append(
        thresh_text + '6 日加权降雨 P6d=%s mm，α=%s，动态湿度下限 %s%%、上限 %s%%'
        % (
            _num(ctx.get('p6d'), 1),
            _num(ctx.get('alpha'), 2),
            _num(ctx.get('eff_lower'), 1),
            _num(ctx.get('eff_upper'), 1),
        )
    )
    lines.append(
        '设备：气泵 %s，水泵 %s'
        % (ctx.get('air_pump') or '未知', ctx.get('water_pump') or '未知')
    )

    try:
        status = heartbeat.get_status(uid)
        last_seen = int(status.get('last_seen_ts') or 0)
        state = '在线' if status.get('online') else '离线'
        if last_seen:
            silent = status.get('silent_seconds')
            if silent is not None:
                state += '（%.0f 秒前有上报）' % float(silent)
            lines.append('设备连接：%s' % state)
        else:
            lines.append('设备连接：尚未收到心跳（设备可能未上电或未联网）')
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = db.query_history(uid, 40, farm_id=db.get_active_farm_id(uid))
        rows = list(reversed(rows))
        if rows:
            # ADC -> mm 的换算与「当前地块」无关，这里一次性算完；
            # 逐点调用会走 40 次惰性 import 与 try/except，是纯浪费。
            from qinghe import irrigation

            water = [r['water_adc'] for r in rows]
            dos = [r['do_mgl'] for r in rows]
            water_mm = [irrigation.adc_to_water_mm(w) for w in water]
            lines.append(
                '近 40 条采样趋势：水位 ADC %s（换算 %s），溶解氧 %s mg/L'
                % (
                    _trend(water, 0),
                    _trend(water_mm, 1),
                    _trend(dos, 2),
                )
            )
    except Exception:  # noqa: BLE001
        pass

    try:
        precips = planner._forecast_precips(uid) or []
        if precips:
            lines.append(
                '未来 6 日预报降雨（mm，按日）：%s'
                % '、'.join('%.1f' % float(p) for p in precips[:6])
            )
    except Exception:  # noqa: BLE001
        pass

    lines.append(
        '请结合以上实时数据作答：优先给出可执行结论（是否需要开/关水泵、气泵，阈值是否要调），'
        '并在引用数字时与快照保持一致；数据缺失时明确说明缺什么，不要编造读数。'
    )
    text = '\n'.join('- ' + line if i else line for i, line in enumerate(lines))
    return text[:SNAPSHOT_MAX_CHARS]


def load_ai_config(uid: int):
    """读取用户的 AI 配置行（ai_domain / ai_key），不存在返回 None。"""
    return db.load_ai_config(uid)


def normalize_base_url(ai_domain) -> str:
    """规整 AI 接口基址：空值取默认；deepseek 官方误填 http 时自动纠正为 https。"""
    base_url = (ai_domain.strip() if ai_domain else config.DEFAULT_AI_DOMAIN)
    if base_url.startswith('http://api.deepseek.com'):
        base_url = 'https://api.deepseek.com'
    return base_url


def build_chat_request(ai_domain, user_msg: str):
    """构造 (url, headers, body)。"""
    base_url = normalize_base_url(ai_domain)
    url = '%s/chat/completions' % base_url.rstrip('/')
    headers = {'Content-Type': 'application/json'}
    body = {
        'model': config.DEFAULT_AI_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_msg},
        ],
        'stream': False,
    }
    return url, headers, body


def is_public_http_url(url: str) -> bool:
    """判断 URL 是否为 http(s) 且主机不是本机/私网/链路本地/元数据地址。

    只做主机字面量与常见内网域名判断，不做 DNS 解析：既避免校验与实际连接
    解析结果不一致（DNS rebinding），也避免测试环境被迫联网。非法 URL 视为
    不安全。用于阻断「把 ai_domain 指到 127.0.0.1 / 169.254.169.254 从而让
    服务端替调用方访问内网」的 SSRF 路径。
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return False
    host = parsed.hostname.strip('[]').lower()
    if host in ('localhost', 'localhost.localdomain') or host.endswith(
            ('.local', '.internal', '.localhost', '.lan', '.home')):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return bool(
        ip.is_global
        and not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    )


def chat(ai_domain, ai_key, user_msg: str, context: str = None) -> dict:
    """调用 AI 接口并返回可直接 jsonify 的 dict。

    参数:
        context: 可选的「实时快照」文本。非空时作为第二条 system 消息插在
                 固定系统提示之后、用户提问之前，让模型带着实时读数作答。
    """
    url, headers, body = build_chat_request(ai_domain, user_msg)
    # 防 SSRF：ai_domain 由用户配置，不能被用来让服务端访问本机/内网/云元数据
    if not is_public_http_url(url):
        return _wrap('AI 域名不允许指向本机或内网地址，请在设置中填写公开可访问的 https 地址')
    if context:
        body['messages'].insert(1, {'role': 'system', 'content': context})
    headers['Authorization'] = 'Bearer %s' % ai_key
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=config.TIMEOUT_AI)
        if resp.status_code != 200:
            snippet = (resp.text or '(空响应)')[:300]
            return _wrap('AI 接口返回异常（HTTP %s）：%s' % (resp.status_code, snippet))
        try:
            return resp.json()
        except Exception:
            return _wrap(
                'AI 接口返回非 JSON 内容（HTTP %s）：%s'
                % (resp.status_code, (resp.text or '')[:300])
            )
    except Exception as e:
        return _wrap('请求失败: %s' % str(e))
