"""测试辅助函数（不依赖 pytest fixture，可在任意测试模块 import）。"""

from contextlib import closing

from qinghe import auth
from qinghe.db import get_db


def make_user(username, password):
    """直接建用户（不经过 HTTP），返回 uid；用户名已存在返回 None。"""
    return auth.db.create_user(username, auth.hash_password(password))


def login_session(client, username, password):
    """走 HTTP 登录，建立 session，返回响应对象。"""
    return client.post('/api/login', json={'username': username, 'password': password})


def fetch_one(sql, params=()):
    """执行单行查询并返回 sqlite3.Row（或 None）。"""
    with closing(get_db()) as conn:
        return conn.execute(sql, params).fetchone()


def fetch_all(sql, params=()):
    """执行查询并返回全部行。"""
    with closing(get_db()) as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql, params=()):
    """执行写语句并提交。"""
    with closing(get_db()) as conn:
        conn.execute(sql, params)
        conn.commit()


def set_config(uid, **columns):
    """直接更新 configs 表的若干列（测试准备数据用）。"""
    if not columns:
        return
    assignments = ', '.join('%s=?' % col for col in columns)
    execute('UPDATE configs SET %s WHERE user_id=?' % assignments,
            tuple(columns.values()) + (uid,))


def user_id_of(username):
    """按用户名取 uid。"""
    row = fetch_one('SELECT id FROM users WHERE username=?', (username,))
    return row['id'] if row else None
