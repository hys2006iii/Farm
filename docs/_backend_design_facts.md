# 后端设计事实清单（代码为准）

> 本文件由 **architect** 维护，供 `docs/20_概要设计说明书.md` 与 `docs/30_详细设计说明书.md` 核对准确性。
> **所有路径、字段名、函数签名均逐字取自当前代码**，不是设计意图，而是实现事实。
> 生成基准：`qinghe/**` + `app.py` + `server.py`（截至 `ccc2e15`）。

---

## 一、模块职责与对外函数签名

### 1.1 包级入口

| 文件 | 职责 | 对外符号 |
| --- | --- | --- |
| `qinghe/__init__.py` | 应用工厂：装配 Flask、注册蓝图/安全头/错误处理、绑定 SocketIO | `socketio = SocketIO()`（进程级单例，未绑 app）<br>`create_app(init_storage: bool = True) -> tuple`（返回 `(app, socketio)`）<br>`_warn_default_secret() -> None`<br>`_register_security_headers(app) -> None`<br>`_register_blueprints(app) -> None`<br>`_register_error_handlers(app) -> None` |
| `app.py` | 入口：`from qinghe import config, create_app; app, socketio = create_app()`；`__main__` 调 `socketio.run(app, debug=debug, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)` | `app`、`socketio` |
| `server.py` | waitress 生产启动器（多线程、打印局域网地址、waitress 缺失回退 `socketio.run`） | `main()` |

### 1.2 配置层

**`qinghe/config.py`** —— 纯常量与 3 个环境读取函数，无副作用。

```python
is_debug() -> bool        # FARM_DEBUG 默认 '0'（生产安全）
get_secret_key() -> str   # FARM_SECRET_KEY，缺失时回退 FALLBACK_SECRET_KEY
get_db_path() -> str      # 运行时读 FARM_DB_PATH，便于测试切库
```

常量分组（**注意 `get_db_path()` 在 config 而非 db**）：

- 基础：`APP_NAME`、`DB_PATH`、`FALLBACK_SECRET_KEY = 'smart_irrigation_secret_2026'`、`DEFAULT_PORT = 5000`、`DB_TIMEOUT = 10`
- 历史：`HISTORY_KEEP_DAYS = 7`、`HISTORY_DEFAULT_LIMIT = 1000`、`HISTORY_MIN_LIMIT = 1`、`HISTORY_MAX_LIMIT = 5000`
- 安全：`CSP_POLICY`、`SECURITY_HEADERS`、`LOGIN_MAX_FAIL = 5`、`LOGIN_LOCK_SECONDS = 600`、`MASK = '••••••••'`
- IoT：`IOT_PORT_MIN = 1`、`IOT_PORT_MAX = 65535`、`IOT_PORT_DEFAULT = 1883`、`DEFAULT_M2M_TOPIC = '/esp32e/data'`、`DEFAULT_CMD_TOPIC = '/esp32e/cmd'`
- 阈值：`THRESH_DEFAULTS = {'humi_down': 40, 'humi_up': 80, 'waterlevel_down': 30, 'waterlevel_up': 150, 'manual_mode': 0}`
- 外部服务：`DEFAULT_WEATHER_DOMAIN = 'm767cfpjh7.re.qweatherapi.com'`、`DEFAULT_AI_DOMAIN = 'https://api.deepseek.com'`、`DEFAULT_AI_MODEL = 'deepseek-chat'`、`TIMEOUT_PHOTON = 6`、`TIMEOUT_WEBHOOK = 6`、`TIMEOUT_WEATHER = 8`、`TIMEOUT_AI = 20`
- 量程标定：`ADC_MAX = 4095.0`、`WATER_FS_MM = 300.0`、`DO_MIN_MGL/MAX_MGL = 0/20`、`EH_MIN_MV/MAX_MV = -150/300`
- RORI：`W_EH = 0.35`、`W_DO = 0.35`、`W_WATER_SOIL = 0.30`、`GAMMA = 0.5`、`EH_SAFE_MV = 300.0`、`EH_SPAN_MV = 450.0`、`DO_SAFE_MGL = 8.0`、`WATER_DEADBAND_MM = 5.0`、`WATER_RISK_SPAN_MM = 100.0`、`RORI_HEAVY = 70`、`RORI_MODERATE = 40`
- 动态阈值：`RAIN_WEIGHTS = [1.0, 0.9, 0.7, 0.5, 0.4, 0.3]`、`H_ROOT = 200.0`、`ALPHA_LOW = 0.95`、`ALPHA_MID = 0.75`、`ALPHA_HIGH = 0.45`、`ALPHA_LOW_MAX = 10.0`、`ALPHA_MID_MAX = 50.0`、`EFF_LOWER_FLOOR = 45.0`、`EFF_UPPER_RAIN = 15.0`、`EFF_UPPER_BONUS = 15.0`、`EFF_UPPER_CAP = 100.0`
- 告警：`ALERT_COOLDOWN_SECONDS = 60`、`ALERT_KEY_PREFIX = '【青禾智灌系统】'`
- 落库队列：`HISTORY_QUEUE_MAX = 2000`、`HISTORY_FLUSH_INTERVAL = 1.0`、`HISTORY_FLUSH_BATCH = 200`

