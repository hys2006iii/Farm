"""青禾智灌 —— 天气与逆地理模块。

- `photon_reverse()`：Photon(komoot/OSM) 逆地理，免 Key、简体、可下探社区级；
- `fetch_forecast()`：和风天气 7 日预报代理（避免前端跨域与 CSP 拦截）；
- `geo_lookup()`：带 DB 缓存的逆地理查询，同一坐标只打一次外部接口。

所有外部调用都带 timeout，且异常一律吞掉后返回 None / 错误字典，不向上抛。
"""

import requests

from qinghe import config, db


def _pick_admin(values):
    """values: 由大到小的行政区字段（可能为空）。过滤国家/空值、去重，
    返回最细最多 4 级，保持 大->小 顺序。"""
    cleaned = []
    for v in values:
        if v and v not in ('中华人民共和国', '中国'):
            cleaned.append(v)
    seen = set()
    out = []
    for v in cleaned:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out[-4:]


def photon_reverse(lat, lng):
    """Photon(komoot, 基于 OSM) 逆地理：免 Key、返回简体、可下探 suburb/quarter(社区级)。
    服务端调用、带缓存。失败返回 None。"""
    try:
        r = requests.get(
            'https://photon.komoot.io/reverse',
            params={'lat': lat, 'lon': lng, 'lang': 'zh'},
            timeout=config.TIMEOUT_PHOTON,
        )
        f = (r.json() or {}).get('features', [{}])[0].get('properties', {})
        if not f:
            return None
        name = f.get('name')
        chain = _pick_admin([
            f.get('state'), f.get('city'), f.get('county'),
            f.get('district'), f.get('suburb'), f.get('quarter'),
        ])
        # 若 name 比 chain 最细一级还细（如 社区/村/POI），补到末尾
        if name and name not in chain:
            chain = chain + [name]
        chain = chain[-4:]
        if chain:
            return ' · '.join(chain)
    except Exception:
        pass
    return None


def geo_key(lat: float, lng: float) -> str:
    """逆地理缓存键：坐标保留 4 位小数。"""
    return '%s,%s' % (round(lat, 4), round(lng, 4))


def geo_fallback_text(lat: float, lng: float) -> str:
    """反查失败时的坐标兜底文案（与旧版逐字一致）。"""
    return 'E: %.2f°, N: %.2f°' % (lng, lat)


def geo_lookup(lat: float, lng: float):
    """带缓存的逆地理查询。

    返回: (name, cached)。name 为 None 表示未解析到（调用方应给坐标兜底文案）。
    """
    key = geo_key(lat, lng)
    cached = db.get_geo_cache(key)
    if cached:
        return cached, True
    name = photon_reverse(lat, lng)
    if name:
        db.set_geo_cache(key, name)
        return name, False
    return None, False


def build_forecast_url(domain: str, lng, lat, key: str) -> str:
    """拼接和风天气 7 日预报 URL。"""
    domain = (domain or config.DEFAULT_WEATHER_DOMAIN).strip()
    return 'https://%s/v7/weather/7d?location=%s,%s&key=%s' % (domain, lng, lat, key)


def fetch_forecast(domain: str, lng, lat, key: str) -> dict:
    """代理请求和风天气 7 日预报。

    返回: 上游 JSON（原样透传）；失败时返回 {'code': 'ERR', 'error': ...}。
    """
    url = build_forecast_url(domain, lng, lat, key)
    try:
        r = requests.get(url, timeout=config.TIMEOUT_WEATHER)
    except Exception as e:
        return {'code': 'ERR', 'error': '天气接口请求失败: %s' % str(e)}
    try:
        return r.json()
    except Exception:
        return {'code': 'ERR', 'error': '天气接口非 JSON（HTTP %s）' % r.status_code}
