"""青禾智灌 —— 全局配置与常量。

集中存放：环境变量读取、数据库路径、安全响应头、登录限流参数、
传感器量程标定、RORI 融合权重、降雨前馈动态阈值模型参数。
本模块**不得**导入其他 qinghe 子模块，以免形成循环依赖。
"""

import os
import secrets
import threading

# ============================================================
# 一、应用基础配置
# ============================================================

APP_NAME = '青禾智灌智慧灌溉管理平台'

#: 数据库文件路径，可用 FARM_DB_PATH 覆盖（测试用临时文件）
DB_PATH = os.environ.get('FARM_DB_PATH', 'qinghe.db')

#: 会话签名密钥哨兵值。**仅用于判断「是否显式配置了 FARM_SECRET_KEY」，绝不作为签名密钥使用。**
#: 未配置时由 `get_secret_key()` 生成本进程随机密钥（见该函数 docstring）。
FALLBACK_SECRET_KEY = 'smart_irrigation_secret_2026'

#: 默认监听端口（Werkzeug 调试服务器）
DEFAULT_PORT = 5000

#: SQLite 连接超时（秒）。多线程写 sensor_history 时避免立刻 database is locked
DB_TIMEOUT = 10

#: 启动时清理超过该天数的历史数据
HISTORY_KEEP_DAYS = 7

#: 历史查询 limit 的默认值与上下限（clamp）
HISTORY_DEFAULT_LIMIT = 1000
HISTORY_MIN_LIMIT = 1
HISTORY_MAX_LIMIT = 5000

# ============================================================
# 二、安全响应头
# ============================================================

#: 基础 CSP：脚本与样式全部本地化（socket.io / Chart.js / Leaflet 在 static/vendor），
#: 因此 script-src / style-src 只放同源，不再放行外网 CDN；地图瓦片是 <img>，img-src 放行 https。
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self' https:; "
    "font-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self';"
)

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'SAMEORIGIN',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': CSP_POLICY,
}

# ============================================================
# 三、登录限流（按 用户名+IP 维度）
# ============================================================

LOGIN_MAX_FAIL = 5
LOGIN_LOCK_SECONDS = 600
REGISTER_MAX_ATTEMPTS = 10          #: 同一来源 IP 在限流窗口内最多注册次数
MAX_CONTENT_LENGTH = 512 * 1024     #: 请求体上限（字节），超限返回 413

# ============================================================
# 四、配置项校验
# ============================================================

#: 敏感字段在 GET /api/get_config 中回显的掩码占位符
MASK = '••••••••'

#: 告警文案长度上限（/api/notify_alert 截断用）
ALERT_CONTENT_MAX_LEN = 500
ALERT_LEVEL_MAX_LEN = 20

#: iot_port 合法范围
IOT_PORT_MIN = 1
IOT_PORT_MAX = 65535
IOT_PORT_DEFAULT = 1883

#: 阈值合法范围
HUMI_MIN, HUMI_MAX = 0, 100
WATERLEVEL_MIN, WATERLEVEL_MAX = 0, 300
THRESH_DEFAULTS = {
    'humi_down': 40,
    'humi_up': 80,
    'waterlevel_down': 30,
    'waterlevel_up': 150,
    'manual_mode': 0,
}

#: 用户/密码长度约束
USERNAME_MIN_LEN, USERNAME_MAX_LEN = 3, 20
PASSWORD_MIN_LEN, PASSWORD_MAX_LEN = 6, 64

#: MQTT / 外部接口默认值
DEFAULT_M2M_TOPIC = '/esp32e/data'
DEFAULT_CMD_TOPIC = '/esp32e/cmd'
DEFAULT_WEATHER_DOMAIN = 'm767cfpjh7.re.qweatherapi.com'
DEFAULT_AI_DOMAIN = 'https://api.deepseek.com'
DEFAULT_AI_MODEL = 'deepseek-chat'
AI_MSG_MAX_LEN = 2000               #: 单次提问最大字符数（超长直接 400）

#: 外部网络调用超时（秒）
TIMEOUT_PHOTON = 6
TIMEOUT_WEBHOOK = 3
TIMEOUT_WEATHER = 8
TIMEOUT_AI = 20

#: 多农场（地块）约束
FARM_NAME_MIN_LEN = 1
FARM_NAME_MAX_LEN = 20
FARM_MAX_COUNT = 12                #: 单账号地块上限
FARM_AREA_MAX_M2 = 1000000.0       #: 单块地上限 100 公顷
FARM_POLYGON_MAX_POINTS = 200      #: 圈地边界点数上限
FARM_POLYGON_MAX_LEN = 20000       #: 边界 JSON 字符串长度上限
FARM_LAT_RANGE = (-90.0, 90.0)
FARM_LON_RANGE = (-180.0, 180.0)

#: 设备模拟器开关（无实物主板时演示用，默认关闭）：FARM_DEV_SIM=1 才开放
DEV_SIM_ENV = 'FARM_DEV_SIM'

# ============================================================
# 五、传感器量程标定（与固件 esp.txt / 前端 index.html 保持一致）
# ============================================================

ADC_MAX = 4095.0            #: 12 位 ADC 满量程
WATER_FS_MM = 300.0         #: 探针式水位满量程（mm）
DO_MIN_MGL, DO_MAX_MGL = 0.0, 20.0      #: 根区溶解氧量程（mg/L）
EH_MIN_MV, EH_MAX_MV = -150.0, 300.0    #: 根区氧化还原电位量程（mV）

# ============================================================
# 六、RORI 根区缺氧风险指数模型（说明书 3.1~3.2）
# ============================================================