### 1.3 数据访问层

**`qinghe/db.py`**

```python
get_db() -> sqlite3.Connection          # timeout=10, row_factory=Row, PRAGMA journal_mode=WAL, busy_timeout=10000
init_db(force: bool = False) -> None    # 建 4 张基表 + 增量迁移列 + 索引 + 清理 7 天前历史
init_geo_cache() -> None
create_user(username: str, password_hash: str)      # 重名返回 None（IntegrityError 吞掉）
get_user_by_username(username: str)
get_user_by_id(uid: int)
update_password(uid: int, password_hash: str) -> None
load_config(uid: int)
load_ai_config(uid: int)
load_weather_config(uid: int)
save_config(uid: int, values: dict) -> None
insert_history_rows(rows) -> None                   # executemany
query_history(uid: int, limit: int)
load_thresholds(uid: int)
save_thresholds(uid, humi_down, humi_up, wl_down, wl_up, manual) -> None   # ON CONFLICT UPSERT
get_geo_cache(key: str)                 # 表不存在返回 None
set_geo_cache(key: str, name: str) -> None
CONFIG_COLUMNS = (...21 列元组...)
```

### 1.4 认证与安全

**`qinghe/auth.py`**

```python
# 公开限流入口（路由层只允许用这三个，不得调用下划线私有函数）
login_throttle(username: str) -> bool
record_login_failure(username: str) -> None
clear_login_failures(username: str) -> None

reset_login_failures() -> None          # 测试用，清空全部限流状态
is_password_hash(stored: str) -> bool   # 前缀 ('pbkdf2:', 'scrypt:', 'sha256:')
verify_password(stored: str, password: str) -> bool
upgrade_plaintext_password(uid: int, password: str) -> None
hash_password(password: str) -> str
issue_token(uid: int, days: int = 7) -> str     # HS256，claims 含 user_id 与 exp
authenticate(username: str, password: str)      # -> (user_row, ok)
require_token(f)                                # 装饰器，用 current_app.secret_key
current_uid()
```

限流 key = `f"{username}:{_client_ip()}"`；`_client_ip()` 取 `X-Forwarded-For` 首段，否则 `request.remote_addr or 'unknown'`。

### 1.5 决策层（纯函数，无 IO）

**`qinghe/irrigation.py`** —— 与前端 `templates/index.html` 公式逐字一致。

```python
adc_to_water_mm(water_adc) -> float     # clamp(adc/4095*300, 0, 300)
adc_to_soil_pct(soil_adc) -> float      # clamp((4095-adc)/4095*100, 0, 100)
clamp(value, low, high)
risk_eh(eh_mv) -> float                 # clamp((300-eh)/450, 0, 1)
risk_do(do_mgl) -> float                # clamp((8.0-do)/8.0, 0, 1)
risk_water(water_mm) -> float           # water_mm>5 ? clamp((water_mm-5)/100,0,1) : 0
risk_soil(soil_pct) -> float            # clamp(soil_pct/100, 0, 1)
compute_rori(water_adc, soil_adc, do_mgl, eh_mv) -> float
classify_rori(rori) -> dict             # {'code','name','strategy'}
compute_p6d(daily_precips) -> float
alpha_of(p6d: float) -> float
compute_dynamic_threshold(humi_down, humi_up, daily_precips) -> dict
decide_control(water_mm, soil_pct, rori, thresholds: dict,
               state: dict = None, dt: dict = None) -> dict
PUMP_STATE_ON/OFF/HOLD/OK = 'on'/'off'/'hold'/'ok'
```

`compute_rori` 公式（**与 `templates/index.html:1309-1322` 一致**）：

```
pRisk = W_EH*sEh + W_DO*sDo + W_WATER_SOIL*max(riskWater, riskSoil) + GAMMA*riskWater*riskSoil
RORI  = clamp(pRisk, 0, 1) * 100
```

`classify_rori` 分级：

| 条件 | code | name | strategy |
| --- | --- | --- | --- |
| `>= 70` | 2 | 重度厌氧 | 重度厌氧预警，加气机全满载强制增氧 |
| `>= 40` | 1 | 中度缺氧 | 根区微量缺氧，周期性脉冲加气补氧 |
| 否则 | 0 | 安全运行 | 根区有氧环境优良，加气机低耗待机 |

`compute_dynamic_threshold` 返回键（**固定 8 个**）：`P6d`、`alpha`、`effLower`、`effUpper`、`baseLower`、`baseUpper`、`hasForecast`、`rainComing`。

> ⚠️ **易误读点**：`effLower = max(EFF_LOWER_FLOOR, humi_down - (alpha*P6d/H_ROOT)*100)`，
> `EFF_LOWER_FLOOR = 45.0` 是**无条件保底**。默认 `humi_down = 40` 时 `effLower` 恒为 `45.0`
> （反而比基础下限高 5），只有 `humi_down > 45` 时降雨前馈才会真正下调阈值。
> 这不是 bug，是前端既有行为，重构时必须保留。

### 1.6 设备接入层

**`qinghe/iot.py`**

