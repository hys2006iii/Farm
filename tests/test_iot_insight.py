"""遥测旁路集成测试：一次设备上报同时驱动心跳、预案上下文、泵时长、告警。

被测链路：`qinghe.iot.handle_mqtt_message()` -> `iot._feed_insight()`。
测试全部离线执行：不连 MQTT、不调外部 HTTP；emit 与历史写入器都用桩替代。
"""

import json
import time

import pytest

from helpers import make_user
from qinghe import alert_center, heartbeat, iot, logbook, metrics, planner


class FakeWriter:
    """替代 `HistoryWriter`，只记录入队的历史采样。"""

    def __init__(self):
        self.rows = []

    def enqueue(self, uid, ts, water_adc, soil_adc, do_mgl=None, eh_mv=None):
        self.rows.append((uid, ts, water_adc, soil_adc, do_mgl, eh_mv))
        return True


def huawei_payload(**props):
    """构造华为云物模型属性上报报文。"""
    return json.dumps({'services': [{'service_id': 'esp', 'properties': props}]}, ensure_ascii=False)


@pytest.fixture()
def uid(flask_app):
    """一个普通用户。"""
    created = make_user('iot01', 'secret123')
    assert created
    return created


@pytest.fixture(autouse=True)
def _clean_state():
    """清掉告警冷却、限频表与日志队列，保证用例间互不影响。"""
    alert_center._reset_dedupe()
    with iot._alert_eval_lock:
        iot._alert_eval_last.clear()
    logbook.flush_logs()
    yield
    alert_center._reset_dedupe()
    with iot._alert_eval_lock:
        iot._alert_eval_last.clear()
    logbook.flush_logs()


def send(uid, payload, writer=None):
    """用桩替换 emit / writer 后投递一条报文，返回收到的推送消息列表。"""
    emitted = []
    writer = writer or FakeWriter()
    iot.handle_mqtt_message(
        uid,
        '/esp32e/data',
        payload,
        emit=lambda user_id, msg: emitted.append((user_id, msg)),
        writer=writer,
    )
    return emitted, writer


# ============================================================
# 心跳
# ============================================================


def test_message_marks_heartbeat_online(uid):
    """一条上报即可把设备判为在线。"""
    assert heartbeat.get_status(uid)['online'] is False
    send(uid, huawei_payload(waterlevel=1500, humidity=3500, do=2.0, eh=-50))
    status = heartbeat.get_status(uid)
    assert status['online'] is True
    assert status['last_seen_ts'] > 0


# ============================================================
# 预案上下文
# ============================================================


def test_message_updates_planner_context(uid):
    """上报的遥测被写入预案上下文缓存，并算出 RORI 与量纲换算值。"""
    send(uid, huawei_payload(waterlevel=1500, humidity=3500, do=2.0, eh=-50))
    context = planner.build_context(uid)
    assert context['water_mm'] == pytest.approx(1500 / 4095 * 300, abs=0.5)
    assert context['soil_pct'] == pytest.approx((4095 - 3500) / 4095 * 100, abs=0.5)
    assert context['do_mgl'] == pytest.approx(2.0, abs=1e-6)
    assert context['eh_mv'] == pytest.approx(-50.0, abs=1e-6)
    assert context['rori'] > 70
    assert context['rori_level']['code'] == 2


# ============================================================
# 泵运行时长
# ============================================================


def test_message_records_pump_runtime(uid):
    """泵状态上报累加到节水减碳看板的运行时长。"""
    send(uid, huawei_payload(waterlevel=1200, humidity=3000, do=5.0, eh=150,
                             air_pump='on', water_pump='off'))
    time.sleep(0.01)
    series = metrics.daily_series(uid, days=1)
    assert isinstance(series, list)
    # 至少有一条记录说明泵状态已被跟踪（秒数可能为 0，刚开启还没结算）
    assert series, '泵运行时长未被记录'


# ============================================================
# 服务端告警
# ============================================================


