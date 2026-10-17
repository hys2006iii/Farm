import datetime
from functools import wraps
import json
import os
import sqlite3
import threading
import time
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, join_room
from werkzeug.security import check_password_hash, generate_password_hash
import jwt
import paho.mqtt.client as mqtt
import requests

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
            timeout=6,
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


app = Flask(__name__)
# 会话签名密钥：优先读环境变量 FARM_SECRET_KEY（生产建议配置），
# 未设置时用内置兜底密钥，保证本地能直接启动。
app.secret_key = os.environ.get('FARM_SECRET_KEY') or 'smart_irrigation_secret_2026'
socketio = SocketIO(app, cors_allowed_origins='*')
DB_PATH = os.environ.get('FARM_DB_PATH', 'qinghe.db')


@app.after_request
def add_security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'no-referrer')
    # 基础 CSP：允许同源脚本与内联（本项目用了内联 script/style）
    resp.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https:; "
        "font-src 'self' data:;"
    )
    return resp


# 登录限流：连续 5 次失败锁定 10 分钟（按 用户名+IP 维度）
LOGIN_MAX_FAIL = 5
LOGIN_LOCK_SECONDS = 600
_login_fail = {}   # key -> [fail_count, last_fail_ts]
_login_lock = threading.Lock()


def _client_ip():
    # 取真实来源 IP（若有反向代理 X-Forwarded-For 则取其第一段）
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _login_locked(username):
    key = f"{username}:{_client_ip()}"
    with _login_lock:
        entry = _login_fail.get(key)
        if not entry:
            return False
        count, ts = entry
        # 锁定窗口过期则重置
        if time.time() - ts > LOGIN_LOCK_SECONDS:
            _login_fail.pop(key, None)
            return False
        return count >= LOGIN_MAX_FAIL


def _record_login_fail(username):
    key = f"{username}:{_client_ip()}"
    with _login_lock:
        entry = _login_fail.get(key)
        if entry and time.time() - entry[1] <= LOGIN_LOCK_SECONDS:
            _login_fail[key] = (entry[0] + 1, time.time())
        else:
            _login_fail[key] = (1, time.time())


def _clear_login_fail(username):
    key = f"{username}:{_client_ip()}"
    with _login_lock:
        _login_fail.pop(key, None)


