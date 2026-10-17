"""青禾智灌 —— 全局配置与常量。

集中存放：环境变量读取、数据库路径、安全响应头、登录限流参数、
传感器量程标定、RORI 融合权重、降雨前馈动态阈值模型参数。
本模块**不得**导入其他 qinghe 子模块，以免形成循环依赖。
"""

import os

# ============================================================
# 一、应用基础配置
# ============================================================

APP_NAME = '青禾智灌智慧灌溉管理平台'

#: 数据库文件路径，可用 FARM_DB_PATH 覆盖（测试用临时文件）
DB_PATH = os.environ.get('FARM_DB_PATH', 'qinghe.db')

#: 会话签名密钥。优先读 FARM_SECRET_KEY；未配置时使用兜底值，
#: 兜底值仅为「本地能直接启动」服务，生产必须显式配置。
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

#: 基础 CSP：允许同源脚本与内联（项目使用了内联 script/style），
#: 图表库走 cdnjs / jsdelivr 两个 CDN。
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
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

# ============================================================
# 四、配置项校验
# ============================================================

#: 敏感字段在 GET /api/get_config 中回显的掩码占位符
MASK = '••••••••'

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

#: 外部网络调用超时（秒）
TIMEOUT_PHOTON = 6
TIMEOUT_WEBHOOK = 6
TIMEOUT_WEATHER = 8
TIMEOUT_AI = 20

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


def get_secret_key() -> str:
    """取会话签名密钥：优先环境变量 FARM_SECRET_KEY，未设置时用兜底值。"""
    return os.environ.get('FARM_SECRET_KEY') or FALLBACK_SECRET_KEY


def get_db_path() -> str:
    """取数据库路径：优先环境变量 FARM_DB_PATH（运行时可覆盖，便于测试）。"""
    return os.environ.get('FARM_DB_PATH', DB_PATH)