def test_message_triggers_server_side_alerts(uid):
    """土壤很干 + 高 RORI 时应产生服务端告警。"""
    send(uid, huawei_payload(waterlevel=1500, humidity=3500, do=2.0, eh=-50))
    alerts = alert_center.list_alerts(uid, limit=50)
    assert alerts, '未产生任何服务端告警'
    codes = {item['code'] for item in alerts}
    assert 'soil_low' in codes
    assert 'rori_high' in codes


def test_message_alert_evaluation_is_throttled(uid):
    """限频窗口内重复上报不会重复判定告警。"""
    payload = huawei_payload(waterlevel=1500, humidity=3500, do=2.0, eh=-50)
    send(uid, payload)
    first = alert_center.list_alerts(uid, limit=50)
    send(uid, payload)
    second = alert_center.list_alerts(uid, limit=50)
    assert len(first) == len(second)


# ============================================================
# 主链路不回归
# ============================================================


def test_message_still_emits_and_enqueues_history(uid):
    """旁路集成不影响原有推送与历史入库行为，且 DO / Eh 一并落库。"""
    emitted, writer = send(uid, huawei_payload(waterlevel=1500, humidity=3500,
                                               do=4.5, eh=90))
    topics = {msg['topic'] for _, msg in emitted}
    assert {'waterlevel', 'humidity'} <= topics
    assert len(writer.rows) == 1
    _, _, water_adc, soil_adc, do_mgl, eh_mv = writer.rows[0]
    assert (water_adc, soil_adc) == (1500, 3500)
    assert do_mgl == pytest.approx(4.5)
    assert eh_mv == pytest.approx(90.0)


def test_history_rows_persist_do_and_eh(uid):
    """DO / Eh 能真正写进 sensor_history 并被查询接口读回。"""
    from contextlib import closing

    from qinghe import db

    db.insert_history_rows([(uid, 1750000100000, 200, 2100, 3.5, -120)])
    with closing(db.get_db()) as conn:
        row = conn.execute(
            'SELECT ts, water_adc, soil_adc, do_mgl, eh_mv FROM sensor_history'
            ' WHERE user_id = ?', (uid,)).fetchone()
    assert row['do_mgl'] == pytest.approx(3.5)
    assert row['eh_mv'] == pytest.approx(-120.0)

    rows = db.query_history(uid, 10)
    assert rows and rows[0]['do_mgl'] == pytest.approx(3.5)


@pytest.mark.parametrize('payload', ['not-json', '12345', '{"foo": "bar"}'])
def test_message_tolerates_malformed_payload(uid, payload):
    """畸形报文不抛异常，心跳仍然记录。"""
    send(uid, payload)
    assert heartbeat.get_status(uid)['online'] is True


def test_message_without_sensors_skips_alert_eval(uid):
    """只有泵状态、没有传感器数据的报文不触发告警判定。"""
    send(uid, huawei_payload(air_pump='on'))
    assert alert_center.list_alerts(uid, limit=10) == []


def test_message_triggers_low_water_alert(uid):
    """水位低于下限时补发 water_low 告警（既有 evaluate_alerts 不产出该码）。"""
    # humidity=1500 -> 湿润度约 63%，不触发土壤告警；waterlevel=200 -> 约 14.65mm
    send(uid, huawei_payload(waterlevel=200, humidity=1500, do=6.5, eh=200))
    codes = {item['code'] for item in alert_center.list_alerts(uid, limit=50)}
    assert 'water_low' in codes


def test_thresholds_from_db_drive_alert_judgement(uid):
    """放宽阈值后同样的遥测不再触发土壤过低告警。"""
    from qinghe import db

    db.save_thresholds(uid, humi_down=5, humi_up=95, wl_down=30, wl_up=290, manual=0)
    send(uid, huawei_payload(waterlevel=1500, humidity=3500, do=6.5, eh=200))
    codes = {item['code'] for item in alert_center.list_alerts(uid, limit=50)}
    assert 'soil_low' not in codes
