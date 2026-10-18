"""青禾智灌 —— 无实物主板的端到端自测脚本。

不依赖 MQTT、不依赖外网、不需要提前启动服务端、**也不依赖任何系统内的测试接口**：
用 Flask 测试客户端 + 临时数据库把整条业务链路跑一遍，逐项打印 PASS/FAIL，
最后给出汇总与退出码。灌数走 `qinghe.simulate.run_simulation()`（外部联调通道），
与真实 MQTT 上报共用 `iot.ingest_telemetry()` 链路。

覆盖链路：
  注册 → 登录（含地块清单）→ 模拟设备上报（四路遥测 + 泵状态）
  → 历史落库与查询 → RORI/上下文换算 → 七日灌溉建议
  → 服务端告警 → 运行日志 → 设备心跳 → AI 上下文快照 → CSV 导出
  → 多农场新增/切换/删除

用法::

    python tools/selftest_no_hardware.py            # 全部检查
    python tools/selftest_no_hardware.py -v         # 每条检查附细节

退出码 0 = 全部通过；1 = 有失败项。既可在本地手动跑，也可接进 CI。
"""

import argparse
import os
import sys
import tempfile

# Windows 控制台默认 GBK，打印 ⚠/中文/百分比会 UnicodeEncodeError，这里强制 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHECKED = []


def check(name):
    """装饰器：登记一条检查，捕获异常并记录结果。"""
    def wrapper(func):
        CHECKED.append((name, func))
        return func
    return wrapper


def _client(tmpdir):
    """构造绑定临时库的测试客户端（不依赖任何系统内测试接口）。"""
    os.environ['FARM_DB_PATH'] = os.path.join(tmpdir, 'selftest.db')
    os.environ['FARM_SECRET_KEY'] = 'selftest_secret_key_0123456789abcdef'
    os.environ['FARM_DEBUG'] = '0'
    for module in [m for m in list(sys.modules) if m == 'qinghe' or m.startswith('qinghe.')]:
        del sys.modules[module]
    from qinghe import config, create_app
    config.DB_PATH = os.environ['FARM_DB_PATH']
    app, _socketio = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _current_uid(client):
    """取当前会话的 user_id（供外部灌数通道直接使用）。"""
    with client.session_transaction() as sess:
        return sess.get('user_id')


class Context:
    """检查之间共享的运行时状态（客户端、用户 id、地块 id）。"""

    def __init__(self, client):
        self.client = client
        self.uid = None
        self.farm_id = None

    def login(self):
        """注册并登录一个自测账号。"""
        resp = self.client.post('/api/register', json={
            'username': 'selftest', 'password': 'selftest123'})
        assert resp.status_code == 200, '注册失败：%s %s' % (resp.status_code, resp.get_json())
        resp = self.client.post('/api/login', json={
            'username': 'selftest', 'password': 'selftest123'})
        assert resp.status_code == 200, '登录失败：%s' % (resp.status_code, resp.get_json())
        body = resp.get_json()
        self.farm_id = body.get('active_farm_id')
        assert self.farm_id, '登录响应缺少 active_farm_id'
        self.uid = _current_uid(self.client)
        assert self.uid, '会话里没有 user_id'
        return body


@check('注册与登录（返回默认地块）')
def test_login(ctx):
    """登录响应必须带 active_farm_id 与 farms 列表。"""
    body = ctx.login()
    assert body['farms'], '登录响应 farms 为空'
    assert 'status' not in body or body['status'] == 'success'
    return 'active_farm_id=%s，farms=%d 块' % (body['active_farm_id'], len(body['farms']))


@check('模拟设备上报（常规场景 12 条）')
def test_inject_normal(ctx):
    """按常规场景灌 12 条遥测，应全部接收。

    走的是外部联调通道：直接调用 `qinghe.simulate.run_simulation()`，
    与真实 MQTT 上报共用 `iot.ingest_telemetry()` 链路，系统内无测试接口。
    """
    from qinghe import simulate

    result = simulate.run_simulation(ctx.uid, 'normal', samples=12, interval=60, emit=False)
    assert result['samples'] == 12, '期望 12 条，实际 %s' % result['samples']
    return 'scenario=%s，%s 条' % (result['scenario'], result['samples'])


