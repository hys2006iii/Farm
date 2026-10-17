"""青禾智灌 —— 告警判定与 webhook 推送。

- `notify_webhook()`：把告警推送到用户配置的 webhook（钉钉/企业微信/飞书通用文本格式）；
- `AlertDeduper`：同一告警内容的去重/冷却，避免高频采集下重复轰炸；
- `evaluate_alerts()`：纯函数，按阈值与 RORI 分级判定当前应产生的告警列表。
"""

import threading
import time

import requests

from qinghe import config, db

#: 钉钉机器人安全设置要求消息包含关键词【青禾智灌系统】，固定加在开头
ALERT_KEYWORD = config.ALERT_KEY_PREFIX


def notify_webhook(uid: int, title: str, content: str) -> bool:
    """推送告警到用户配置的 webhook（钉钉/企业微信/飞书 通用格式，带兜底适配）。"""
    cfg = db.load_config(uid)
    if not cfg or not cfg['webhook_url']:
        return False
    url = (cfg['webhook_url'] or '').strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    text = '%s%s\n%s' % (ALERT_KEYWORD, title, content)
    payload = {'msgtype': 'text', 'text': {'content': text}}
    try:
        r = requests.post(url, json=payload, timeout=config.TIMEOUT_WEBHOOK)
        return r.status_code in (200, 201)
    except Exception:
        return False


class AlertDeduper:
    """按告警内容去重的冷却器（线程安全）。

    与前端 `alertCoolDown` 行为一致：同一 key 在 cooldown 秒内只放行一次。
    """

    def __init__(self, cooldown: float = config.ALERT_COOLDOWN_SECONDS):
        self.cooldown = cooldown
        self._last = {}
        self._lock = threading.Lock()

    def should_emit(self, key: str, now: float = None) -> bool:
        """是否应当发出该告警；返回 True 时同时刷新时间戳。"""
        now = time.time() if now is None else now
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.cooldown:
                return False
            self._last[key] = now
            return True

    def reset(self) -> None:
        """清空去重状态。"""
        with self._lock:
            self._last.clear()


def evaluate_alerts(soil_pct, water_mm, humi_lower, humi_upper,
                    water_upper, rori=None) -> list:
    """纯函数：按动态阈值与 RORI 分级判定当前告警列表。

    参数:
        soil_pct:    当前土壤湿润度（%RH）
        water_mm:    当前水位（mm）
        humi_lower:  动态土壤湿度下限（%）
        humi_upper:  动态土壤湿度上限（%）
        water_upper: 水位上限（mm）
        rori:        RORI 指数（0~100），None 表示不可用

    返回:
        [{'level': 'warn'|'danger', 'code': '...', 'msg': '...'}, ...]

    其中 `code` 是稳定类型码（`soil_low` / `soil_high` / `water_high` /
    `rori_medium` / `rori_high`），供 `alert_center` 直接落库，**不依赖中文文案**，
    因此调整文案不会改变告警分类。
    """
    items = []
    if soil_pct < humi_lower:
        items.append({'level': 'warn', 'code': 'soil_low',
                      'msg': '土壤湿度过低 %.1f%% < 下限 %.1f%%，建议补灌' % (soil_pct, humi_lower)})
    elif soil_pct > humi_upper:
        items.append({'level': 'warn', 'code': 'soil_high',
                      'msg': '土壤湿度过高 %.1f%% > 上限 %.1f%%，注意排湿' % (soil_pct, humi_upper)})
    if water_mm > water_upper:
        items.append({'level': 'warn', 'code': 'water_high',
                      'msg': '水位过高 %.1fmm > 上限 %.1fmm，注意排水' % (water_mm, water_upper)})
    if rori is not None:
        if rori >= config.RORI_HEAVY:
            items.append({'level': 'danger', 'code': 'rori_high',
                          'msg': 'RORI %.0f 重度厌氧，强制增氧' % rori})
        elif rori >= config.RORI_MODERATE:
            items.append({'level': 'warn', 'code': 'rori_medium',
                          'msg': 'RORI %.0f 中度缺氧，脉冲加气' % rori})
    return items
