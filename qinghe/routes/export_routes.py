"""青禾智灌 —— NF6 数据导出（CSV 下载）。

两个接口都要求登录，导出内容为 UTF-8 + BOM（`\\ufeff`）的 CSV，用 Excel 直接双击
打开不乱码。列名固定，源表缺失的列留空，便于下游脚本按固定表头解析。

路由：
- GET /api/export/history.csv  `?limit=` / `?since_ts=`
- GET /api/export/alerts.csv   `?limit=` / `?since_ts=`
"""

import csv
import io
import time
from contextlib import closing
from datetime import datetime

from flask import Blueprint, Response, jsonify, request, session

from qinghe import config, db

bp = Blueprint('export', __name__)

#: UTF-8 BOM，保证 Excel 识别编码
BOM = '\ufeff'

#: 单次导出最大行数
MAX_EXPORT_ROWS = 50000

#: 默认导出行数
DEFAULT_EXPORT_ROWS = config.HISTORY_MAX_LIMIT

#: 历史数据表头（固定列，缺列留空）
HISTORY_HEADER = ['时间', '时间戳', '水位ADC', '土壤ADC', '溶解氧mg/L', '氧化还原电位mV']

#: 告警导出表头
ALERTS_HEADER = ['时间', '时间戳', '级别', '类型', '内容', '已确认']


def _current_uid():
    """取当前登录用户 id；未登录返回 None。"""
    try:
        uid = session.get('user_id')
    except Exception:
        return None
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None


def _unauthorized():
    """统一的未登录响应。"""
    return jsonify({'error': '未登录'}), 401


def _parse_int(value, default, minimum, maximum):
    """把查询参数解析成区间内整数；非法返回 None。"""
    if value is None or value == '':
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def _parse_limit(raw, default: int):
    """解析导出条数：缺省用默认值，超过 `MAX_EXPORT_ROWS` 按上限截断，非法返回 None。"""
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 1:
        return None
    return min(value, MAX_EXPORT_ROWS)


def _fmt_ts(ts) -> str:
    """毫秒时间戳 → 本地时间字符串（秒级，导出可读性优先）。"""
    try:
        return datetime.fromtimestamp(int(ts) / 1000.0).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError, OSError):
        return ''


def _table_columns(conn, table: str) -> set:
    """读取表字段名集合；表不存在返回空集合。"""
    try:
        rows = conn.execute('PRAGMA table_info(%s)' % table).fetchall()
    except Exception:
        return set()
    return {str(row[1]) for row in rows}


def _build_csv(header, rows) -> str:
    """把表头与数据行写成带 BOM 的 CSV 文本。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return BOM + buffer.getvalue()


def _csv_response(text: str, filename: str) -> Response:
    """构造 CSV 下载响应（带 Content-Disposition 文件名）。"""
    response = Response(text, mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=%s' % filename
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('/api/export/history.csv')
def export_history_csv():
    """导出传感器历史为 CSV（按 ts 倒序，缺列留空）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    limit = _parse_limit(request.args.get('limit'), DEFAULT_EXPORT_ROWS)
    if limit is None:
        return jsonify({'error': 'limit 必须是正整数（超过 %d 按上限截断）' % MAX_EXPORT_ROWS}), 400
    since_ts = _parse_int(request.args.get('since_ts'), 0, 0, 2 ** 62)
    if since_ts is None:
        return jsonify({'error': 'since_ts 必须是非负整数'}), 400

    rows = []
    try:
        with closing(db.get_db()) as conn:
            columns = _table_columns(conn, 'sensor_history')
            if columns:
                selected = [name for name in ('ts', 'water_adc', 'soil_adc', 'do_mgl', 'eh_mv')
                            if name in columns]
                where = 'user_id = ? AND ts >= ?'
                params = [int(uid), int(since_ts)]
                if 'farm_id' in columns:
                    # 与 /api/history 一致：只导出当前地块 + 升级前未归属的行
                    where += ' AND (farm_id = 0 OR farm_id = ?)'
                    params.append(int(db.get_active_farm_id(uid)))
                params.append(int(limit))
                sql = 'SELECT %s FROM sensor_history WHERE %s ORDER BY ts DESC LIMIT ?' \
                      % (', '.join(selected), where)
                for row in conn.execute(sql, params).fetchall():
                    record = dict(zip(selected, row))
                    rows.append([
                        _fmt_ts(record.get('ts')),
                        record.get('ts', ''),
                        record.get('water_adc', ''),
                        record.get('soil_adc', ''),
                        record.get('do_mgl', ''),
                        record.get('eh_mv', ''),
                    ])
    except Exception:
        rows = []

    filename = 'qinghe_history_%d_%d.csv' % (uid, int(time.time() * 1000))
    return _csv_response(_build_csv(HISTORY_HEADER, rows), filename)


@bp.get('/api/export/alerts.csv')
def export_alerts_csv():
    """导出告警记录为 CSV（按 ts 倒序；告警表未建表时只返回表头）。"""
    uid = _current_uid()
    if uid is None:
        return _unauthorized()
    limit = _parse_limit(request.args.get('limit'), 200)
    if limit is None:
        return jsonify({'error': 'limit 必须是正整数（超过 %d 按上限截断）' % MAX_EXPORT_ROWS}), 400
    since_ts = _parse_int(request.args.get('since_ts'), 0, 0, 2 ** 62)
    if since_ts is None:
        return jsonify({'error': 'since_ts 必须是非负整数'}), 400

    rows = []
    try:
        with closing(db.get_db()) as conn:
            columns = _table_columns(conn, 'alerts')
            if columns:
                selected = [name for name in ('ts', 'level', 'code', 'content', 'acked')
                            if name in columns]
                sql = 'SELECT %s FROM alerts WHERE user_id = ? AND ts >= ?' \
                      ' ORDER BY ts DESC LIMIT ?' % ', '.join(selected)
                for row in conn.execute(sql, (int(uid), int(since_ts), int(limit))).fetchall():
                    record = dict(zip(selected, row))
                    rows.append([
                        _fmt_ts(record.get('ts')),
                        record.get('ts', ''),
                        record.get('level', ''),
                        record.get('code', ''),
                        record.get('content', ''),
                        '已确认' if record.get('acked') else '未确认',
                    ])
    except Exception:
        rows = []

    filename = 'qinghe_alerts_%d_%d.csv' % (uid, int(time.time() * 1000))
    return _csv_response(_build_csv(ALERTS_HEADER, rows), filename)