# 每个登录用户一套 MQTT 客户端：{uid: {'client': ..., 'device_id': ...}}
mqtt_clients = {}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS configs (
        user_id INTEGER PRIMARY KEY,
        farm_name TEXT DEFAULT '',
        farm_lng TEXT DEFAULT '', farm_lat TEXT DEFAULT '',
        pump_port TEXT DEFAULT 'D9', air_pump_port TEXT DEFAULT 'D5',
        water_sensor_port TEXT DEFAULT 'A0', soil_sensor_port TEXT DEFAULT 'A2',
        weather_domain TEXT, weather_key TEXT, ai_domain TEXT, ai_key TEXT,
        iot_host TEXT, iot_port INTEGER DEFAULT 1883,
        iot_client_id TEXT, iot_user TEXT, iot_pass TEXT, iot_device_id TEXT,
        iot_target_device_id TEXT DEFAULT '', iot_m2m_topic TEXT DEFAULT '/esp32e/data',
        iot_cmd_topic TEXT DEFAULT '/esp32e/cmd',
        webhook_url TEXT DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    # 老库可能没有新加的字段，按需补列
    cursor.execute('PRAGMA table_info(configs)')
    cols = [r[1] for r in cursor.fetchall()]
    if 'farm_lng' not in cols:
        cursor.execute("ALTER TABLE configs ADD COLUMN farm_lng TEXT DEFAULT ''")
    if 'farm_lat' not in cols:
        cursor.execute("ALTER TABLE configs ADD COLUMN farm_lat TEXT DEFAULT ''")
    for col in ('iot_target_device_id', 'iot_m2m_topic', 'iot_cmd_topic'):
        if col not in cols:
            cursor.execute(
                f'ALTER TABLE configs ADD COLUMN {col} TEXT DEFAULT '
                + ("'/esp32e/cmd'" if col == 'iot_cmd_topic' else ("'/esp32e/data'" if col == 'iot_m2m_topic' else "''"))
            )
    if 'farm_name' not in cols:
        cursor.execute("ALTER TABLE configs ADD COLUMN farm_name TEXT DEFAULT ''")
    if 'webhook_url' not in cols:
        cursor.execute("ALTER TABLE configs ADD COLUMN webhook_url TEXT DEFAULT ''")
    conn.commit()
    cursor.execute('''CREATE TABLE IF NOT EXISTS sensor_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        ts INTEGER NOT NULL,
        water_adc INTEGER,
        soil_adc INTEGER
    )''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_history_user_ts ON sensor_history(user_id, ts)'
    )
    # 只保留最近 7 天的数据
    cursor.execute(
        'DELETE FROM sensor_history WHERE ts < ?',
        (int(time.time() * 1000) - 7 * 24 * 3600 * 1000,),
    )
    cursor.execute('''CREATE TABLE IF NOT EXISTS thresh_settings (
        user_id INTEGER PRIMARY KEY,
        humi_down INTEGER DEFAULT 40,
        humi_up INTEGER DEFAULT 80,
        waterlevel_down INTEGER DEFAULT 30,
        waterlevel_up INTEGER DEFAULT 150,
        manual_mode INTEGER DEFAULT 0,
        updated_ts INTEGER
    )''')
    conn.commit()
    conn.close()


def init_geo_cache():
    """反查地名缓存表：同一坐标只调一次外部接口，之后全走缓存。"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS geo_cache (
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ts INTEGER NOT NULL
        )'''
    )
    conn.commit()
    conn.close()


def load_config(uid):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM configs WHERE user_id = ?', (uid,))
    cfg = cursor.fetchone()
    conn.close()
    return cfg


def handle_mqtt_message(uid, topic, content):
    """把 MQTT 报文拆成字段，推给前端，并落一条历史记录。"""
    topic_leaf = topic.split('/')[-1]
    parsed = None
    try:
        parsed = json.loads(content)
    except Exception:
        pass

    values = {}
    if parsed and 'services' in parsed:
        # 华为云物模型上报：services[].properties
        for svc in parsed['services']:
            props = svc.get('properties') or {}
            for k, v in props.items():
                values[k] = v
                socketio.emit(
                    'hw_data',
                    {'type': 'data', 'topic': k, 'payload': str(v)},
                    room=str(uid),
                )
    elif isinstance(parsed, dict) and parsed:
        # 自定义 Topic 直接是 JSON 对象
        for k, v in parsed.items():
            if isinstance(v, (int, float, str, bool)):
                values[k] = v
                socketio.emit(
                    'hw_data',
                    {'type': 'data', 'topic': k, 'payload': str(v)},
                    room=str(uid),
                )
    else:
        # 纯文本，整段当作叶子 Topic 的值
        socketio.emit(
            'hw_data',
            {'type': 'data', 'topic': topic_leaf, 'payload': content},
            room=str(uid),
        )

    # 水位和土壤都齐了，就存一条历史
    try:
        water_adc = values.get('waterlevel')
        soil_adc = values.get('humidity')
        if water_adc is not None and soil_adc is not None:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc)'
                ' VALUES (?, ?, ?, ?)',
                (uid, int(time.time() * 1000),
                 int(float(water_adc)), int(float(soil_adc))),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass


def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    uid = userdata.get('uid')
    if rc == 0:
        m2m_topic = userdata.get('m2m_topic', '/esp32e/data')
        device_id = userdata.get('device_id', '')
        try:
            client.subscribe(m2m_topic)
            if device_id:
                client.subscribe(f'$oc/devices/{device_id}/user/#')
        except Exception:
            pass
        socketio.emit(
            'hw_data', {'type': 'device_status', 'status': 'online'}, room=str(uid)
        )
        socketio.emit(
            'hw_data',
            {'type': 'data', 'topic': 'log', 'payload': '华为云 MQTT 连接成功'},
            room=str(uid),
        )
        if uid in mqtt_clients:
            mqtt_clients[uid]['connected'] = True
    else:
        socketio.emit(
            'hw_data', {'type': 'device_status', 'status': 'offline'}, room=str(uid)
        )


