"""IoT / MQTT 层测试：报文解析、批量落库队列、注册表加锁、指令下发。"""

import json
import threading
import time
from contextlib import closing

import pytest

from helpers import fetch_all, make_user
from qinghe import config, iot
from qinghe.db import get_db


@pytest.fixture()
def uid(flask_app):
    return make_user('iotuser1', 'pw123456')


# ============================================================
# 报文解析
# ============================================================

def test_parse_huawei_services_payload():
    content = json.dumps({
        'services': [{'service_id': 's1', 'properties': {'waterlevel': 1000, 'humidity': 2000}}]
    })
    leaf, values, messages = iot.parse_mqtt_payload('/esp32e/data', content)
    assert leaf == 'data'
    assert values == {'waterlevel': 1000, 'humidity': 2000}
    assert {'type': 'data', 'topic': 'waterlevel', 'payload': '1000'} in messages
    assert len(messages) == 2


def test_parse_flat_json_payload():
    _leaf, values, messages = iot.parse_mqtt_payload(
        '/esp32e/data', json.dumps({'waterlevel': 500, 'do': 6.5}))
    assert values == {'waterlevel': 500, 'do': 6.5}
    assert len(messages) == 2


def test_parse_flat_json_skips_nested_objects():
    _leaf, values, _messages = iot.parse_mqtt_payload(
        '/esp32e/data', json.dumps({'waterlevel': 500, 'nested': {'a': 1}}))
    assert values == {'waterlevel': 500}


def test_parse_plain_text_payload():
    leaf, values, messages = iot.parse_mqtt_payload('/esp32e/status', 'QB_ON')
    assert leaf == 'status'
    assert values == {}
    assert messages == [{'type': 'data', 'topic': 'status', 'payload': 'QB_ON'}]


def test_parse_empty_json_object_falls_back_to_text():
    _leaf, values, messages = iot.parse_mqtt_payload('/esp32e/data', '{}')
    assert values == {}
    assert messages[0]['topic'] == 'data'


def test_parse_payload_message_shape():
    _leaf, _values, messages = iot.parse_mqtt_payload(
        '/esp32e/data', json.dumps({'waterlevel': 1}))
    msg = messages[0]
    assert set(msg) == {'type', 'topic', 'payload'}
    assert msg['type'] == 'data'
    assert isinstance(msg['payload'], str)


# ============================================================
# 历史采样提取
# ============================================================

def test_extract_history_sample_requires_both_fields():
    assert iot.extract_history_sample({'waterlevel': 100}) is None
    assert iot.extract_history_sample({'humidity': 100}) is None
    assert iot.extract_history_sample({}) is None


def test_extract_history_sample_converts_to_int():
    sample = iot.extract_history_sample(
        {'waterlevel': '1024.7', 'humidity': 2048.2}, now_ms=1700000000000)
    assert sample == (1024, 2048, 1700000000000, None, None)


def test_extract_history_sample_includes_optional_do_and_eh():
    """溶解氧与氧化还原电位随采样一起返回（供碳汇 / 厌氧评价回溯）。"""
    sample = iot.extract_history_sample(
        {'waterlevel': 800, 'humidity': 1600, 'do': '3.5', 'eh': -120},
        now_ms=1700000000000)
    assert sample == (800, 1600, 1700000000000, 3.5, -120.0)


def test_extract_history_sample_handles_garbage():
    assert iot.extract_history_sample({'waterlevel': 'abc', 'humidity': 1}) is None


# ============================================================
# handle_mqtt_message
# ============================================================

def test_handle_mqtt_message_emits_and_enqueues(uid):
    emitted = []
    writer = iot.HistoryWriter()
    iot.handle_mqtt_message(
        uid, '/esp32e/data',
        json.dumps({'services': [{'properties': {'waterlevel': 800, 'humidity': 1600}}]}),
        emit=lambda u, m: emitted.append((u, m)), writer=writer)
    assert len(emitted) == 2
    assert all(u == uid for u, _ in emitted)
    assert writer.queue.qsize() == 1


def test_handle_mqtt_message_skips_history_when_incomplete(uid):
    writer = iot.HistoryWriter()
    iot.handle_mqtt_message(uid, '/esp32e/data', json.dumps({'waterlevel': 800}),
                            emit=lambda u, m: None, writer=writer)
    assert writer.queue.qsize() == 0


def test_handle_mqtt_message_never_raises(uid):
    """畸形报文不得把异常抛回 MQTT 回调线程。"""
    writer = iot.HistoryWriter()
    iot.handle_mqtt_message(uid, '/x', '\x00not-json', emit=lambda u, m: None, writer=writer)
    iot.handle_mqtt_message(uid, '', '', emit=lambda u, m: None, writer=writer)


# ============================================================
# HistoryWriter 批量落库
# ============================================================

