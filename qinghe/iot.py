"""青禾智灌 —— 华为云 IoTDA(MQTT) 接入层。

职责：
- `mqtt_clients` 注册表（**加锁**保护，MQTT 回调线程与请求线程并发读写安全）；
- `connect_huawei_iot()` / `send_property_command()`：按用户配置连接与下发指令；
- `handle_mqtt_message()`：解析上报报文 → SocketIO 推送 → 历史数据入队；
- `HistoryWriter`：模块级写入队列 + 单后台线程批量落库，回调线程零阻塞。

Topic 约定（与华为云数据转发规则一致）：
- 上行：`/esp32e/data`（可配置 iot_m2m_topic）与 `$oc/devices/<device_id>/user/#`
- 下行：`/esp32e/cmd`（可配置 iot_cmd_topic），用非 $oc 自定义 Topic 才能被平台接受
"""

import json
import queue
import threading
import time

import paho.mqtt.client as mqtt

from qinghe import config, db

# ============================================================
# 一、连接注册表（加锁）
# ============================================================

#: {uid: {'client': mqtt.Client, 'device_id': str, 'cmd_topic': str, 'connected': bool}}
mqtt_clients = {}
mqtt_lock = threading.RLock()


def get_client(uid):
    """取用户的 MQTT 客户端记录（副本），不存在返回 None。"""
    with mqtt_lock:
        entry = mqtt_clients.get(uid)
        return dict(entry) if entry else None


def is_connected(uid) -> bool:
    """该用户的 MQTT 是否真正握手成功（rc==0）。"""
    with mqtt_lock:
        entry = mqtt_clients.get(uid)
        return bool(entry and entry.get('connected'))


def set_connected(uid, connected: bool) -> None:
    """更新连接状态标记（供 MQTT 回调线程调用）。"""
    with mqtt_lock:
        entry = mqtt_clients.get(uid)
        if entry is not None:
            entry['connected'] = bool(connected)


def _stop_client(uid) -> None:
    """停掉该用户的旧连接并从注册表移除。"""
    with mqtt_lock:
        entry = mqtt_clients.pop(uid, None)
    if not entry:
        return
    try:
        entry['client'].loop_stop()
    except Exception:
        pass
    try:
        entry['client'].disconnect()
    except Exception:
        pass


def clear_clients() -> None:
    """停掉全部连接（测试/进程退出用）。"""
    with mqtt_lock:
        uids = list(mqtt_clients.keys())
    for uid in uids:
        _stop_client(uid)


# ============================================================
# 二、历史数据批量落库
# ============================================================