def on_mqtt_disconnect(client, userdata, rc, properties=None, reason_code=None):
    uid = userdata.get('uid')
    if uid in mqtt_clients:
        mqtt_clients[uid]['connected'] = False
    socketio.emit(
        'hw_data', {'type': 'device_status', 'status': 'offline'}, room=str(uid)
    )


def on_mqtt_message(client, userdata, msg):
    uid = userdata.get('uid')
    content = msg.payload.decode('utf-8', errors='replace')
    handle_mqtt_message(uid, msg.topic, content)


def connect_huawei_iot(uid):
    """按用户配置连上华为云 IoTDA。app 用 client 设备身份连接；
    订阅数据转发 Topic（ESP32-E 数据被规则推到这）与自身的 user/# 命令反馈。"""
    cfg = load_config(uid)
    if not cfg:
        return False
    host = cfg['iot_host'] or ''
    port = int(cfg['iot_port'] or 1883)
    client_id = cfg['iot_client_id'] or ''
    user = cfg['iot_user'] or ''
    pw = cfg['iot_pass'] or ''
    # 本机身份：app 用 client 设备，device_id 即 client 自己的设备 ID（用于发布命令主题）
    device_id = cfg['iot_device_id'] or ''
    target_device = cfg['iot_target_device_id'] or ''
    m2m_topic = cfg['iot_m2m_topic'] or '/esp32e/data'
    cmd_topic = cfg['iot_cmd_topic'] or '/esp32e/cmd'

    if not host or not client_id or not user or not pw or not device_id:
        return False

    # 同一用户重连前，先停掉旧连接
    if uid in mqtt_clients:
        try:
            mqtt_clients[uid]['client'].loop_stop()
            mqtt_clients[uid]['client'].disconnect()
        except Exception:
            pass

    try:
        cli = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=client_id
        )
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
        mqtt_clients[uid] = {'client': cli, 'device_id': device_id, 'cmd_topic': cmd_topic, 'connected': False}
        return True
    except Exception:
        return False


# 设备控制下发：app 用 client 设备身份，把命令发到非 $oc 自定义 Topic（默认 /esp32e/cmd，可配置），
# 再由华为云【数据转发规则】把该主题的“设备消息”转发到 ESP32-E（ESP32-E 已订阅 /esp32e/cmd）。
# 关键：用非 $oc 自定义 Topic 才能被平台接受（$oc/.../user/ 下的 Topic 必须在产品里定义，
# 未定义会报 IOTDA.017004 Invalid topic）；且 app 用 client 身份，不抢 ESP32-E 身份。
# 无实体设备时不做任何模拟回执——网页状态只反映真实 MQTT 消息。
def send_property_command(uid, props):
    device, action = next(iter(props.items()))
    if uid not in mqtt_clients or not mqtt_clients[uid].get('connected'):
        return False
    cli = mqtt_clients[uid]['client']
    # 使用该用户配置的命令 Topic（未配则默认 /esp32e/cmd），与华为云转发规则保持一致
    cmd_topic = mqtt_clients[uid].get('cmd_topic') or '/esp32e/cmd'
    message = json.dumps({'device': device, 'action': action}, ensure_ascii=False)
    cli.publish(cmd_topic, message)
    return True


def notify_webhook(uid, title, content):
    """推送告警到用户配置的 webhook（钉钉/企业微信/飞书 通用格式，带兜底适配）。"""
    cfg = load_config(uid)
    if not cfg or not cfg['webhook_url']:
        return False
    url = (cfg['webhook_url'] or '').strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        return False
    # 钉钉机器人安全设置要求消息包含关键词【青禾智灌系统】，固定加在开头
    text = f"【青禾智灌系统】{title}\n{content}"
    payload = {'msgtype': 'text', 'text': {'content': text}}
    try:
        r = requests.post(url, json=payload, timeout=6)
        return r.status_code in (200, 201)
    except Exception:
        return False