def test_history_writer_flush_persists(uid):
    writer = iot.HistoryWriter()
    writer.enqueue(uid, 1000, 111, 222)
    writer.enqueue(uid, 2000, 333, 444)
    assert writer.flush_once() == 2
    rows = fetch_all('SELECT ts, water_adc, soil_adc FROM sensor_history ORDER BY ts')
    assert [(r['ts'], r['water_adc'], r['soil_adc']) for r in rows] == [
        (1000, 111, 222), (2000, 333, 444)]


def test_history_writer_flush_empty_returns_zero():
    assert iot.HistoryWriter().flush_once() == 0


def test_history_writer_drops_oldest_when_full(uid):
    writer = iot.HistoryWriter(maxsize=3)
    for i in range(5):
        writer.enqueue(uid, i, i, i)
    assert writer.queue.qsize() == 3
    assert writer.dropped == 2
    ts_values = [item[1] for item in list(writer.queue.queue)]
    assert ts_values == [2, 3, 4]      # 保留最新三条


def test_history_writer_enqueue_is_non_blocking(uid):
    """队列满时入队不得阻塞（返回时间应远小于 1 秒）。"""
    writer = iot.HistoryWriter(maxsize=2)
    start = time.time()
    for i in range(200):
        writer.enqueue(uid, i, i, i)
    assert time.time() - start < 1.0


def test_history_writer_batch_size_respected(uid):
    writer = iot.HistoryWriter(maxsize=100, batch=10)
    for i in range(50):
        writer.enqueue(uid, i, i, i)
    assert writer.flush_once() == 10
    assert writer.queue.qsize() == 40


def test_history_writer_start_stop_flushes(uid):
    writer = iot.HistoryWriter(flush_interval=0.05)
    writer.start()
    writer.enqueue(uid, 5000, 1, 2)
    time.sleep(0.25)
    writer.stop()
    rows = fetch_all('SELECT COUNT(*) AS n FROM sensor_history')
    assert rows[0]['n'] == 1


def test_history_writer_start_is_idempotent():
    writer = iot.HistoryWriter(flush_interval=0.05)
    writer.start()
    first = writer._thread
    writer.start()
    assert writer._thread is first
    writer.stop()


def test_history_writer_background_thread_is_daemon():
    writer = iot.HistoryWriter()
    writer.start()
    assert writer._thread.daemon is True
    writer.stop()


def test_global_history_writer_flush(uid):
    iot.history_writer.enqueue(uid, 7000, 5, 6)
    assert iot.flush_history() >= 1


def test_history_writer_requeues_on_db_failure(uid, monkeypatch):
    """落库异常时数据重新入队，不丢也不抛。"""
    import qinghe.db as db

    def boom(_rows):
        raise RuntimeError('db down')

    monkeypatch.setattr(db, 'insert_history_rows', boom)
    writer = iot.HistoryWriter()
    writer.enqueue(uid, 1, 1, 1)
    assert writer.flush_once() == 0
    assert writer.queue.qsize() == 1


# ============================================================
# mqtt_clients 注册表（并发安全）
# ============================================================

def test_set_connected_unknown_uid_is_noop():
    iot.set_connected(999, True)
    assert iot.is_connected(999) is False