```python
mqtt_clients = {}                       # {uid: {'client','device_id','cmd_topic','connected'}}
mqtt_lock = threading.RLock()
get_client(uid)                         # 返回副本
is_connected(uid) -> bool
set_connected(uid, connected: bool) -> None
clear_clients() -> None
class HistoryWriter(maxsize=2000, flush_interval=1.0, batch=200)
    enqueue(uid, ts, water_adc, soil_adc) -> None    # 满则丢最旧，不阻塞
    flush_once() -> int                              # 失败重新入队
    start() / stop(timeout=2.0)
history_writer = HistoryWriter()
start_history_writer() -> None
flush_history() -> int
HISTORY_FIELDS = ('waterlevel', 'humidity')
PROP_MAP = {'water_pump': 'water_pump', 'air_pump': 'air_pump'}   # 唯一来源
parse_mqtt_payload(topic: str, content: str)     # -> (topic_leaf, values, messages)
extract_history_sample(values: dict, now_ms: int = None)   # -> (water_adc, soil_adc, ts) | None
handle_mqtt_message(uid, topic, content, emit=None, writer=None) -> None   # 非阻塞
on_mqtt_connect(client, userdata, flags, rc, properties=None)
on_mqtt_disconnect(client, userdata, rc, properties=None, reason_code=None)
on_mqtt_message(client, userdata, msg)
connect_huawei_iot(uid) -> bool
send_property_command(uid, props) -> bool
```

### 1.7 告警、实时、天气、AI

```python
# qinghe/alerts.py
notify_webhook(uid: int, title: str, content: str) -> bool
class AlertDeduper: __init__(cooldown=60); should_emit(key, now=None) -> bool; reset()
evaluate_alerts(soil_pct, water_mm, humi_lower, humi_upper,
                water_upper, rori=None) -> list   # 每项 {'level','code','msg'}

# qinghe/alert_center.py
push_alert(uid, level, code, content) -> {'id','deduped','pushed'}
list_alerts(uid, limit=100, since_ts=0) -> list[dict]
ack_alert(uid, alert_id) -> bool
prune_alerts(keep_days=7) -> int
evaluate_and_push(uid, soil_pct, water_mm, rori, humi_lower, humi_upper,
                  water_lower, water_upper) -> list[dict]

# qinghe/realtime.py
PROP_MAP = iot.PROP_MAP                 # 别名，唯一来源在 iot
emit_hw_data(uid, payload) -> None      # socketio.emit('hw_data', payload, room=str(uid))
start_device_watcher(interval=None)     # 只在进程入口调用一次
register_events(sock) -> None

# qinghe/weather.py
_pick_admin(values)
photon_reverse(lat, lng)
geo_key(lat: float, lng: float) -> str          # f"{round(lat,4)},{round(lng,4)}"
geo_fallback_text(lat: float, lng: float) -> str
geo_lookup(lat: float, lng: float)              # -> (name, cached)
build_forecast_url(domain: str, lng, lat, key: str) -> str
fetch_forecast(domain: str, lng, lat, key: str) -> dict
forecast_failed(payload) -> bool

# qinghe/ai.py
SYSTEM_PROMPT = '你是一个智能灌溉与水利控制系统助手，请简洁专业地回答中文问题。'
load_ai_config(uid: int)
normalize_base_url(ai_domain) -> str
build_chat_request(ai_domain, user_msg: str)
chat(ai_domain, ai_key, user_msg: str) -> dict
```

### 1.8 NF1–NF7 新增模块

| 模块 | 职责 | 关键常量 |
| --- | --- | --- |
| `qinghe/alert_center.py` | 告警落库、60 秒去重冷却、webhook 重试推送 | `ALERT_LEVELS=('info','warning','danger')`、`CONTENT_MAX_LEN=500`、`MAX_LIMIT=500`、`PUSH_RETRY_DELAYS=(0.0,0.5,1.0)` |
| `qinghe/logbook.py` | 运行日志异步批量落库 | `LOG_SOURCES=('system','device','auto','manual','plan','config')`、`QUEUE_MAX=1000`、`BATCH_SIZE=20`、`FLUSH_INTERVAL=1.0`、`MAX_LIMIT=1000` |
| `qinghe/heartbeat.py` | 设备心跳与离线巡检 | `DEVICE_OFFLINE_SECONDS=30`、`WATCH_INTERVAL=5.0` |
| `qinghe/planner.py` | AI 决策预案（AI 失败自动规则回退） | `PLAN_TTL_SECONDS=600`、`ALLOWED_DEVICES=('air_pump','water_pump')`、`ALLOWED_ACTIONS=('on','off')`、`AI_TIMEOUT_SECONDS=25` |
| `qinghe/metrics.py` | 节水减碳工程估算 | `DEVICES=('air_pump','water_pump')`、`MAX_DAYS=90` |
| `qinghe/autocontrol.py` | 服务端自动调控开关与执行 | `AUTO_MIN_INTERVAL_SECONDS=60`、`DEVICES=('air_pump','water_pump')` |
| `qinghe/routes/export_routes.py` | CSV 导出（UTF-8 BOM） | `MAX_EXPORT_ROWS=50000` |

---

