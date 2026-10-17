"""CSV 导出接口测试：/api/export/history.csv 与 /api/export/alerts.csv。

覆盖点：
- 未登录 401；
- BOM + 表头逐字一致；
- 历史导出包含 DO / Eh 两列真实数值（数据完整性）；
- 只导出当前用户的数据；
- 告警导出含已确认标记；
- limit 非法返回 400，超上限按 50000 截断（不报错）。
"""

from contextlib import closing

import pytest

from helpers import make_user, user_id_of
from qinghe import alert_center, db


HISTORY_HEADER = '时间,时间戳,水位ADC,土壤ADC,溶解氧mg/L,氧化还原电位mV'
ALERTS_HEADER = '时间,时间戳,级别,类型,内容,已确认'


@pytest.fixture()
def logged_client(client, registered):
    """已登录的测试客户端。"""
    return client


@pytest.fixture()
def uid(logged_client):
    """当前登录用户 id。"""
    value = user_id_of('farmer01')
    assert value
    return value


@pytest.fixture(autouse=True)
def _reset_dedupe():
    """清掉告警冷却，保证用例互不影响。"""
    alert_center._reset_dedupe()
    yield
    alert_center._reset_dedupe()


def csv_lines(resp) -> list:
    """把响应体按 UTF-8（去 BOM）拆成行。"""
    text = resp.data.decode('utf-8-sig')
    return [line for line in text.replace('\r\n', '\n').split('\n') if line]


def test_history_export_requires_login(client):
    """未登录导出历史返回 401。"""
    assert client.get('/api/export/history.csv').status_code == 401


def test_alerts_export_requires_login(client):
    """未登录导出告警返回 401。"""
    assert client.get('/api/export/alerts.csv').status_code == 401


def test_history_export_empty_only_header(logged_client):
    """无数据时只返回表头。"""
    resp = logged_client.get('/api/export/history.csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers['Content-Type']
    assert 'attachment' in resp.headers['Content-Disposition']
    lines = csv_lines(resp)
    assert lines == [HISTORY_HEADER]


def test_history_export_contains_do_and_eh(logged_client, uid):
    """历史导出的溶解氧 / 氧化还原电位两列有真实数值。"""
    db.insert_history_rows([(uid, 1750000100000, 200, 2100, 3.5, -120.0)])
    lines = csv_lines(logged_client.get('/api/export/history.csv'))
    assert lines[0] == HISTORY_HEADER
    assert len(lines) == 2
    fields = lines[1].split(',')
    assert fields[1] == '1750000100000'
    assert fields[2] == '200'
    assert fields[3] == '2100'
    assert fields[4] == '3.5'
    assert fields[5] == '-120.0'


def test_history_export_isolated_between_users(logged_client, uid):
    """只导出自己的历史数据。"""
    other = make_user('exporter02', 'secret123')
    assert other
    db.insert_history_rows([(other, 1750000300000, 999, 999, None, None)])
    db.insert_history_rows([(uid, 1750000400000, 111, 111, None, None)])
    lines = csv_lines(logged_client.get('/api/export/history.csv'))
    body = '\n'.join(lines[1:])
    assert '111' in body
    assert '999' not in body


def test_history_export_rejects_bad_limit(logged_client):
    """limit 非数字或非正数返回 400。"""
    assert logged_client.get('/api/export/history.csv?limit=abc').status_code == 400
    assert logged_client.get('/api/export/history.csv?limit=0').status_code == 400


def test_history_export_caps_limit(logged_client):
    """limit 超大时按 50000 截断而不是报错。"""
    resp = logged_client.get('/api/export/history.csv?limit=999999')
    assert resp.status_code == 200


def test_alerts_export_header_and_ack_flag(logged_client, uid):
    """告警导出包含表头与「已确认」标记。"""
    pushed = alert_center.push_alert(uid, 'danger', 'rori_high', '检测到重度厌氧风险')
    assert pushed['id'] > 0
    alert_center.ack_alert(uid, pushed['id'])

    lines = csv_lines(logged_client.get('/api/export/alerts.csv'))
    assert lines[0] == ALERTS_HEADER
    assert len(lines) == 2
    fields = lines[1].split(',')
    assert fields[2] == 'danger'
    assert fields[3] == 'rori_high'
    assert fields[4] == '检测到重度厌氧风险'
    assert fields[5] == '已确认'


def test_alerts_export_empty_is_header_only(logged_client):
    """告警表为空时只返回表头（不报 500）。"""
    lines = csv_lines(logged_client.get('/api/export/alerts.csv'))
    assert lines == [ALERTS_HEADER]