@app.route('/api/notify_alert', methods=['POST'])
def api_notify_alert():
    """前端检测到设备告警后调用，转发到用户配置的 webhook。"""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    data = request.json or {}
    msg = (data.get('msg') or '').strip()[:500]
    level = (data.get('level') or 'warn').strip()[:20]
    if not msg:
        return jsonify({'status': 'error', 'message': '缺少告警内容'}), 400
    ok = notify_webhook(session['user_id'], f"[青禾智灌] {level} 告警", msg)
    return jsonify({'status': 'success' if ok else 'skipped', 'sent': ok})


def require_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'status': 'error', 'message': '未授权访问'}), 401

        try:
            claims = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            uid = claims['user_id']
        except Exception:
            return jsonify({'status': 'error', 'message': 'Token无效或过期'}), 401

        return f(uid, *args, **kwargs)

    return wrapper


@app.route('/api/app_login', methods=['POST'])
def api_app_login():
    payload = request.json or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    if _login_locked(username):
        return jsonify({'status': 'error', 'message': '尝试次数过多，请 10 分钟后再试'}), 429
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, username, password FROM users WHERE username=?',
        (username,),
    )
    user = cursor.fetchone()
    conn.close()

    ok = False
    if user:
        stored = user['password']
        if stored.startswith(('pbkdf2:', 'scrypt:', 'sha256:')):
            ok = check_password_hash(stored, password)
        else:
            ok = (stored == password)
            if ok:
                conn = get_db()
                conn.execute(
                    'UPDATE users SET password=? WHERE id=?',
                    (generate_password_hash(password), user['id']),
                )
                conn.commit()
                conn.close()

    if ok:
        _clear_login_fail(username)
        token = jwt.encode({
            'user_id': user['id'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7),
        }, app.secret_key, algorithm='HS256')
        connect_huawei_iot(user['id'])
        return jsonify({
            'status': 'success',
            'message': '登录成功',
            'token': token,
            'username': user['username'],
        })

    _record_login_fail(username)
    return jsonify({'status': 'error', 'message': '账号或密码错误'})


@app.route('/api/app_send_command', methods=['POST'])
@require_token
def api_app_command(uid):
    payload = request.json or {}
    device = payload.get('device')
    action = payload.get('action')
    # 只允许白名单内的属性，防止任意下发
    prop_map = {
        'water_pump': 'water_pump',
        'air_pump': 'air_pump',
    }
    prop = prop_map.get(device)
    if not prop:
        return jsonify({'status': 'error', 'message': '未知设备'}), 400
    ok = send_property_command(uid, {prop: 'on' if action == 'on' else 'off'})
    if not ok:
        return jsonify({'status': 'error', 'message': '设备未连接'})
    return jsonify({'status': 'success', 'message': '指令已发送'})


@socketio.on('connect')
def on_ws_connect():
    uid = session.get('user_id')
    if not uid:
        return False
    join_room(str(uid))
    connect_huawei_iot(uid)
    # 把当前真实华为云连接状态推给前端：仅 broker 真正握手成功(rc==0)才 online，
    # 没配/没连/握手失败都发 offline，避免前端依赖 SocketIO 自身连上就误标"已连接"
    connected = bool(uid in mqtt_clients and mqtt_clients[uid].get('connected'))
    status = 'online' if connected else 'offline'
    socketio.emit('hw_data', {'type': 'device_status', 'status': status}, room=str(uid))


@socketio.on('send_command')
def on_ws_command(data):
    uid = session.get('user_id')
    device = data.get('device')
    action = data.get('action')
    prop_map = {
        'water_pump': 'water_pump',
        'air_pump': 'air_pump',
    }
    prop = prop_map.get(device)
    if not prop:
        return
    send_property_command(uid, {prop: 'on' if action == 'on' else 'off'})


@app.route('/')
def route_root():
    if 'user_id' in session:
        return redirect(url_for('route_index'))
    return render_template('login.html')


@app.route('/index')
def route_index():
    if 'user_id' not in session:
        return redirect(url_for('route_root'))
    return render_template('index.html', username=session.get('username'))