class HistoryWriter:
    """模块级写入队列 + 单后台线程批量落库。

    - MQTT 回调线程只做 `enqueue()`（非阻塞，O(1)）；
    - 后台线程每 `flush_interval` 秒或攒够 `batch` 条 flush 一次；
    - 队列满时**丢弃最旧**数据，绝不阻塞回调线程。
    """

    def __init__(self, maxsize: int = config.HISTORY_QUEUE_MAX,
                 flush_interval: float = config.HISTORY_FLUSH_INTERVAL,
                 batch: int = config.HISTORY_FLUSH_BATCH):
        self.queue = queue.Queue(maxsize=maxsize)
        self.flush_interval = flush_interval
        self.batch = batch
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.dropped = 0

    def enqueue(self, uid, ts, water_adc, soil_adc) -> bool:
        """入队一条历史采样；队列满则丢弃最旧一条再放入。返回是否直接入队成功。"""
        item = (uid, ts, water_adc, soil_adc)
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            pass
        # 丢弃最旧一条，为最新数据让位（不阻塞 MQTT 回调线程）
        try:
            self.queue.get_nowait()
            self.dropped += 1
        except queue.Empty:
            pass
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1
            return False
        return True

    def _drain(self):
        """取出最多 batch 条待写入数据。"""
        rows = []
        while len(rows) < self.batch:
            try:
                rows.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return rows

    def flush_once(self) -> int:
        """立即 flush 一批，返回写入条数（测试可直接调用）。"""
        rows = self._drain()
        if not rows:
            return 0
        try:
            db.insert_history_rows(rows)
        except Exception:
            # 落库失败不能影响 MQTT 回调；重新入队等待下次重试
            for row in rows:
                self.enqueue(*row)
            return 0
        return len(rows)

    def _run(self):
        while not self._stop.wait(self.flush_interval):
            self.flush_once()

    def start(self) -> None:
        """启动后台落库线程（幂等）。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name='history-writer', daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """停止后台线程并 flush 剩余数据。"""
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self.flush_once()


#: 全局单例
history_writer = HistoryWriter()


def start_history_writer() -> None:
    """启动全局历史落库线程。"""
    history_writer.start()


def flush_history() -> int:
    """同步 flush 全局队列（测试用）。"""
    return history_writer.flush_once()


# ============================================================
# 三、报文处理
# ============================================================

#: 历史采样需要的两个字段（华为云物模型属性名）
HISTORY_FIELDS = ('waterlevel', 'humidity')


def parse_mqtt_payload(topic: str, content: str):
    """解析 MQTT 报文。

    返回: (topic_leaf, values, messages)
        topic_leaf: Topic 末段
        values:     {属性名: 值}，仅含标量
        messages:   [{'type','topic','payload'}, ...] 待推送前端的消息
    """
    topic_leaf = topic.split('/')[-1]
    parsed = None
    try:
        parsed = json.loads(content)
    except Exception:
        pass

    values = {}
    messages = []
    if parsed and isinstance(parsed, dict) and 'services' in parsed:
        # 华为云物模型上报：services[].properties
        for svc in parsed['services']:
            props = svc.get('properties') or {}
            for k, v in props.items():
                values[k] = v
                messages.append({'type': 'data', 'topic': k, 'payload': str(v)})
    elif isinstance(parsed, dict) and parsed:
        # 自定义 Topic 直接是 JSON 对象
        for k, v in parsed.items():
            if isinstance(v, (int, float, str, bool)):
                values[k] = v
                messages.append({'type': 'data', 'topic': k, 'payload': str(v)})
    else:
        # 纯文本，整段当作叶子 Topic 的值
        messages.append({'type': 'data', 'topic': topic_leaf, 'payload': content})
    return topic_leaf, values, messages


def extract_history_sample(values: dict, now_ms: int = None):
    """从解析出的属性中提取历史采样行；水位与土壤不齐时返回 None。"""
    water_adc = values.get('waterlevel')
    soil_adc = values.get('humidity')
    if water_adc is None or soil_adc is None:
        return None
    try:
        ts = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return (int(float(water_adc)), int(float(soil_adc)), ts)
    except (TypeError, ValueError):
        return None


def handle_mqtt_message(uid, topic, content, emit=None, writer=None) -> None:
    """把 MQTT 报文拆成字段，推给前端，并把历史数据放入批量写入队列。

    本函数在 MQTT 回调线程中执行，**不得**做任何阻塞 IO。
    """
    if emit is None:
        from qinghe import realtime
        emit = realtime.emit_hw_data
    writer = writer or history_writer

    _topic_leaf, values, messages = parse_mqtt_payload(topic, content)
    for msg in messages:
        emit(uid, msg)

    sample = extract_history_sample(values)
    if sample is not None:
        water_adc, soil_adc, ts = sample
        writer.enqueue(uid, ts, water_adc, soil_adc)


# ============================================================
# 四、MQTT 回调
# ============================================================


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    """连接回调：订阅上行 Topic 并推送在线状态。"""
    from qinghe import realtime

    uid = userdata.get('uid')
    if rc == 0:
        m2m_topic = userdata.get('m2m_topic', config.DEFAULT_M2M_TOPIC)
        device_id = userdata.get('device_id', '')
        try:
            client.subscribe(m2m_topic)
            if device_id:
                client.subscribe('$oc/devices/%s/user/#' % device_id)
        except Exception:
            pass
        set_connected(uid, True)
        realtime.emit_hw_data(uid, {'type': 'device_status', 'status': 'online'})
        realtime.emit_hw_data(
            uid, {'type': 'data', 'topic': 'log', 'payload': '华为云 MQTT 连接成功'}
        )
    else:
        realtime.emit_hw_data(uid, {'type': 'device_status', 'status': 'offline'})


def on_mqtt_disconnect(client, userdata, rc, properties=None, reason_code=None):
    """断开回调：标记离线并推送状态。"""
    from qinghe import realtime

    uid = userdata.get('uid')
    set_connected(uid, False)
    realtime.emit_hw_data(uid, {'type': 'device_status', 'status': 'offline'})


def on_mqtt_message(client, userdata, msg):
    """消息回调：交给 handle_mqtt_message 解析（内部非阻塞）。"""
    uid = userdata.get('uid')
    content = msg.payload.decode('utf-8', errors='replace')
    handle_mqtt_message(uid, msg.topic, content)


# ============================================================
# 五、连接与下发
# ============================================================


def connect_huawei_iot(uid) -> bool:
    """按用户配置连上华为云 IoTDA。

    app 用 client 设备身份连接；订阅数据转发 Topic（ESP32-E 数据被规则推到这）
    与自身的 user/# 命令反馈。配置不完整或连接失败返回 False。
    """
    cfg = db.load_config(uid)
    if not cfg:
        return False
    host = cfg['iot_host'] or ''
    port = int(cfg['iot_port'] or config.IOT_PORT_DEFAULT)
    client_id = cfg['iot_client_id'] or ''
    user = cfg['iot_user'] or ''
    pw = cfg['iot_pass'] or ''
    # 本机身份：app 用 client 设备，device_id 即 client 自己的设备 ID（用于发布命令主题）
    device_id = cfg['iot_device_id'] or ''
    target_device = cfg['iot_target_device_id'] or ''
    m2m_topic = cfg['iot_m2m_topic'] or config.DEFAULT_M2M_TOPIC
    cmd_topic = cfg['iot_cmd_topic'] or config.DEFAULT_CMD_TOPIC

    if not host or not client_id or not user or not pw or not device_id:
        return False

    # 同一用户重连前，先停掉旧连接
    _stop_client(uid)

    try:
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:
        cli = mqtt.Client(client_id=client_id)

    cli.user_data_set({
        'uid': uid,
        'm2m_topic': m2m_topic,
        'cmd_topic': cmd_topic,
        'target_device': target_device,
        'device_id': device_id,
    })
    cli.username_pw_set(user, pw)
    cli.on_connect = on_mqtt_connect
    cli.on_disconnect = on_mqtt_disconnect
    cli.on_message = on_mqtt_message

    try:
        cli.connect(host, port, 60)
        cli.loop_start()
    except Exception:
        try:
            cli.disconnect()
        except Exception:
            pass
        return False

    with mqtt_lock:
        mqtt_clients[uid] = {
            'client': cli,
            'device_id': device_id,
            'cmd_topic': cmd_topic,
            'connected': False,
        }
    return True


def send_property_command(uid, props) -> bool:
    """下发设备控制指令。

    设备控制下发：app 用 client 设备身份，把命令发到非 $oc 自定义 Topic
    （默认 /esp32e/cmd，可配置），再由华为云【数据转发规则】把该主题的
    "设备消息"转发到 ESP32-E（ESP32-E 已订阅 /esp32e/cmd）。
    关键：用非 $oc 自定义 Topic 才能被平台接受（$oc/.../user/ 下的 Topic 必须在
    产品里定义，未定义会报 IOTDA.017004 Invalid topic）；且 app 用 client 身份，
    不抢 ESP32-E 身份。无实体设备时不做任何模拟回执——网页状态只反映真实 MQTT 消息。
    """
    device, action = next(iter(props.items()))
    entry = get_client(uid)
    if not entry or not entry.get('connected'):
        return False
    cli = entry['client']
    cmd_topic = entry.get('cmd_topic') or config.DEFAULT_CMD_TOPIC
    message = json.dumps({'device': device, 'action': action}, ensure_ascii=False)
    cli.publish(cmd_topic, message)
    return True
