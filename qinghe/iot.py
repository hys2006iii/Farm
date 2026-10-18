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
import logging
import queue
import threading
import time

import paho.mqtt.client as mqtt

from qinghe import config, db

_logger = logging.getLogger('qinghe.iot')

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

    def enqueue(self, uid, ts, water_adc, soil_adc, do_mgl=None, eh_mv=None) -> bool:
        """入队一条历史采样；队列满则丢弃最旧一条再放入。返回是否直接入队成功。

        `do_mgl` / `eh_mv` 为可选感知量，缺失时存 `NULL`（兼容旧调用方）。
        """
        item = (uid, ts, water_adc, soil_adc, do_mgl, eh_mv)
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
        """立即 flush 一批，返回写入条数（测试可直接调用）。

        落库前按用户解析「当前地块」，把每行打进所属地块（`farm_id`），
        让切换地块后的历史图表只看到当前田的数据。解析放在后台线程里做，
        MQTT 回调线程仍然只做非阻塞入队。
        """
        rows = self._drain()
        if not rows:
            return 0
        try:
            farm_ids = {}
            for row in rows:
                uid = row[0]
                if uid not in farm_ids:
                    try:
                        farm_ids[uid] = db.get_active_farm_id(uid)
                    except Exception:  # noqa: BLE001 - 地块查询失败退化为账号级
                        farm_ids[uid] = 0
            grouped = {}
            for row in rows:
                grouped.setdefault(row[0], []).append(row)
            for uid, items in grouped.items():
                db.insert_history_rows(items, farm_id=farm_ids.get(uid, 0))
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

#: 允许下发的设备白名单（唯一来源）：HTTP `/api/app_send_command` 与 SocketIO
#: `send_command` 都从这里取，新增设备只改这一处。
PROP_MAP = {
    'water_pump': 'water_pump',
    'air_pump': 'air_pump',
}


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
    """从解析出的属性中提取历史采样行；水位与土壤不齐时返回 None。

    返回 `(water_adc, soil_adc, ts, do_mgl, eh_mv)`：溶解氧与氧化还原电位为
    可选感知量，缺失时为 `None`（便于碳汇 / 厌氧评价回溯）。
    """
    water_adc = values.get('waterlevel')
    soil_adc = values.get('humidity')
    if water_adc is None or soil_adc is None:
        return None
    try:
        ts = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return (
            int(float(water_adc)),
            int(float(soil_adc)),
            ts,
            _to_float(values.get('do')),
            _to_float(values.get('eh')),
        )
    except (TypeError, ValueError):
        return None