@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    # 输入校验：长度限制，防注入/超大请求
    if not (3 <= len(username) <= 20):
        return jsonify({'status': 'error', 'message': '用户名长度需为 3-20 字符'})
    if not (6 <= len(password) <= 64):
        return jsonify({'status': 'error', 'message': '密码长度需为 6-64 字符'})
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO users (username, password) VALUES (?, ?)',
            (username, generate_password_hash(password)),
        )
        uid = cursor.lastrowid
        cursor.execute('INSERT INTO configs (user_id) VALUES (?)', (uid,))
        conn.commit()
        return jsonify({'status': 'success', 'message': '注册成功'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': '账号已存在'})
    finally:
        conn.close()


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'status': 'error', 'message': '请输入账号和密码'})
    if _login_locked(username):
        return jsonify({'status': 'error', 'message': '尝试次数过多，请 10 分钟后再试'}), 429
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, username, password FROM users WHERE username=?',
        (username,),
    )
    user = cursor.fetchone()
    conn.close()
    if not user:
        _record_login_fail(username)
        return jsonify({'status': 'error', 'message': '账号或密码错误'})
    stored = user['password']
    # 兼容旧库明文密码：匹配则自动升级为哈希
    if stored.startswith(('pbkdf2:', 'scrypt:', 'sha256:')):
        ok = check_password_hash(stored, password)
    else:
        ok = (stored == password)
        if ok:
            conn = get_db()
            conn.execute(
                'UPDATE users SET password=? WHERE id=?',
                (generate_password_hash(password), user['id']),
            )
            conn.commit()
            conn.close()
    if ok:
        _clear_login_fail(username)
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'status': 'success', 'message': '登录成功'})
    _record_login_fail(username)
    return jsonify({'status': 'error', 'message': '账号或密码错误'})


@app.route('/api/logout')
def api_logout():
    session.clear()
    return redirect(url_for('route_root'))


@app.route('/api/change_password', methods=['POST'])
def api_change_password():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': '未授权'}), 401
    data = request.json or {}
    uid = session['user_id']
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''
    if not (6 <= len(new_password) <= 64):
        return jsonify({'status': 'error', 'message': '新密码长度需为 6-64 字符'})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id, password FROM users WHERE id=?', (uid,)
    )
    user = cursor.fetchone()
    if not user or not check_password_hash(user['password'], old_password):
        conn.close()
        return jsonify({'status': 'error', 'message': '原密码错误'})
    cursor.execute(
        'UPDATE users SET password=? WHERE id=?',
        (generate_password_hash(new_password), uid),
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'message': '密码修改成功，请重新登录'})


@app.route('/api/get_config', methods=['GET'])
def api_get_config():
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM configs WHERE user_id = ?', (session['user_id'],)
    )
    cfg = cursor.fetchone()
    conn.close()
    if not cfg:
        return jsonify({'error': '未找到配置'}), 404
    cfg = dict(cfg)
    # 敏感凭据不回显明文：已设置则返回掩码占位，未设置返回空串（前端据此显示占位符）
    for key in ('iot_pass', 'weather_key', 'ai_key'):
        if cfg.get(key):
            cfg[key] = '••••••••'
    return jsonify(cfg)


@app.route('/api/history', methods=['GET'])
def api_history():
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    uid = session['user_id']
    try:
        limit = min(int(request.args.get('limit', 1000)), 5000)
    except Exception:
        limit = 1000
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT ts, water_adc, soil_adc FROM sensor_history'
        ' WHERE user_id = ? ORDER BY ts DESC LIMIT ?',
        (uid, limit),
    )
    rows = cursor.fetchall()
    conn.close()
    result = [
        {'ts': r['ts'], 'water_adc': r['water_adc'], 'soil_adc': r['soil_adc']}
        for r in rows
    ]
    result.reverse()
    return jsonify({'data': result})