## 二、数据库表 DDL（逐字段）

> 表名与既有 5 张表的字段名**不得改名**（软著材料已记载）；新增表可自由设计。
> 全部 DDL 由 `sqlite_master` 实测导出。

### 2.1 既有表（字段名冻结）

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE configs (
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
);

CREATE TABLE sensor_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    water_adc INTEGER,
    soil_adc INTEGER,
    do_mgl REAL,        -- 新增列（可加不可改）
    eh_mv REAL          -- 新增列（可加不可改）
);

CREATE TABLE thresh_settings (
    user_id INTEGER PRIMARY KEY,
    humi_down INTEGER DEFAULT 40,
    humi_up INTEGER DEFAULT 80,
    waterlevel_down INTEGER DEFAULT 30,
    waterlevel_up INTEGER DEFAULT 150,
    manual_mode INTEGER DEFAULT 0,
    updated_ts INTEGER
);

CREATE TABLE geo_cache (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ts INTEGER NOT NULL
);
```

`configs` 增量迁移列（`db._CONFIG_MIGRATIONS`）：`farm_lng`、`farm_lat`、`iot_target_device_id`、`iot_m2m_topic`、`iot_cmd_topic`、`farm_name`、`webhook_url`。

### 2.2 新增表

```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,        -- info | warning | danger
    code TEXT NOT NULL,         -- soil_low | soil_high | water_high | water_low
                                -- | rori_medium | rori_high | auto_action
    content TEXT NOT NULL,
    acked INTEGER DEFAULT 0
);

CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,        -- info | warning | error
    source TEXT NOT NULL,       -- system | device | auto | manual | plan | config
    message TEXT NOT NULL
);

CREATE TABLE device_status (
    user_id INTEGER PRIMARY KEY,
    last_seen_ts INTEGER NOT NULL,
    online INTEGER NOT NULL DEFAULT 0,
    last_reason TEXT DEFAULT ''
);

CREATE TABLE plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending|confirmed|rejected|expired|failed
    context_json TEXT NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    proposal_json TEXT NOT NULL,
    decided_ts INTEGER,
    apply_result TEXT DEFAULT ''
);

CREATE TABLE pump_runtime (
    user_id INTEGER NOT NULL,
    device TEXT NOT NULL,
    day TEXT NOT NULL,
    seconds INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, device, day)
);