@check('历史落库含 DO / Eh 四路数据')
def test_history(ctx):
    """抽一条历史，确认溶解氧与氧化还原电位不为空。"""
    from qinghe import iot
    iot.flush_history()  # 落库是批量异步的，先冲一次队列
    resp = ctx.client.get('/api/history?limit=20')
    assert resp.status_code == 200
    rows = (resp.get_json() or {}).get('data') or []
    assert rows, '历史为空'
    row = rows[-1]
    assert row.get('water_adc') is not None
    assert row.get('do_mgl') is not None, '历史缺溶解氧（D-01 回归）'
    assert row.get('eh_mv') is not None, '历史缺氧化还原电位（D-01 回归）'
    return '%d 条样本，末条 DO=%s Eh=%s' % (len(rows), row['do_mgl'], row['eh_mv'])


@check('RORI 与实时上下文换算')
def test_context(ctx):
    """planner.build_context 应给出 RORI 与水位/墒情换算值。"""
    from qinghe import planner
    ctx_uid = _current_uid(ctx.client)
    planner.update_telemetry(ctx_uid, waterlevel=1500, humidity=2200, do=6.0, eh=120.0)
    data = planner.build_context(ctx_uid)
    assert data.get('water_mm') is not None, '水位未换算'
    assert data.get('rori') is not None, 'RORI 未计算'
    assert 0 <= data['rori'] <= 100
    return 'water=%.2fmm soil=%s%% rori=%.2f' % (
        data['water_mm'], _fmt(data.get('soil_pct')), data['rori'])


@check('七日灌溉建议接口')
def test_advice(ctx):
    """建议接口应返回 7 天计划与总览。"""
    resp = ctx.client.get('/api/advice/calendar')
    assert resp.status_code == 200, '%s %s' % (resp.status_code, resp.get_json())
    body = resp.get_json()
    assert body['status'] == 'success'
    assert len(body['days']) == 7, '期望 7 天，实际 %s' % len(body['days'])
    return 'has_forecast=%s，summary=%s' % (
        body['has_forecast'], body['summary'][:24])


@check('服务端告警（缺氧场景产生告警）')
def test_alerts(ctx):
    """缺氧场景应产生 rori_high 告警并可被查询/确认。"""
    from qinghe import simulate

    simulate.run_simulation(ctx.uid, 'anaerobic', samples=6, interval=60, emit=False)
    resp = ctx.client.get('/api/alerts?limit=50')
    assert resp.status_code == 200
    body = resp.get_json()
    alerts = body.get('alerts') or []
    assert alerts, '缺氧场景后仍无告警'
    codes = [item.get('code') for item in alerts]
    assert 'rori_high' in codes, '告警类型缺少 rori_high：%s' % codes
    ack = ctx.client.post('/api/alerts/ack', json={'id': alerts[0]['id']})
    assert ack.status_code == 200, '确认告警失败'
    return '告警 %d 条，含 rori_high，首条已确认' % len(alerts)


@check('运行日志（服务端落库）')
def test_logs(ctx):
    """运行日志接口应能读到批次日志。"""
    from qinghe import logbook
    logbook.flush_logs(timeout=3.0)
    resp = ctx.client.get('/api/logs?limit=50')
    assert resp.status_code == 200
    logs = resp.get_json()
    assert logs, '日志为空（flush 后仍无数据）'
    return '%d 条日志' % len(logs)


@check('设备心跳状态')
def test_heartbeat(ctx):
    """刚灌过数据，设备状态应为在线。"""
    resp = ctx.client.get('/api/device_status')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get('online') is True, '设备应在线：%s' % body
    return 'online=%s，online_seconds=%s' % (body.get('online'), body.get('online_seconds'))


