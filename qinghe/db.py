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
                soil_adc INTEGER,
                do_mgl REAL,
                eh_mv REAL,
                farm_id INTEGER DEFAULT 0
            )''')
            # 老库没有 do_mgl / eh_mv / farm_id，按需补列（幂等）
            cursor.execute('PRAGMA table_info(sensor_history)')
            history_cols = [r[1] for r in cursor.fetchall()]
            farm_id_added = False
            for col, ddl in _HISTORY_MIGRATIONS:
                if col not in history_cols:
                    cursor.execute(ddl)
                    if col == 'farm_id':
                        farm_id_added = True
            if farm_id_added:
                # 升级旧库：历史行无法追溯真实地块，统一归到当前生效地块，
                # 避免旧数据在切换地块后从图表里消失；无地块账号保持 0（账号级）。
                cursor.execute(
                    'UPDATE sensor_history SET farm_id = COALESCE('
                    '(SELECT c.active_farm_id FROM configs c'
                    ' WHERE c.user_id = sensor_history.user_id), 0)'
                    ' WHERE farm_id = 0'
                )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_history_user_ts ON sensor_history(user_id, ts)'
            )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_history_user_farm_ts'
                ' ON sensor_history(user_id, farm_id, ts)'
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
            # 多农场（地块）表：一个账号可管理多块田，configs 只镜像当前生效地块
            cursor.execute('''CREATE TABLE IF NOT EXISTS farms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                lat REAL,
                lon REAL,
                area_m2 REAL DEFAULT 0,
                polygon TEXT DEFAULT '',
                created_ts INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )''')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_farms_user ON farms(user_id, id)'
            )
            # farms 表在旧库可能不存在（上面已补建），configs 的 active_farm_id 交给迁移列表
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
    ('active_farm_id',
     'ALTER TABLE configs ADD COLUMN active_farm_id INTEGER DEFAULT 0'),
]

#: sensor_history 表的增量迁移列（列名, DDL）：溶解氧、氧化还原电位与所属地块
_HISTORY_MIGRATIONS = [
    ('do_mgl', 'ALTER TABLE sensor_history ADD COLUMN do_mgl REAL'),
    ('eh_mv', 'ALTER TABLE sensor_history ADD COLUMN eh_mv REAL'),
    ('farm_id', 'ALTER TABLE sensor_history ADD COLUMN farm_id INTEGER DEFAULT 0'),
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
        except sqlite3.IntegrityError:
            return None
    # 新账号自动建一块默认地，设置页/地图选点都有落点可用
    try:
        ensure_default_farm(uid)
    except sqlite3.Error:
        pass
    return uid


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

def insert_history_rows(rows, farm_id: int = 0) -> None:
    """批量写入历史采样。

    参数:
        rows: 可迭代的 `(user_id, ts, water_adc, soil_adc[, do_mgl, eh_mv[, farm_id]])`
              元组序列。4 / 5 / 6 元组会按位补 `None`，末位地块缺省用 `farm_id`
              （默认 0 表示账号级/未归属）。
        farm_id: 批量统一地块号；行内已带第 7 位时以行内为准。
    """
    default_farm = int(farm_id or 0)
    normalized = []
    for row in rows:
        item = tuple(row)
        if len(item) == 4:
            item = item + (None, None)
        elif len(item) == 5:
            item = item + (None,)
        if len(item) == 6:
            item = item + (default_farm,)
        normalized.append(item[:7])
    if not normalized:
        return
    with closing(get_db()) as conn:
        conn.executemany(
            'INSERT INTO sensor_history'
            ' (user_id, ts, water_adc, soil_adc, do_mgl, eh_mv, farm_id)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            normalized,
        )
        conn.commit()


def query_history(uid: int, limit: int, farm_id: int = None):
    """按时间倒序取最近 limit 条历史，返回 sqlite3.Row 列表（未 reverse）。

    `farm_id` 给出时只返回该地块的历史；`farm_id=0` 的行是未归属/账号级旧数据，
    对所有地块都可见，避免升级或单地块账号丢图。
    """
    sql = ('SELECT ts, water_adc, soil_adc, do_mgl, eh_mv FROM sensor_history'
           ' WHERE user_id = ?')
    params = [uid]
    if farm_id:
        sql += ' AND (farm_id = ? OR farm_id = 0)'
        params.append(int(farm_id))
    sql += ' ORDER BY ts DESC LIMIT ?'
    params.append(limit)
    with closing(get_db()) as conn:
        cur = conn.execute(sql, params)
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


# ============================================================
# DAO：farms（多农场 / 地块）
# ============================================================

#: 新账号自动创建的首个地块名
DEFAULT_FARM_NAME = '默认地块'

_FARM_FIELDS = ('id', 'user_id', 'name', 'lat', 'lon', 'area_m2', 'polygon', 'created_ts')


def _farm_dict(row) -> dict:
    """把 farms 行转为可 JSON 序列化的 dict。"""
    if row is None:
        return None
    return {
        'id': int(row['id']),
        'name': row['name'],
        'lat': None if row['lat'] is None else float(row['lat']),
        'lon': None if row['lon'] is None else float(row['lon']),
        'area_m2': float(row['area_m2'] or 0.0),
        'polygon': row['polygon'] or '',
        'created_ts': int(row['created_ts'] or 0),
    }


def count_farms(uid: int) -> int:
    """统计该账号的地块数量。"""
    with closing(get_db()) as conn:
        cur = conn.execute('SELECT COUNT(*) AS n FROM farms WHERE user_id=?', (uid,))
        return int(cur.fetchone()['n'])


def list_farms(uid: int) -> list:
    """按创建顺序列出该账号所有地块（dict 列表）。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT * FROM farms WHERE user_id=? ORDER BY id ASC', (uid,)
        )
        return [_farm_dict(row) for row in cur.fetchall()]


def get_farm(uid: int, farm_id: int) -> dict:
    """按 id 取地块（仅限本人），不存在返回 None。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT * FROM farms WHERE user_id=? AND id=?', (uid, farm_id)
        )
        return _farm_dict(cur.fetchone())


def create_farm(uid: int, name: str, lat=None, lon=None,
                area_m2: float = 0.0, polygon: str = '') -> int:
    """新建地块，返回新 id。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'INSERT INTO farms (user_id, name, lat, lon, area_m2, polygon, created_ts)'
            ' VALUES (?,?,?,?,?,?,?)',
            (uid, name, lat, lon, area_m2, polygon, int(time.time())),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_farm(uid: int, farm_id: int, name: str, lat=None, lon=None,
                area_m2: float = 0.0, polygon: str = '') -> bool:
    """更新地块信息，返回是否命中。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'UPDATE farms SET name=?, lat=?, lon=?, area_m2=?, polygon=?'
            ' WHERE user_id=? AND id=?',
            (name, lat, lon, area_m2, polygon, uid, farm_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_farm(uid: int, farm_id: int) -> bool:
    """删除地块（至少保留一块的约束由调用方保证），返回是否命中。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'DELETE FROM farms WHERE user_id=? AND id=?', (uid, farm_id)
        )
        conn.commit()
        return cur.rowcount > 0


def get_active_farm_id(uid: int) -> int:
    """读取当前生效地块 id，未设置返回 0。"""
    with closing(get_db()) as conn:
        cur = conn.execute(
            'SELECT active_farm_id FROM configs WHERE user_id=?', (uid,)
        )
        row = cur.fetchone()
        if row is None or row['active_farm_id'] is None:
            return 0
        return int(row['active_farm_id'])


def _mirror_to_config(conn, uid: int, farm: dict) -> None:
    """把地块的名称/经纬度镜像进 configs（天气、看板、逆地理都读这几个字段）。"""
    conn.execute(
        'UPDATE configs SET farm_name=?, farm_lat=?, farm_lng=?, active_farm_id=?'
        ' WHERE user_id=?',
        (
            farm.get('name') or '',
            '' if farm.get('lat') is None else str(farm['lat']),
            '' if farm.get('lon') is None else str(farm['lon']),
            int(farm.get('id') or 0),
            uid,
        ),
    )


def set_active_farm(uid: int, farm_id: int) -> bool:
    """切换当前地块：写 configs.active_farm_id 并镜像名称与坐标。"""
    farm = get_farm(uid, farm_id)
    if farm is None:
        return False
    with closing(get_db()) as conn:
        _mirror_to_config(conn, uid, farm)
        conn.commit()
    return True


def ensure_default_farm(uid: int) -> dict:
    """保证账号至少有一块地；返回当前生效地块 dict（必要时新建并激活）。"""
    farms = list_farms(uid)
    if not farms:
        cfg = load_config(uid)
        name = (cfg['farm_name'] if cfg and cfg['farm_name'] else '') or DEFAULT_FARM_NAME
        lng = cfg['farm_lng'] if cfg else ''
        lat = cfg['farm_lat'] if cfg else ''
        farm_id = create_farm(
            uid,
            name or DEFAULT_FARM_NAME,
            float(lat) if lat else None,
            float(lng) if lng else None,
        )
        farms = list_farms(uid)
        set_active_farm(uid, farm_id)
        return get_farm(uid, farm_id)
    active_id = get_active_farm_id(uid)
    current = get_farm(uid, active_id) if active_id else None
    if current is None:
        # active_farm_id 失效（被删/旧库）：回落到第一块地
        set_active_farm(uid, farms[0]['id'])
        return get_farm(uid, farms[0]['id'])
    return current


def save_active_farm_meta(uid: int, name=None, lat=None, lon=None,
                          area_m2=None, polygon=None) -> bool:
    """保存设置页里对「当前地块」的修改（名称/坐标/面积/边界）。

    **参数为 None 表示「本次不改动该字段」**，保持地块记录原值。
    因此本函数无法用 None 表达「把坐标清空」——调用方若需要清空坐标，
    应显式传入空字符串 `''`（本函数会把它转成 `None` 落库）。
    """
    farm = ensure_default_farm(uid)
    if farm is None:
        return False

    def _coord(value, current):
        """坐标取值：None=不改动，''=清空（落 NULL），其余转 float。"""
        if value is None:
            return current
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return current

    return update_farm(
        uid,
        farm['id'],
        name if name is not None else farm['name'],
        _coord(lat, farm['lat']),
        _coord(lon, farm['lon']),
        area_m2 if area_m2 is not None else farm['area_m2'],
        polygon if polygon is not None else farm['polygon'],
    )