W_EH = 0.35             #: 氧化还原电位风险权重
W_DO = 0.35             #: 溶解氧风险权重
W_WATER_SOIL = 0.30     #: 水位/土壤湿润度取大风险权重
GAMMA = 0.5             #: 水位×土壤耦合惩罚系数

EH_SAFE_MV = 300.0      #: SEh 公式中的 Ehmax
EH_SPAN_MV = 450.0      #: SEh 公式分母 (Ehmax - Ehmin) = 300 - (-150)
DO_SAFE_MGL = 8.0       #: SDO 公式中的 DOmax，超过该值视为无缺氧风险
WATER_DEADBAND_MM = 5.0     #: 水位风险死区
WATER_RISK_SPAN_MM = 100.0  #: 水位风险归一化跨度

RORI_HEAVY = 70         #: RORI≥70 重度厌氧
RORI_MODERATE = 40      #: 40≤RORI<70 中度缺氧

# ============================================================
# 七、降雨前馈动态阈值模型（说明书 3.3）
# ============================================================

RAIN_WEIGHTS = [1.0, 0.9, 0.7, 0.5, 0.4, 0.3]   #: 6 日降雨时间衰减权重 ω_t
H_ROOT = 200.0                                  #: 核心活动根系层厚度（mm）
ALPHA_LOW = 0.95        #: P6d ≤ 10mm 时的降雨有效利用系数
ALPHA_MID = 0.75        #: 10 < P6d ≤ 50mm
ALPHA_HIGH = 0.45       #: P6d > 50mm
ALPHA_LOW_MAX = 10.0
ALPHA_MID_MAX = 50.0
EFF_LOWER_FLOOR = 45.0  #: 前馈控水等雨的湿度下限保底（防枯萎）
EFF_UPPER_RAIN = 15.0   #: P6d≥15mm 触发蓄雨型控灌
EFF_UPPER_BONUS = 15.0  #: 蓄雨上限放宽幅度（%）
EFF_UPPER_CAP = 100.0   #: 湿度上限封顶

# ============================================================
# 八、告警去重 / 冷却
# ============================================================

ALERT_COOLDOWN_SECONDS = 60     #: 同一告警内容的最小推送间隔（秒）
ALERT_KEY_PREFIX = '【青禾智灌系统】'

# ============================================================
# 九、MQTT 批量落库队列
# ============================================================

HISTORY_QUEUE_MAX = 2000        #: 队列上限，满则丢弃最旧数据（不阻塞 MQTT 回调线程）
HISTORY_FLUSH_INTERVAL = 1.0    #: 后台线程 flush 周期（秒）
HISTORY_FLUSH_BATCH = 200       #: 单次 flush 最多写入条数


def is_debug() -> bool:
    """是否处于调试模式。默认 0（生产安全），本地调试需显式 FARM_DEBUG=1。"""
    return os.environ.get('FARM_DEBUG', '0') == '1'


def trust_proxy() -> bool:
    """是否信任反向代理传来的 `X-Forwarded-For`。

    **默认关闭**。直连部署时客户端可随意伪造 XFF 头，若据此做登录限流
    等于把限流开关交给攻击者（换头即重置计数，可无限爆破）。仅当服务确实
    部署在 nginx / waitress 等反向代理之后，才设 `FARM_TRUST_PROXY=1`。
    """
    return os.environ.get('FARM_TRUST_PROXY', '0') == '1'


def dev_sim_enabled() -> bool:
    """设备模拟器是否开放（`FARM_DEV_SIM=1`）。

    用于没有实物主板的演示/答辩场景：接口可注入一段带时间戳的遥测数据，
    走与 MQTT 上报完全相同的处理链路。生产环境不要开。
    """
    return os.environ.get(DEV_SIM_ENV, '0') == '1'


#: 未配置 FARM_SECRET_KEY 时生成的进程级随机密钥（首次调用时惰性创建，进程内复用）。
#: 每次启动都不同 —— 攻击者无法预知，因此无法伪造 JWT / 会话签名。
_RUNTIME_SECRET_KEY = None
_SECRET_LOCK = threading.Lock()


def secret_key_is_configured() -> bool:
    """是否显式配置了 FARM_SECRET_KEY（用于告警判定）。"""
    return bool(os.environ.get('FARM_SECRET_KEY'))


def get_secret_key() -> str:
    """取会话 / JWT 签名密钥。

    优先读环境变量 `FARM_SECRET_KEY`；**未配置时生成进程级随机密钥**
    （`secrets.token_urlsafe(48)`，约 64 字符），而不是回落到硬编码常量。

    安全考量：旧实现回落到公开的硬编码常量，任何人可用它自签 JWT 冒充任意
    `user_id` 调用 `/api/app_send_command` 真实下发设备指令（fail-open）。
    改为随机密钥后攻击者无法预知，属 fail-closed；代价是未配置时**重启后
    既有登录态失效**，生产应显式配置 `FARM_SECRET_KEY`（见 `.env.example`）。
    """
    configured = os.environ.get('FARM_SECRET_KEY')
    if configured:
        return configured
    global _RUNTIME_SECRET_KEY
    with _SECRET_LOCK:
        if _RUNTIME_SECRET_KEY is None:
            _RUNTIME_SECRET_KEY = secrets.token_urlsafe(48)
        return _RUNTIME_SECRET_KEY


def reset_runtime_secret_key() -> None:
    """清空进程级随机密钥（仅供测试模拟「进程重启」）。"""
    global _RUNTIME_SECRET_KEY
    with _SECRET_LOCK:
        _RUNTIME_SECRET_KEY = None


def get_db_path() -> str:
    """取数据库路径：优先环境变量 FARM_DB_PATH（运行时可覆盖，便于测试）。"""
    return os.environ.get('FARM_DB_PATH', DB_PATH)
