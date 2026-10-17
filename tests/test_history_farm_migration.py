"""sensor_history.farm_id 增量迁移测试。

背景：历史表原本只有 user_id，没有地块归属；多地块上线后新增 farm_id，
并给旧库里的历史行回填账号当前生效地块，避免升级后图表凭空少一段。
"""

import sqlite3
import time

from qinghe import db


def _make_legacy_db(path, active_farm_id):
    """造一个「没有 farm_id 列」的旧库，含 1 个用户 + 1 行历史。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        '''CREATE TABLE users (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               username TEXT UNIQUE NOT NULL,
               password TEXT NOT NULL);
           CREATE TABLE configs (
               user_id INTEGER PRIMARY KEY,
               farm_name TEXT DEFAULT '',
               active_farm_id INTEGER DEFAULT 0);
           CREATE TABLE sensor_history (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL,
               ts INTEGER NOT NULL,
               water_adc INTEGER,
               soil_adc INTEGER);'''
    )
    conn.execute("INSERT INTO users (id, username, password) VALUES (1, 'olduser', 'x')")
    conn.execute(
        'INSERT INTO configs (user_id, farm_name, active_farm_id) VALUES (1, ?, ?)',
        ('老地块', active_farm_id),
    )
    conn.execute(
        'INSERT INTO sensor_history (user_id, ts, water_adc, soil_adc) VALUES (1, ?, 1200, 3000)',
        (int(time.time() * 1000),),
    )
    conn.commit()
    conn.close()


def test_legacy_rows_backfilled_with_active_farm(tmp_path, monkeypatch):
    """旧库升级时，历史行归到当前生效地块，且不会被别的用户/地块看到。"""
    db_path = tmp_path / 'legacy.db'
    _make_legacy_db(str(db_path), active_farm_id=7)
    monkeypatch.setenv('FARM_DB_PATH', str(db_path))

    db.init_db(force=True)

    with db.get_db() as conn:
        cols = [r[1] for r in conn.execute('PRAGMA table_info(sensor_history)').fetchall()]
        assert 'farm_id' in cols
        row = conn.execute('SELECT farm_id, water_adc FROM sensor_history').fetchone()
    assert row['farm_id'] == 7
    assert row['water_adc'] == 1200

    assert len(db.query_history(1, 5, farm_id=7)) == 1
    assert db.query_history(1, 5, farm_id=8) == []


def test_legacy_db_without_farm_keeps_zero(tmp_path, monkeypatch):
    """旧库没有生效地块（active_farm_id=0）时，历史保持账号级 0。"""
    db_path = tmp_path / 'legacy_zero.db'
    _make_legacy_db(str(db_path), active_farm_id=0)
    monkeypatch.setenv('FARM_DB_PATH', str(db_path))

    db.init_db(force=True)

    with db.get_db() as conn:
        row = conn.execute('SELECT farm_id FROM sensor_history').fetchone()
    assert row['farm_id'] == 0