def _to_float(value):
    """把上报值尽力转成 float；非法或缺失返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: 服务端告警判定的最小间隔（秒），避免每条上报都查库
_ALERT_EVAL_INTERVAL = 10.0
_alert_eval_last = {}
_alert_eval_lock = threading.Lock()


def _feed_insight(uid, values: dict, now_ms: int) -> None:
    """把一次设备上报分发给新增旁路模块（心跳 / 预案上下文 / 泵时长 / 自动调控 / 告警）。

    本函数在 MQTT 回调线程中执行，**不得**阻塞、**不得**向上抛异常：
    每个子系统独立 try/except，任一子系统故障都不影响遥测主链路。
    """
    try:
        from qinghe import alert_center, autocontrol, heartbeat, irrigation, metrics, planner
    except Exception:  # noqa: BLE001 - 新增模块缺失时静默跳过
        return

    # 1) 心跳：驱动服务端在线判定。
    # 用墙钟而不是报文里的 ts——心跳表示「此刻收到过包」，而模拟器/补录会带历史
    # 时间戳，若按报文时间算会被立刻判成离线。
    try:
        heartbeat.mark_seen(uid)
    except Exception:  # noqa: BLE001
        pass

    water_adc = _to_float(values.get('waterlevel'))
    soil_adc = _to_float(values.get('humidity'))
    do_mgl = _to_float(values.get('do'))
    eh_mv = _to_float(values.get('eh'))

    water_mm = irrigation.adc_to_water_mm(water_adc) if water_adc is not None else None
    soil_pct = irrigation.adc_to_soil_pct(soil_adc) if soil_adc is not None else None
    rori = None
    if None not in (water_adc, soil_adc, do_mgl, eh_mv):
        try:
            rori = irrigation.compute_rori(water_adc, soil_adc, do_mgl, eh_mv)
        except Exception:  # noqa: BLE001
            rori = None

    telemetry = {
        'water_adc': water_adc,
        'soil_adc': soil_adc,
        'water_mm': water_mm,
        'soil_pct': soil_pct,
        'do_mgl': do_mgl,
        'eh_mv': eh_mv,
        'rori': rori,
        'air_pump': values.get('air_pump'),
        'water_pump': values.get('water_pump'),
        'ts': now_ms,
    }

    # 2) 预案上下文缓存：供 /api/plan/propose 注入感知输入
    try:
        planner.update_telemetry(uid, **telemetry)
    except Exception:  # noqa: BLE001
        pass

    # 3) 泵运行时长：驱动节水减碳看板
    for device in ('air_pump', 'water_pump'):
        state = values.get(device)
        if state is None:
            continue
        try:
            metrics.note_pump_state(uid, device, state, now_ms)
        except Exception:  # noqa: BLE001
            pass

    # 4) 服务端自动调控（默认关闭；开启后带最小动作间隔滞回）
    try:
        autocontrol.evaluate(uid, telemetry)
    except Exception:  # noqa: BLE001
        pass

    # 服务端告警判定（限频，避免每条上报都查库）
    # 注意限频用**墙钟**而不是报文里的 ts：模拟器/补传会一次性灌入带历史
    # 时间戳的批次，用报文时间做限频会把整批都判成「刚判过」而全部跳过。
    if water_mm is None or soil_pct is None:
        return
    now_s = time.time()
    with _alert_eval_lock:
        last = _alert_eval_last.get(uid, 0.0)
        if now_s - last < _ALERT_EVAL_INTERVAL:
            return
        _alert_eval_last[uid] = now_s

    try:
        from qinghe import db
        row = db.load_thresholds(uid)
        # load_thresholds 返回 sqlite3.Row 或 None；统一转成 dict 再取默认值
        thresh = dict(row) if row else {}
    except Exception:  # noqa: BLE001
        thresh = {}

    try:
        alert_center.evaluate_and_push(
            uid,
            soil_pct,
            water_mm,
            rori if rori is not None else 0.0,
            thresh.get('humi_down', 40),
            thresh.get('humi_up', 80),
            thresh.get('waterlevel_down', 30),
            thresh.get('waterlevel_up', 150),
        )
    except Exception:  # noqa: BLE001
        pass

    # 低水位告警：既有 alerts.evaluate_alerts() 不产出 water_low，这里补一条
    try:
        raw_low = thresh.get('waterlevel_down')
        low_mm = 30.0 if raw_low is None else float(raw_low)
        if water_mm < low_mm:
            alert_center.push_alert(
                uid, 'warning', 'water_low',
                '渠道水位偏低（%.1f mm，低于下限 %.0f mm）' % (water_mm, low_mm),
            )
    except Exception:  # noqa: BLE001
        pass


def ingest_telemetry(uid, values: dict, ts=None, emit=None, writer=None) -> dict:
    """把一帧已解析的遥测走完整链路（历史落库 + 旁路分发 + 前端事件）。

    与 MQTT 上报复用同一套处理逻辑，供设备模拟器 / 自测使用；区别只在于
    允许指定历史时间戳（`ts`，毫秒），便于一次灌入一段带时间序列的数据。

    参数:
        values: 属性字典，键与 MQTT 报文一致：waterlevel / humidity / do / eh /
                air_pump / water_pump / temperature / humidity_air ...
        ts:     毫秒时间戳；缺省取当前时间。
        emit:   前端推送函数，缺省用 `realtime.emit_hw_data`；传 `False` 可关闭推送。
        writer: 历史写入器，缺省用模块级 `history_writer`。

    返回: `{'sample': (water_adc, soil_adc, ts, do_mgl, eh_mv) | None, 'ts': int}`
    """
    writer = writer or history_writer
    now_ms = int(time.time() * 1000) if ts is None else int(ts)
    sample = extract_history_sample(values, now_ms)
    if sample is not None:
        water_adc, soil_adc, sample_ts, do_mgl, eh_mv = sample
        writer.enqueue(uid, sample_ts, water_adc, soil_adc, do_mgl, eh_mv)
    else:
        sample_ts = now_ms

    if emit is None:
        from qinghe import realtime

        emit = realtime.emit_hw_data
    if emit:
        try:
            emit(uid, {'type': 'data', 'topic': 'data', 'payload': dict(values)})
        except Exception:  # noqa: BLE001 - 推送失败不影响落库
            pass

    _feed_insight(uid, values, sample_ts)
    return {'sample': sample, 'ts': sample_ts}


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
        water_adc, soil_adc, ts, do_mgl, eh_mv = sample
        writer.enqueue(uid, ts, water_adc, soil_adc, do_mgl, eh_mv)
    else:
        ts = int(time.time() * 1000)

    # 旁路集成：心跳 / 预案上下文 / 泵时长 / 服务端自动调控 / 服务端告警
    _feed_insight(uid, values, ts)


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

def _safe_iot_port(raw) -> int:
    """把配置里的 iot_port 归一为合法端口，非法值回退默认并记 warning。

    路由层已做同口径校验，但 `connect_huawei_iot` 也会被 `api_app_login`、
    定时重连等路径直接调用；历史脏数据（如 `'abc'`）不应让 MQTT 线程抛
    `ValueError` 崩掉。
    """
    try:
        port = int(str(raw).strip()) if raw is not None and str(raw).strip() else config.IOT_PORT_DEFAULT
    except (TypeError, ValueError):
        port = config.IOT_PORT_DEFAULT
    if not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
        _logger.warning('iot_port 非法（%r），回退默认端口 %s', raw, config.IOT_PORT_DEFAULT)
        return config.IOT_PORT_DEFAULT
    return port


def connect_huawei_iot(uid) -> bool:
    """按用户配置连上华为云 IoTDA。

    app 用 client 设备身份连接；订阅数据转发 Topic（ESP32-E 数据被规则推到这）
    与自身的 user/# 命令反馈。配置不完整或连接失败返回 False。

    接入参数按地块独立：走 `db.load_iot_config()`，地块上填了的字段优先，
    留空的字段回落到账号级配置，因此切换地块即切换到该地块的接入信息。
    """
    cfg = db.load_iot_config(uid)
    if not cfg:
        return False
    host = cfg['iot_host'] or ''
    port = _safe_iot_port(cfg['iot_port'])
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


def reconnect_async(uid) -> None:
    """在后台守护线程里重建该用户的 MQTT 连接。

    `connect_huawei_iot()` 内部的 `client.connect()` 超时可达 60 秒，同步执行会把
    HTTP 请求线程一起卡死（华为云不可达时尤其明显）。这里改成异步：调用方立即返回，
    连接结果由 SocketIO 的 `device_status` 事件推给前端。
    用于两处：设置页保存接入参数后、以及切换地块后（接入信息按地块独立）。
    """
    import threading

    try:
        thread = threading.Thread(
            target=connect_huawei_iot,
            args=(uid,),
            name='iot-reconnect-%s' % uid,
            daemon=True,
        )
        thread.start()
    except Exception:  # noqa: BLE001 - 线程起不来也不能影响调用方结果
        pass


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