@check('AI 上下文快照')
def test_ai_snapshot(ctx):
    """AI 接口在无 Key 时也应返回带实时快照的提示。"""
    resp = ctx.client.post('/api/ai_chat', json={'message': '现在要不要开泵？'})
    assert resp.status_code == 200
    body = resp.get_json()
    content = body['choices'][0]['message']['content']
    assert '当前地块' in content and '四路读数' in content, '缺少实时快照块：%s' % content[:120]
    return '%d 字符，含实时快照' % len(content)


@check('CSV 导出（历史 + 告警）')
def test_export(ctx):
    """两个导出接口都应返回 CSV 附件。"""
    for path in ('/api/export/history.csv', '/api/export/alerts.csv'):
        resp = ctx.client.get(path)
        assert resp.status_code == 200, '%s 返回 %s' % (path, resp.status_code)
        assert 'text/csv' in resp.headers.get('Content-Type', '')
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
    return 'history.csv / alerts.csv 均 200'


@check('多农场：新增 → 切换 → 删除')
def test_farms(ctx):
    """地块 CRUD 与切换、以及当前地块的隔离。"""
    resp = ctx.client.post('/api/farms', json={
        'name': '北洼试验田', 'lat': 23.13, 'lon': 113.27, 'area_m2': 400})
    assert resp.status_code == 200, '新增地块失败：%s' % resp.get_json()
    body = resp.get_json()
    new_id = (body.get('farm') or {}).get('id') or body.get('farm_id')
    assert new_id, '新增响应缺少 id：%s' % body
    resp = ctx.client.post('/api/farms/switch', json={'farm_id': new_id})
    assert resp.status_code == 200, '切换失败：%s' % resp.get_json()
    resp = ctx.client.get('/api/farms')
    assert resp.status_code == 200
    farms = (resp.get_json() or {}).get('farms') or []
    ids = [f['id'] for f in farms]
    assert new_id in ids and len(ids) >= 2, '地块清单异常：%s' % farms
    resp = ctx.client.post('/api/farms/delete', json={'farm_id': new_id})
    assert resp.status_code == 200, '删除失败：%s' % resp.get_json()
    return '新增 id=%s 已切块并删除，剩余 %d 块' % (new_id, len(ids) - 1)


@check('知识库页面（登录后 200）')
def test_knowledge(ctx):
    """知识库模板应由服务端正常渲染。"""
    resp = ctx.client.get('/knowledge')
    assert resp.status_code == 200, '知识库返回 %s' % resp.status_code
    body = resp.get_data(as_text=True)
    assert len(body) > 1000, '知识库页面内容过少'
    return 'knowledge.html 渲染 %d 字符' % len(body)


def _fmt(value):
    """保留两位小数的安全格式化。"""
    return '--' if value is None else '%.2f' % value


def main(argv=None):
    """逐条执行检查并汇总。"""
    parser = argparse.ArgumentParser(description='青禾智灌无硬件自测')
    parser.add_argument('-v', '--verbose', action='store_true', help='打印每条检查细节')
    args = parser.parse_args(argv)

    results = []
    with tempfile.TemporaryDirectory(prefix='qinghe_selftest_') as tmpdir:
        ctx = Context(_client(tmpdir))
        for name, func in CHECKED:
            try:
                detail = func(ctx)
                results.append((name, True, detail))
                print('PASS  %s' % name)
                if args.verbose and detail:
                    print('      %s' % detail)
            except Exception as exc:  # noqa: BLE001 - 自测脚本要把失败原因打给人看
                results.append((name, False, str(exc)))
                print('FAIL  %s' % name)
                print('      %s' % exc)

    passed = sum(1 for _n, ok, _d in results if ok)
    total = len(results)
    print('\n%s：%d/%d 通过' % ('全部通过' if passed == total else '存在失败', passed, total))
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
