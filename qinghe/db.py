"""青禾智灌 —— 数据访问层。

职责：SQLite 连接管理（WAL + timeout）、建表与迁移、各表 DAO、反查地名缓存。
连接一律通过 `closing()` 或 `with closing(get_db()) as conn:` 关闭，禁止泄漏。
表名与字段名与旧版 app.py 逐字一致，只允许新增列/表，不允许改名。
"""

import sqlite3
import threading
import time
from contextlib import closing

from qinghe import config

#: 建表语句在进程内只跑一次（多线程并发首次请求时避免重复迁移）
_init_lock = threading.Lock()
_initialized = False


def get_db() -> sqlite3.Connection:
    """新建一个 SQLite 连接（Row 工厂 + timeout，启用 WAL）。

    调用方必须负责关闭：`with closing(get_db()) as conn:`。
    """
    conn = sqlite3.connect(config.get_db_path(), timeout=config.DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    # WAL 提升并发读性能，缓解多线程写 sensor_history 时的 database is locked
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=%d' % int(config.DB_TIMEOUT * 1000))
    except sqlite3.Error:
        pass
    return conn


def init_db(force: bool = False) -> None:
    """建表 + 增量迁移 + 清理过期历史。幂等，进程内只执行一次。

    参数:
        force: 为 True 时忽略进程内一次性标记，强制执行（测试用）。
    """
    global _initialized
    with _init_lock:
        if _initialized and not force:
            return
        with closing(get_db()) as conn:
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
            for col, ddl in _CONFIG_MIGRATIONS:
                if col not in cols:
                    cursor.execute(ddl)
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
            # 只保留最近 N 天的数据
            cutoff = int(time.time() * 1000) - config.HISTORY_KEEP_DAYS * 24 * 3600 * 1000
            cursor.execute('DELETE FROM sensor_history WHERE ts < ?', (cutoff,))
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
        _initialized = True


#: configs 表的增量迁移列（列名, DDL），保持与旧库兼容
_CONFIG_MIGRATIONS = [
    ('farm_lng', "ALTER TABLE configs ADD COLUMN farm_lng TEXT DEFAULT ''"),
    ('farm_lat', "ALTER TABLE configs ADD COLUMN farm_lat TEXT DEFAULT ''"),
    ('iot_target_device_id',
     "ALTER TABLE configs ADD COLUMN iot_target_device_id TEXT DEFAULT ''"),
    ('iot_m2m_topic',
     "ALTER TABLE configs ADD COLUMN iot_m2m_topic TEXT DEFAULT '/esp32e/data'"),
    ('iot_cmd_topic',
     "ALTER TABLE configs ADD COLUMN iot_cmd_topic TEXT DEFAULT '/esp32e/cmd'"),
    ('farm_name', "ALTER TABLE configs ADD COLUMN farm_name TEXT DEFAULT ''"),
    ('webhook_url', "ALTER TABLE configs ADD COLUMN webhook_url TEXT DEFAULT ''"),
]


def init_geo_cache() -> None:
    """反查地名缓存表：同一坐标只调一次外部接口，之后全走缓存。启动时调用。"""
    with closing(get_db()) as conn:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS geo_cache (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ts INTEGER NOT NULL
            )'''
        )
        conn.commit()


# ============================================================
# DAO：users
# ============================================================

def create_user(username: str, password_hash: str):
    """新建用户并初始化其配置行。

    返回: 新用户 id；用户名已存在时返回 None。
    """
    with closing(get_db()) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO users (username, password) VALUES (?, ?)',
                (username, password_hash),
            )
            uid = cursor.lastrowid
            cursor.execute('INSERT INTO configs (user_id) VALUES (?)', (uid,))
            conn.commit()
            return uid
        except sqlite3.IntegrityError:
            return None


def get_user_by_username(username: str):
    """按用户名取用户行（含 password 字段），不存在返回 None。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT id, username, password FROM users WHERE username=?', (username,)
        )
        return cur.fetchone()


def get_user_by_id(uid: int):
    """按用户 id 取用户行，不存在返回 None。"""
    with closing(get_db()) as conn:
        cur = conn.execute('SELECT id, username, password FROM users WHERE id=?', (uid,))
        return cur.fetchone()


def update_password(uid: int, password_hash: str) -> None:
    """更新指定用户的密码哈希。"""
    with closing(get_db()) as conn:
        conn.execute('UPDATE users SET password=? WHERE id=?', (password_hash, uid))
        conn.commit()


# ============================================================
# DAO：configs
# ============================================================

def load_config(uid: int):
    """读取用户配置行，不存在返回 None。"""
    with closing(get_db()) as conn:
        cur = conn.execute('SELECT * FROM configs WHERE user_id = ?', (uid,))
        return cur.fetchone()


def load_ai_config(uid: int):
    """只取 AI 代理需要的两列（ai_domain / ai_key）。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT ai_domain, ai_key FROM configs WHERE user_id = ?', (uid,)
        )
        return cur.fetchone()


def load_weather_config(uid: int):
    """只取天气代理需要的四列（weather_domain / weather_key / farm_lng / farm_lat）。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT weather_domain, weather_key, farm_lng, farm_lat'
            ' FROM configs WHERE user_id = ?',
            (uid,),
        )
        return cur.fetchone()


#: /api/save_config 可更新的列，顺序即 SQL 中的赋值顺序
CONFIG_COLUMNS = (
    'farm_name', 'farm_lng', 'farm_lat',
    'pump_port', 'air_pump_port', 'water_sensor_port', 'soil_sensor_port',
    'weather_domain', 'weather_key', 'ai_domain', 'ai_key',
    'iot_host', 'iot_port', 'iot_client_id', 'iot_user', 'iot_pass', 'iot_device_id',
    'iot_target_device_id', 'iot_m2m_topic', 'iot_cmd_topic', 'webhook_url',
)


def save_config(uid: int, values: dict) -> None:
    """按 CONFIG_COLUMNS 全量更新用户配置（values 中缺失的列写 NULL）。"""
    assignments = ', '.join('%s=?' % col for col in CONFIG_COLUMNS)
    params = tuple(values.get(col) for col in CONFIG_COLUMNS) + (uid,)
    with closing(get_db()) as conn:
        conn.execute('UPDATE configs SET %s WHERE user_id=?' % assignments, params)
        conn.commit()


# ============================================================
# DAO：sensor_history
# ============================================================

def insert_history_rows(rows) -> None:
    """批量写入历史采样。

    参数:
        rows: 可迭代的 (user_id, ts, water_adc, soil_adc) 元组序列。
    """
    rows = list(rows)
    if not rows:
        return
    with closing(get_db()) as conn:
        conn.executemany(
            'INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc)'
            ' VALUES (?, ?, ?, ?)',
            rows,
        )
        conn.commit()


def query_history(uid: int, limit: int):
    """按时间倒序取最近 limit 条历史，返回 sqlite3.Row 列表（未 reverse）。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT ts, water_adc, soil_adc FROM sensor_history'
            ' WHERE user_id = ? ORDER BY ts DESC LIMIT ?',
            (uid, limit),
        )
        return cur.fetchall()


# ============================================================
# DAO：thresh_settings
# ============================================================

def load_thresholds(uid: int):
    """读取用户阈值设定行，不存在返回 None。"""
    with closing(get_db()) as conn:
        cur = conn.execute('SELECT * FROM thresh_settings WHERE user_id = ?', (uid,))
        return cur.fetchone()


def save_thresholds(uid: int, humi_down: int, humi_up: int,
                    wl_down: int, wl_up: int, manual: int) -> None:
    """UPSERT 用户阈值设定与手动/自动模式。"""
    with closing(get_db()) as conn:
        conn.execute(
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


# ============================================================
# DAO：geo_cache
# ============================================================

def get_geo_cache(key: str):
    """取缓存地名，未命中返回 None。表不存在（未初始化）时也返回 None。"""
    try:
        with closing(get_db()) as conn:
            cur = conn.execute('SELECT name FROM geo_cache WHERE key=?', (key,))
            row = cur.fetchone()
            return row['name'] if row else None
    except sqlite3.Error:
        return None


def set_geo_cache(key: str, name: str) -> None:
    """写入/覆盖缓存地名。"""
    with closing(get_db()) as conn:
        conn.execute(
            'INSERT OR REPLACE INTO geo_cache (key, name, ts) VALUES (?,?,?)',
            (key, name, int(time.time())),
        )
        conn.commit()