def test_is_connected_reflects_flag(uid):
    iot.mqtt_clients[uid] = {'client': None, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': False}
    assert iot.is_connected(uid) is False
    iot.set_connected(uid, True)
    assert iot.is_connected(uid) is True


def test_get_client_returns_copy(uid):
    iot.mqtt_clients[uid] = {'client': None, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    snapshot = iot.get_client(uid)
    snapshot['connected'] = False
    assert iot.mqtt_clients[uid]['connected'] is True


def test_mqtt_registry_concurrent_access_is_safe():
    """多线程并发读写注册表不应抛异常（加锁验证）。"""
    errors = []

    def writer(base):
        try:
            for i in range(200):
                uid = base + i
                iot.mqtt_clients[uid] = {'client': None, 'connected': False}
                iot.set_connected(uid, True)
                iot.is_connected(uid)
                iot.get_client(uid)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def cleaner():
        try:
            for _ in range(200):
                with iot.mqtt_lock:
                    iot.mqtt_clients.clear()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i * 1000,)) for i in range(4)]
    threads.append(threading.Thread(target=cleaner))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_clear_clients_empties_registry(uid):
    iot.mqtt_clients[uid] = {'client': _FakeClient(), 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    iot.clear_clients()
    assert iot.mqtt_clients == {}


# ============================================================
# 指令下发
# ============================================================

class _FakeClient:
    """记录 publish 调用的假 MQTT 客户端。"""

    def __init__(self):
        self.published = []
        self.stopped = False
        self.disconnected = False

    def publish(self, topic, message):
        self.published.append((topic, message))

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True


def test_send_property_command_requires_connection(uid):
    assert iot.send_property_command(uid, {'water_pump': 'on'}) is False


def test_send_property_command_publishes_to_cmd_topic(uid):
    fake = _FakeClient()
    iot.mqtt_clients[uid] = {'client': fake, 'device_id': 'd',
                             'cmd_topic': '/esp32e/cmd', 'connected': True}
    assert iot.send_property_command(uid, {'water_pump': 'on'}) is True
    topic, message = fake.published[0]
    assert topic == '/esp32e/cmd'
    assert json.loads(message) == {'device': 'water_pump', 'action': 'on'}


def test_send_property_command_uses_default_topic_when_missing(uid):
    fake = _FakeClient()
    iot.mqtt_clients[uid] = {'client': fake, 'device_id': 'd', 'connected': True}
    iot.send_property_command(uid, {'air_pump': 'off'})
    assert fake.published[0][0] == config.DEFAULT_CMD_TOPIC


def test_send_property_command_unicode_safe(uid):
    fake = _FakeClient()
    iot.mqtt_clients[uid] = {'client': fake, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    iot.send_property_command(uid, {'water_pump': 'on'})
    assert '水' not in fake.published[0][1]


def test_stop_client_disconnects(uid):
    fake = _FakeClient()
    iot.mqtt_clients[uid] = {'client': fake, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    iot._stop_client(uid)
    assert fake.stopped and fake.disconnected
    assert uid not in iot.mqtt_clients


# ============================================================
# 连接（不真正联网）
# ============================================================

def test_connect_returns_false_without_config(uid):
    assert iot.connect_huawei_iot(uid) is False


def test_connect_returns_false_for_unknown_user():
    assert iot.connect_huawei_iot(123456) is False


def test_connect_returns_false_on_bad_host(uid, monkeypatch):
    import qinghe.db as db

    with closing(get_db()) as conn:
        conn.execute(
            "UPDATE configs SET iot_host='127.0.0.1', iot_port=1, iot_client_id='c',"
            " iot_user='u', iot_pass='p', iot_device_id='d' WHERE user_id=?", (uid,))
        conn.commit()

    assert iot.connect_huawei_iot(uid) is False
    assert uid not in iot.mqtt_clients


def test_on_mqtt_disconnect_marks_offline(uid, monkeypatch):
    emitted = []
    monkeypatch.setattr('qinghe.realtime.emit_hw_data',
                        lambda u, p: emitted.append((u, p)))
    iot.mqtt_clients[uid] = {'client': None, 'device_id': 'd', 'cmd_topic': '/t',
                             'connected': True}
    iot.on_mqtt_disconnect(None, {'uid': uid}, 0)
    assert iot.mqtt_clients[uid]['connected'] is False
    assert emitted == [(uid, {'type': 'device_status', 'status': 'offline'})]


def test_on_mqtt_message_decodes_utf8(uid, monkeypatch):
    captured = {}
    monkeypatch.setattr(iot, 'handle_mqtt_message',
                        lambda u, t, c: captured.update(uid=u, topic=t, content=c))

    class _Msg:
        topic = '/esp32e/data'
        payload = '{"waterlevel": 1}'.encode('utf-8')

    iot.on_mqtt_message(None, {'uid': uid}, _Msg())
    assert captured == {'uid': uid, 'topic': '/esp32e/data', 'content': '{"waterlevel": 1}'}


def test_on_mqtt_message_replaces_invalid_utf8(uid, monkeypatch):
    captured = {}
    monkeypatch.setattr(iot, 'handle_mqtt_message',
                        lambda u, t, c: captured.update(content=c))

    class _Msg:
        topic = '/x'
        payload = b'\xff\xfe'

    iot.on_mqtt_message(None, {'uid': uid}, _Msg())
    assert 'content' in captured


def test_on_mqtt_connect_subscribes_and_emits(uid, monkeypatch):
    emitted = []
    monkeypatch.setattr('qinghe.realtime.emit_hw_data', lambda u, p: emitted.append(p))

    class _Cli:
        def __init__(self):
            self.subs = []

        def subscribe(self, topic):
            self.subs.append(topic)

    cli = _Cli()
    iot.mqtt_clients[uid] = {'client': cli, 'device_id': 'dev-9', 'cmd_topic': '/t',
                             'connected': False}
    iot.on_mqtt_connect(cli, {'uid': uid, 'm2m_topic': '/esp32e/data',
                              'device_id': 'dev-9'}, None, 0)
    assert cli.subs == ['/esp32e/data', '$oc/devices/dev-9/user/#']
    assert iot.mqtt_clients[uid]['connected'] is True
    assert emitted[0] == {'type': 'device_status', 'status': 'online'}


def test_on_mqtt_connect_failure_emits_offline(uid, monkeypatch):
    emitted = []
    monkeypatch.setattr('qinghe.realtime.emit_hw_data', lambda u, p: emitted.append(p))
    iot.on_mqtt_connect(None, {'uid': uid}, None, 5)
    assert emitted == [{'type': 'device_status', 'status': 'offline'}]