@app.route('/api/save_config', methods=['POST'])
def api_save_config():
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    data = request.json or {}
    uid = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    # 敏感字段若是掩码占位（前端未改动），则保留数据库原值，避免被占位符覆盖
    MASK = '••••••••'
    cursor.execute('SELECT * FROM configs WHERE user_id = ?', (uid,))
    old = cursor.fetchone()
    old = dict(old) if old else {}
    def val(key):
        v = data.get(key)
        if v == MASK or v is None:
            return old.get(key)
        return v
    cursor.execute(
        '''
        UPDATE configs SET
            farm_name=?, farm_lng=?, farm_lat=?, pump_port=?, air_pump_port=?, water_sensor_port=?, soil_sensor_port=?,
            weather_domain=?, weather_key=?, ai_domain=?, ai_key=?,
            iot_host=?, iot_port=?, iot_client_id=?, iot_user=?, iot_pass=?, iot_device_id=?,
            iot_target_device_id=?, iot_m2m_topic=?, iot_cmd_topic=?, webhook_url=?
        WHERE user_id=?
    ''',
        (
            val('farm_name'),
            val('farm_lng'),
            val('farm_lat'),
            val('pump_port'),
            val('air_pump_port'),
            val('water_sensor_port'),
            val('soil_sensor_port'),
            val('weather_domain'),
            val('weather_key'),
            val('ai_domain'),
            val('ai_key'),
            val('iot_host'),
            val('iot_port'),
            val('iot_client_id'),
            val('iot_user'),
            val('iot_pass'),
            val('iot_device_id'),
            val('iot_target_device_id'),
            val('iot_m2m_topic'),
            val('iot_cmd_topic'),
            val('webhook_url'),
            uid,
        ),
    )
    conn.commit()
    conn.close()
    connect_huawei_iot(uid)
    return jsonify({'status': 'success', 'message': '配置已更新'})