CREATE TABLE auto_control (
    user_id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    last_action_ts INTEGER DEFAULT 0,
    state_json TEXT DEFAULT ''
);
```

### 2.3 索引

```sql
CREATE INDEX IF NOT EXISTS idx_history_user_ts     ON sensor_history(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_alerts_user_ts      ON alerts(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_logs_user_ts        ON logs(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_plans_user_ts       ON plans(user_id, ts);
CREATE INDEX IF NOT EXISTS idx_pump_runtime_user_day ON pump_runtime(user_id, day);
```

### 2.4 时间戳口径

**全库统一毫秒整数**（`int(time.time() * 1000)`），字段名一律 `ts`；`day` 为本地日期字符串 `YYYY-MM-DD`。

---

## 三、HTTP 接口清单

> 除标注外，**鉴权方式均为「会话 Cookie」**（`session['user_id']`），未登录返回 401。
> `JWT` 列标注 Bearer Token（`Authorization: Bearer <token>`）。

### 3.1 页面与静态

| 方法 | 路径 | 请求体 | 响应 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| GET | `/` | — | HTML（index.html） | 200 | 无 |
| GET | `/index` | — | HTML（index.html） | 200 | 无 |
| GET | `/static/<path:filename>` | — | 静态资源 | 200 | 无 |

### 3.2 认证

| 方法 | 路径 | 请求体字段 | 响应字段 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/register` | `username`, `password` | `status`, `message` | 200 / **400** | 无 |
| POST | `/api/login` | `username`, `password` | `status`, `message` | 200 / **400** / **401** / **429** | 无 |
| GET | `/api/logout` | — | 302 重定向到 `/` | 302 | 无 |
| POST | `/api/change_password` | `old_password`, `new_password` | `status`, `message` | 200 / 400 / 401 | 会话 |
| POST | `/api/app_login` | `username`, `password` | `status`, `message`, `token`, `username` | 200 / 429 | 无 |

固定文案（**逐字，前端已依赖**）：

- 注册：`'用户名长度需为 3-20 字符'`、`'密码长度需为 6-64 字符'`、`'账号已存在'`、`'注册成功'`
- 登录：`'请输入账号和密码'`、`'账号或密码错误'`、`'登录成功'`
- 限流（429）：`'尝试次数过多，请 10 分钟后再试'`
- 改密：`'未授权'`(401)、`'新密码长度需为 6-64 字符'`、`'原密码错误'`、`'密码修改成功，请重新登录'`

**状态码语义（响应体形状恒为 `{'status': ..., 'message': ...}`，仅状态码语义化）**：

| 接口 | 200 | 400 | 401 | 429 |
| --- | --- | --- | --- | --- |
| `/api/register` | 注册成功 | 用户名/密码长度非法、账号已存在 | — | — |
| `/api/login` | 登录成功 | 账号或密码为空 | 账号或密码错误 | 已锁定 |

前端 `static/js/login.js` 两个处理函数都是 `.then(r => r.json())` 后按 `data.status` 分支
（`login.js:45`、`login.js:74`），**不读 `res.ok` / HTTP 状态码**，故状态码语义化不影响前端。

### 3.3 配置

| 方法 | 路径 | 请求体 / 查询 | 响应字段 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/get_config` | — | 全部 configs 列；`iot_pass`/`weather_key`/`ai_key` 非空时替换为 `'••••••••'` | 200 / 401 / 404 | 会话 |
| POST | `/api/save_config` | configs 各列（缺省或 `'••••••••'` 或 `null` 保留旧值） | `status`, `message` | 200 / 401 | 会话 |
| GET | `/api/thresh_settings` | — | `humi_down`, `humi_up`, `waterlevel_down`, `waterlevel_up`, `manual_mode` | 200 / 401 | 会话 |
| POST | `/api/thresh_settings` | 同上 | `status`, `message` | 200 / 401 | 会话 |

- 未登录响应体：`{'error': '未授权'}` + 401
- 无配置：`{'error': '未找到配置'}` + 404
- 保存成功：`{'status': 'success', 'message': '配置已更新'}`；阈值成功：`{'status': 'success', 'message': '设定已保存'}`
- `iot_port` 校验 1~65535，非法**保留旧值**；阈值 clamp：湿度 0~100、水位 0~300；`humi_down = min(humi_down, humi_up)`、`wl_down = min(wl_down, wl_up)`

### 3.4 数据

| 方法 | 路径 | 查询 / 请求体 | 响应字段 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/history` | `limit`（clamp 1~5000，默认 1000） | `data[]`，每项 `ts`, `water_adc`, `soil_adc`, `do_mgl`, `eh_mv`（**升序**；后两项早期数据为 `null`） | 200 / 401 | 会话 |
| GET | `/api/forecast` | `lng`, `lat` | 上游 JSON 原样透传；失败 `{'code':'ERR','error':...}` | 200 / **502** / 401 | 会话 |
| GET | `/api/reverse_geocode` | `lat`, `lng` | `name` | 200 / 400 / 401 | 会话 |
| POST | `/api/notify_alert` | `msg`(≤500), `level`(≤20) | `status`, `sent` | 200 / 400 / 401 | 会话 |

- `/api/history` 未登录 `{'error':'未授权'}`；`/api/forecast`、`/api/notify_alert` 未登录 `{'error':'未授权访问'}`（**注意文案不同**）
- `/api/forecast` 失败（未配置 Key / 上游异常 / 上游非 JSON）统一 **502**，body 保持 `{'code':'ERR','error':...}`（前端只读 body 不读 `r.ok`）
- `/api/reverse_geocode`：缺坐标 `{'error':'缺少坐标'}` 400；格式错 `{'error':'坐标格式错误'}` 400；未命中返回 `{'name': f"E: {lng:.2f}°, N: {lat:.2f}°"}` 且不缓存
- `/api/notify_alert`：空 msg `{'status':'error','message':'缺少告警内容'}` 400；成功 `{'status':'success'|'skipped','sent':bool}`

### 3.5 AI 与指令

| 方法 | 路径 | 请求体 | 响应 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/ai_chat` | `message`（兼容 `messages`） | `{'choices':[{'message':{'content':...}}]}` | 200 / 401 | 会话 |
| POST | `/api/app_send_command` | `device`, `action` | `status`, `message` | 200 / 400 | **JWT** |

- `/api/ai_chat` 未登录 `{'error':'未授权访问'}`；无 Key 返回 `{'choices':[{'message':{'content':'⚠️ 提示：未检测到 AI Key，请在【设置】中配置。'}}]}`
- `/api/app_send_command`：未知设备 `{'status':'error','message':'未知设备'}` **400**；设备未连接 `{'status':'error','message':'设备未连接'}` **200**；成功 `{'status':'success','message':'指令已发送'}`

### 3.6 NF1–NF3 监控

| 方法 | 路径 | 查询 / 请求体 | 响应字段 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/alerts` | `limit`(1~500, 默认 100), `since_ts` | `status`, `count`, `alerts[]` | 200 / 400 / 401 | 会话 |
| POST | `/api/alerts/ack` | `id` | `status`, `id`, `acked` | 200 / 400 / 404 / 401 | 会话 |
| POST | `/api/alerts/ack_all` | `codes`（可选，字符串数组） | `status`, `acked` | 200 / 400 / 401 | 会话 |
| GET | `/api/logs` | `limit`(1~1000, 默认 200), `since_ts` | `status`, `count`, `logs[]` | 200 / 400 / 401 | 会话 |
| GET | `/api/device_status` | `offline_seconds`(1~86400) | `status`, `online`, `last_seen_ts`, `silent_seconds` | 200 / 400 / 401 | 会话 |

- 未登录统一 `{'error': '未登录'}` + 401（**与 3.2~3.5 的文案不同**）
- `alerts[]` 每项：`rid`(1 基序号), `id`, `ts`, `level`, `code`, `content`, `acked`
- `logs[]` 每项：`rid`, `ts`, `level`, `source`, `message`
- `/api/alerts/ack` 非本人告警返回 404 `'告警不存在或不属于当前用户'`

### 3.7 NF4–NF5 预案与指标

| 方法 | 路径 | 请求体 / 查询 | 响应字段 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| POST | `/api/plan/propose` | `question`(≤500) | `plan_id`, `status`, `reasoning`, `actions[]`, `summary`, `risk`, `ai_used` | 200 / 400 / 500 / 401 | 会话 |
| POST | `/api/plan/confirm` | `id` | `ok`, `applied[]`, `failed[]`, `status`, `plan_id` | 200 / 400 / 401 | 会话 |
| POST | `/api/plan/reject` | `id`, `reason`(≤200) | `ok`, `id` | 200 / 400 / 401 | 会话 |
| GET | `/api/plans` | `limit`(1~100, 默认 20) | `plans[]`, `count` | 200 / 400 / 401 | 会话 |
| GET | `/api/metrics` | `days`(1~90, 默认 7) | `days`, `water_liters`, `pump_minutes`, `air_minutes`, `ch4_saved_g`, `co2e_saved_g`, `method`, `series[]` | 200 / 400 / 401 | 会话 |
| GET | `/api/auto_control` | — | `enabled`, `last_action_ts`, `state` | 200 / 401 | 会话 |
| POST | `/api/auto_control` | `enabled`(bool) | 同 GET | 200 / 400 / 401 | 会话 |

- `actions[]` 每项：`device`, `action`, `reason`
- 预案 TTL **600 秒**，过期自动置 `expired`
- `metrics.method` 明示「工程估算非实测」口径，前端必须原样展示

### 3.8 NF6 导出

| 方法 | 路径 | 查询 | 响应 | 状态码 | 鉴权 |
| --- | --- | --- | --- | --- | --- |
| GET | `/api/export/history.csv` | `limit`(默认 5000, 上限 50000), `since_ts` | `text/csv`，UTF-8 + BOM | 200 / 400 / 401 | 会话 |
| GET | `/api/export/alerts.csv` | `limit`(默认 200, 上限 50000), `since_ts` | 同上 | 200 / 400 / 401 | 会话 |

表头：历史 `['时间','时间戳','水位ADC','土壤ADC','溶解氧mg/L','氧化还原电位mV']`；告警 `['时间','时间戳','级别','类型','内容','已确认']`。

---

## 四、SocketIO 事件

| 事件名 | 方向 | 载荷 | 行为 |
| --- | --- | --- | --- |
| `connect` | C→S | — | 无 `session['user_id']` 返回 `False` 拒绝；否则 `join_room(str(uid))`、`connect_huawei_iot(uid)`、推 `device_status` |
| `send_command` | C→S | `{'device': str, 'action': str}` | 白名单 `PROP_MAP` 命中才下发；`action == 'on'` 精确匹配才 `'on'`，其余一律 `'off'` |
| `hw_data` | S→C | 见下表 | 服务端推给房间 `str(uid)` |

`hw_data` 载荷形态（前端 `templates/index.html` 解析）：

| `type` | 字段 | 含义 |
| --- | --- | --- |
| `data` | `topic`, `payload`(字符串) | 单属性上报 / 纯文本日志 |
| `device_status` | `status`(`online`/`offline`)，可选 `last_seen_ts`, `silent_seconds`, `ts` | 连接状态与离线巡检 |

---

## 五、MQTT Topic 与数据流转

### 5.1 Topic 清单

| 方向 | Topic | 来源 | 说明 |
| --- | --- | --- | --- |
| 上行 | `/esp32e/data` | `configs.iot_m2m_topic`（默认 `DEFAULT_M2M_TOPIC`） | 设备属性上报 |
| 上行 | `$oc/devices/<device_id>/user/#` | `configs.iot_device_id` | 华为云平台命令反馈 |
| 下行 | `/esp32e/cmd` | `configs.iot_cmd_topic`（默认 `DEFAULT_CMD_TOPIC`） | 指令下发；**必须用非 `$oc` 自定义 Topic 才能被平台接受** |

连接参数：`mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=...)`，失败回退 `mqtt.Client(client_id=...)`；`connect(host, port, 60)` + `loop_start()`；重连前先 `loop_stop()` + `disconnect()` 旧 client。

### 5.2 上行数据流转

```
设备 → 华为云 IoTDA → MQTT broker
  → on_mqtt_message(client, userdata, msg)
      msg.payload.decode('utf-8', errors='replace')
  → handle_mqtt_message(uid, topic, content)          [MQTT 回调线程，必须非阻塞]
      ├─ parse_mqtt_payload(topic, content) → (topic_leaf, values, messages)
      │    有 services → 遍历 svc['properties'] 逐字段成消息
      │    否则 parsed 非空 dict → 逐标量字段成消息
      │    否则 → 纯文本单条消息
      ├─ emit_hw_data(uid, {'type':'data','topic':k,'payload':str(v)})   逐条推前端
      ├─ _feed_insight(uid, values, now_ms)           [旁路分发，每子系统独立 try/except]
      │     1) heartbeat.mark_seen(uid, now_ms)                       心跳
      │     2) planner.update_telemetry(uid, **telemetry)             预案上下文缓存
      │     3) metrics.note_pump_state(uid, device, state, now_ms)    泵时长（air_pump/water_pump）
      │     4) autocontrol.evaluate(uid, telemetry)                   自动调控（默认关闭）
      │     5) alert_center.evaluate_and_push(...)                    告警
      │        ↑ 仅第 5 步限频：_ALERT_EVAL_INTERVAL = 10.0 秒/用户
      │          （_alert_eval_last + _alert_eval_lock 保护，避免每条上报都查库）
      └─ history_writer.enqueue(...)                  [非阻塞入队，满则丢最旧]
                                    ↓
                        HistoryWriter 后台单线程
                          每 1s 或攒够 200 条 flush_once()
                          → db.insert_history_rows()  [executemany 批量提交]
```

**落库条件**：`values` 同时含 `waterlevel` 与 `humidity` 才写 `sensor_history`（`HISTORY_FIELDS`），值 `int(float(x))`，`ts = int(time.time()*1000)`。

### 5.3 下行指令流转

```
前端 send_command / POST /api/app_send_command
  → send_property_command(uid, {'water_pump': 'on'})
      device, action = next(iter(props.items()))
      未连接 → False
      json.dumps({'device': device, 'action': action}, ensure_ascii=False)
      publish 到 cmd_topic
```

---

## 六、控制决策流程

```
                    ┌─────────────────────────────┐
                    │ 遥测: water_adc soil_adc     │
                    │       do_mgl    eh_mv        │
                    └──────────────┬──────────────┘
                                   ▼
              adc_to_water_mm / adc_to_soil_pct  （量程换算）
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │ risk_eh / risk_do / risk_water / risk_soil        │
        │   pRisk = 0.35·sEh + 0.35·sDo                     │
        │         + 0.30·max(riskWater, riskSoil)           │
        │         + 0.5·riskWater·riskSoil                  │
        │   RORI = clamp(pRisk,0,1) × 100                   │
        └───────────────────┬──────────────────────────────┘
                            ▼
                  classify_rori(rori)
        ┌───────────────┬───────────────┬──────────────────┐
        │ < 40 安全     │ 40~70 中度缺氧 │ ≥ 70 重度厌氧     │
        │ code 0        │ code 1        │ code 2            │
        │ 加气机待机     │ 脉冲加气       │ 满载强制增氧       │
        └───────────────┴───────────────┴──────────────────┘
                            │
                            │   ┌────── 动态阈值融合 ──────┐
                            │   │ compute_p6d(daily)      │
                            │   │   → P6d = Σ ω_t · P_t   │
                            │   │ alpha_of(P6d)           │
                            │   │   ≤10 → 0.95            │
                            │   │   ≤50 → 0.75            │
                            │   │   >50 → 0.45            │
                            │   │ effLower = max(45,      │
                            │   │   humi_down             │
                            │   │   - alpha·P6d/200×100)  │
                            │   │ effUpper = P6d≥15 ?     │
                            │   │   min(100, humi_up+15)  │
                            │   │   : humi_up             │
                            │   │ rainComing = P6d ≥ 15   │
                            │   └────────────┬────────────┘
                            ▼                ▼
                    decide_control(water_mm, soil_pct, rori,
                                   thresholds, state, dt)
        ┌───────────────────────────────────────────────────┐
        │ 气泵：effCmd = cmdCode                            │
        │       if dt.rainComing and effCmd < 2: effCmd += 1│
        │       air = 'ON' if effCmd ≥ 1 else 'OFF'         │
        │       仅当 state.air 变化才下发                     │
        ├───────────────────────────────────────────────────┤
        │ 水泵（滞回）：                                     │
        │   water < waterlevel_down:                        │
        │       rainComing → 'hold'（控水等雨，不下发）       │
        │       否则       → 'on' + command 'ON'            │
        │   water > waterlevel_up  → 'off' + command 'OFF'  │
        │   区间内                 → 'ok'  无指令            │
        └───────────────────────────────────────────────────┘
                            ▼
                   send_property_command(uid, {...})
```

**默认关闭**：服务端自动调控由 `auto_control` 表 `enabled` 控制，默认 `0`（关闭），须经 `POST /api/auto_control {'enabled': true}` 显式开启；最小动作间隔 `AUTO_MIN_INTERVAL_SECONDS = 60`。

---

## 七、运行约束与假设

### 7.1 单进程多线程假设（**重要**）

以下运行态**保存在进程内存**，因此系统**必须在单进程内运行，不可横向扩展为多进程**：

| 状态 | 位置 | 影响 |
| --- | --- | --- |
| 登录失败限流计数 | `auth._login_fail` | 多进程下限流阈值按进程独立计算，实际可尝试次数翻倍 |
| MQTT 客户端表 | `iot.mqtt_clients` | 每个进程各自维护连接，同一设备会收到重复连接 |
| 历史落库队列 | `iot.history_writer` | 各进程独立批量提交，落库顺序不保证 |
| 日志落库队列 | `logbook._writer` | 同上 |
| 告警去重冷却 | `alert_center._deduper` | 多进程下 60 秒冷却失效，告警可能重复推送 |
| 预案最新缓存 | `planner._latest` | 各进程视图不一致 |
| 泵状态节流 | `metrics._last` | 时长统计会重复累加 |

**当前部署形态**：`server.py` 使用 waitress（**单进程多线程**），`app.py` 使用 Werkzeug 开发服务器，均为单进程，故上述内存态是自洽的。

**若将来要扩为多进程**：须把限流计数、去重冷却、MQTT 客户端表迁移到外部共享存储（Redis 等），并保证同一 `uid` 的 MQTT 连接只落在一个进程上（按 `uid` 一致性哈希分片）。

### 7.2 线程模型

| 线程 | 启动位置 | 周期 | 职责 |
| --- | --- | --- | --- |
| MQTT 回调线程 | paho-mqtt `loop_start()` | 事件驱动 | `on_mqtt_message` → `handle_mqtt_message`（**必须非阻塞**） |
| 历史落库线程 | `iot.start_history_writer()` | 1.0s 或 200 条 | 批量 `insert_history_rows` |
| 日志落库线程 | `logbook._writer` | 1.0s 或 20 条 | 批量写 `logs` |
| 设备离线巡检线程 | `realtime.start_device_watcher()` | 5.0s | 心跳超时判定 + 推 `device_status` |
| 告警推送线程 | `alert_center._PUSH_THREADS` | 按需 | webhook 重试（0.0/0.5/1.0s） |

**入口约束**：`start_history_writer()` 与 `start_device_watcher()` **只在进程入口调用一次**，不得放进 `create_app()`，否则每个测试用例都会多起一个线程。

### 7.3 SQLite 并发

- `get_db()` 固定 `timeout=10`、`PRAGMA journal_mode=WAL`、`PRAGMA busy_timeout=10000`
- 所有连接一律 `with closing(get_db()) as conn:` 关闭，禁止泄漏
- WAL 模式下读不阻塞写，但仍**只支持单写者**；高频写必须走批量队列（见 5.2）

### 7.4 安全

- `FARM_SECRET_KEY` 缺失时回退 `FALLBACK_SECRET_KEY`，且 `FARM_DEBUG=0` 时打印显著警告（**不改变启动行为**）
- `FARM_DEBUG` 默认 `0`（生产安全）；本地调试须显式 `FARM_DEBUG=1`
- 安全响应头（`after_request`，均 `setdefault` 不覆盖已有值）：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: no-referrer`、CSP
- CSP `script-src` 覆盖 `cdnjs.cloudflare.com` 与 `cdn.jsdelivr.net`，并含 `object-src 'none'`、`base-uri 'self'`
- 密码：兼容旧库明文（命中后自动升级为 `generate_password_hash`）；新密码一律哈希存储
- 敏感字段回显一律掩码 `'••••••••'`，明文不出库

---

## 八、已知修复项对照（重构期间一并修掉）

| # | 问题 | 修复位置 |
| --- | --- | --- |
| 1 | DB 连接泄漏 | 全部 DAO 改用 `with closing(get_db()) as conn:` |
| 2 | SQLite 并发 `database is locked` | `db.get_db()` 设 `timeout=10` + WAL + `busy_timeout` |
| 3 | `mqtt_clients` 竞态 | `iot.mqtt_lock`（`RLock`）保护全部读写 |
| 4 | 高频落库阻塞 MQTT 回调 | `iot.HistoryWriter` 队列 + 单后台线程批量落库，满则丢最旧 |
| 5 | `iot_port` 未校验致 `int()` 抛异常 | `config_routes.api_save_config` 校验 1~65535，非法保留旧值 |
| 6 | 掩码字段 `None` 未回退旧值 | `config_routes` 掩码与 `None` 均保留旧值 |
| 7 | 阈值 `int()` 抛 500 | `config_routes` 校验 + clamp（湿度 0~100、水位 0~300） |
| 8 | `history` limit 无上限 | `data_routes._parse_limit` clamp 1~5000，非法回退默认 |
| 9 | `geo_cache` 每次请求建表 | 移到 `db.init_geo_cache()`，启动时执行一次 |
| 10 | 兜底密钥无提示 | `qinghe.__init__._warn_default_secret()` |
| 11 | `FARM_DEBUG` 默认 1 | `config.is_debug()` 默认 `'0'`；`run.bat` 显式 `set FARM_DEBUG=1` |
| 12 | CSP 缺 `object-src`/`base-uri` | `config.CSP_POLICY` 已补 |
| 13 | `PROP_MAP` 三处重复定义 | 唯一来源收敛到 `iot.PROP_MAP`，`realtime` 与 `app_routes` 改为引用 |
| 14 | 路由层调用 auth 下划线私有函数 | 新增 `login_throttle` / `record_login_failure` / `clear_login_failures` 公开入口 |
| 15 | 告警类型码靠中文文案反推 | `evaluate_alerts` 每项补稳定 `code`，文案映射降级为兼容回退 |
| 16 | `/api/forecast` 失败仍返回 200 | 失败统一 502，body 不变 |
| 17 | `metrics._ensure_schema` 切库漏建表 | 建表标记按数据库路径判定 |