@app.route('/api/thresh_settings', methods=['GET'])
def api_get_thresh():
    """读取当前用户的阈值与自动/手动模式设定。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    uid = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM thresh_settings WHERE user_id = ?', (uid,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({
            'humi_down': 40, 'humi_up': 80,
            'waterlevel_down': 30, 'waterlevel_up': 150,
            'manual_mode': 0,
        })
    return jsonify(dict(row))


@app.route('/api/thresh_settings', methods=['POST'])
def api_save_thresh():
    """保存当前用户的阈值与自动/手动模式设定（供自动调控使用，刷新不丢）。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    uid = session['user_id']
    data = request.json or {}
    humi_down = int(data.get('humi_down') or 40)
    humi_up = int(data.get('humi_up') or 80)
    wl_down = int(data.get('waterlevel_down') or 30)
    wl_up = int(data.get('waterlevel_up') or 150)
    manual = 1 if data.get('manual_mode') else 0
    # 基本约束：下限不超过上限
    humi_down = min(humi_down, humi_up)
    wl_down = min(wl_down, wl_up)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''INSERT INTO thresh_settings
           (user_id, humi_down, humi_up, waterlevel_down, waterlevel_up, manual_mode, updated_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             humi_down=excluded.humi_down, humi_up=excluded.humi_up,
             waterlevel_down=excluded.waterlevel_down, waterlevel_up=excluded.waterlevel_up,
             manual_mode=excluded.manual_mode, updated_ts=excluded.updated_ts
        ''',
        (uid, humi_down, humi_up, wl_down, wl_up, manual, int(time.time())),
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'message': '设定已保存'})


@app.route('/api/ai_chat', methods=['POST'])
def api_ai_chat():
    if 'user_id' not in session:
        return jsonify({'error': '未授权访问'}), 401
    user_msg = (request.json or {}).get('message', '')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT ai_domain, ai_key FROM configs WHERE user_id = ?',
        (session['user_id'],),
    )
    cfg = cursor.fetchone()
    conn.close()

    if not cfg or not cfg['ai_key']:
        return jsonify({
            'choices': [{
                'message': {
                    'content': '⚠️ 提示：未检测到 AI Key，请在【设置】中配置。'
                }
            }]
        })

    base_url = (cfg['ai_domain'].strip() if cfg['ai_domain'] else 'https://api.deepseek.com')
    # deepseek 等官方接口须用 https，误填 http 时自动纠正，避免返回非 JSON
    if base_url.startswith('http://api.deepseek.com'):
        base_url = 'https://api.deepseek.com'
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {cfg['ai_key']}",
    }
    body = {
        'model': 'deepseek-chat',
        'messages': [
            {
                'role': 'system',
                'content': (
                    '你是一个智能灌溉与水利控制系统助手，请简洁专业地回答中文问题。'
                ),
            },
            {'role': 'user', 'content': user_msg},
        ],
        'stream': False,
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=20)
        if resp.status_code != 200:
            snippet = (resp.text or '(空响应)')[:300]
            return jsonify({'choices': [{'message': {
                'content': f'AI 接口返回异常（HTTP {resp.status_code}）：{snippet}'
            }}]})
        try:
            return jsonify(resp.json())
        except Exception:
            return jsonify({'choices': [{'message': {
                'content': f'AI 接口返回非 JSON 内容（HTTP {resp.status_code}）：{(resp.text or "")[:300]}'
            }}]})
    except Exception as e:
        return jsonify({'choices': [{'message': {'content': f'请求失败: {str(e)}'}}]})


@app.route('/api/forecast', methods=['GET'])
def api_forecast():
    """降雨预报代理：从配置读取和风天气域名与 Key，转发 7 日预报，避免前端跨域。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权访问'}), 401
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT weather_domain, weather_key, farm_lng, farm_lat FROM configs WHERE user_id = ?',
        (session['user_id'],),
    )
    cfg = cursor.fetchone()
    conn.close()
    if not cfg or not cfg['weather_key']:
        return jsonify({'code': 'ERR', 'error': '未配置天气 API Key'})
    domain = (cfg['weather_domain'] or 'm767cfpjh7.re.qweatherapi.com').strip()
    lng = request.args.get('lng') or cfg['farm_lng'] or '118.78'
    lat = request.args.get('lat') or cfg['farm_lat'] or '31.90'
    url = f"https://{domain}/v7/weather/7d?location={lng},{lat}&key={cfg['weather_key']}"
    try:
        r = requests.get(url, timeout=8)
        try:
            return jsonify(r.json())
        except Exception:
            return jsonify({'code': 'ERR', 'error': f'天气接口非 JSON（HTTP {r.status_code}）'})
    except Exception as e:
        return jsonify({'code': 'ERR', 'error': f'天气接口请求失败: {str(e)}'})


@app.route('/api/reverse_geocode')
def api_reverse_geocode():
    """逆地理编码：返回具体位置（市·区·街道·社区，简体）。唯一反查源 Photon(komoot/OSM)，
    结果按坐标缓存到 DB，重复刷新不再打外部接口，避免浏览器跨域与免费额度限流。"""
    if 'user_id' not in session:
        return jsonify({'error': '未授权'}), 401
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    if not lat or not lng:
        return jsonify({'error': '缺少坐标'}), 400
    try:
        flat_lat = float(lat)
        flat_lng = float(lng)
    except Exception:
        return jsonify({'error': '坐标格式错误'}), 400

    key = f"{round(flat_lat, 4)},{round(flat_lng, 4)}"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'CREATE TABLE IF NOT EXISTS geo_cache (key TEXT PRIMARY KEY, name TEXT NOT NULL, ts INTEGER NOT NULL)'
    )
    cursor.execute('SELECT name FROM geo_cache WHERE key=?', (key,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return jsonify({'name': row['name']})

    # 唯一反查源：Photon(komoot/OSM)，免 Key、简体、可下探社区级
    name = photon_reverse(flat_lat, flat_lng)
    if name:
        cursor.execute(
            'INSERT OR REPLACE INTO geo_cache (key, name, ts) VALUES (?,?,?)',
            (key, name, int(time.time())),
        )
        conn.commit()
        conn.close()
        return jsonify({'name': name})
    # 都没解析到：按坐标兜底（不缓存，便于下次重试）
    conn.close()
    return jsonify({'name': f"E: {flat_lng:.2f}°, N: {flat_lat:.2f}°"})


if __name__ == '__main__':
    init_db()
    init_geo_cache()
    port = int(os.environ.get('PORT', '5000'))
    # 生产环境建议 FARM_DEBUG=0；debug 模式会暴露调试器，不要对外开放
    debug = os.environ.get('FARM_DEBUG', '1') == '1'
    socketio.run(
        app, debug=debug, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True
    )
