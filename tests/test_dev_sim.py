"""设备模拟器（无实物主板）测试。

覆盖：场景序列的物理合理性、run_simulation 走真实链路（历史/心跳/告警）、
HTTP 接口开关（FARM_DEV_SIM）、参数校验、以及 tools/selftest 依赖的契约。
"""

import pytest

from qinghe import config, simulate

from helpers import login_session


# ---------------------------------------------------------------- 纯函数

def test_build_series_length_and_keys():
    """每条采样含设备上报的八项属性。"""
    series = simulate.build_series('normal', 5)
    assert len(series) == 5
    for item in series:
        for key in ('waterlevel', 'humidity', 'do', 'eh', 'air_pump', 'water_pump'):
            assert key in item, key
        assert 0 <= item['waterlevel'] <= config.ADC_MAX
        assert 0 <= item['humidity'] <= config.ADC_MAX


def test_samples_are_clamped():
    """条数 0 回退默认，超大值夹到上限，非法场景回退 normal。"""
    assert len(simulate.build_series('normal', 0)) == simulate.DEFAULT_SAMPLES
    assert len(simulate.build_series('normal', 999)) == simulate.MAX_SAMPLES
    assert len(simulate.build_series('不存在', 3)) == 3


def test_anaerobic_scenario_goes_anoxic():
    """缺氧场景末端 DO 低、Eh 为负、气泵开启。"""
    tail = simulate.build_series('anaerobic', 24)[-1]
    assert tail['do'] < 1.5
    assert tail['eh'] < 0
    assert tail['air_pump'] == 'on'


def test_drought_scenario_dries_out():
    """干旱场景末端水位与墒情都低，触发水泵。"""
    tail = simulate.build_series('drought', 24)[-1]
    water_mm = tail['waterlevel'] / config.ADC_MAX * config.WATER_FS_MM
    soil_pct = (config.ADC_MAX - tail['humidity']) / config.ADC_MAX * 100
    assert water_mm < 45
    assert soil_pct < 35
    assert tail['water_pump'] == 'on'


def test_scenario_meta_and_describe():
    """四个场景都要有中文名与说明。"""
    assert len(simulate.SCENARIOS) == 4
    described = simulate.describe_scenarios()
    assert [item['key'] for item in described] == list(simulate.SCENARIOS)
    assert all(item['name'] and item['desc'] for item in described)


# ---------------------------------------------------------------- 链路

@pytest.fixture()
def sim_on(monkeypatch):
    """打开模拟器开关。"""
    monkeypatch.setenv('FARM_DEV_SIM', '1')
    return True


def test_run_simulation_writes_history_and_heartbeat(client, registered, sim_on):
    """注入后历史有数据、心跳在线、RORI 上下文有值。"""
    from qinghe import iot, planner

    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    result = simulate.run_simulation(uid, 'normal', samples=6, interval=60, emit=False)
    assert result['samples'] == 6
    iot.flush_history()

    rows = client.get('/api/history?limit=10').get_json()['data']
    assert len(rows) == 6
    assert rows[-1]['do_mgl'] is not None

    status = client.get('/api/device_status').get_json()
    assert status['online'] is True
    assert planner.build_context(uid)['rori'] is not None


def test_anaerobic_simulation_raises_alert(client, registered, sim_on):
    """缺氧场景会产生 rori_high 服务端告警。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    simulate.run_simulation(uid, 'anaerobic', samples=6, interval=60, emit=False)
    body = client.get('/api/alerts?limit=50').get_json()
    assert 'rori_high' in [item['code'] for item in body['alerts']]


# ---------------------------------------------------------------- 接口

def test_scenarios_404_when_disabled(client, registered):
    """未开 FARM_DEV_SIM 时接口按 404 隐藏。"""
    login_session(client, *registered)
    assert client.get('/api/dev/scenarios').status_code == 404
    assert client.post('/api/dev/simulate', json={'scenario': 'normal'}).status_code == 404


def test_simulate_requires_login(client, sim_on):
    """开了模拟器也必须登录。"""
    assert client.get('/api/dev/scenarios').status_code == 401
    assert client.post('/api/dev/simulate', json={}).status_code == 401


def test_scenarios_list(client, registered, sim_on):
    """登录后能拿到四个场景。"""
    login_session(client, *registered)
    body = client.get('/api/dev/scenarios').get_json()
    assert body['status'] == 'success'
    assert len(body['scenarios']) == 4


def test_simulate_endpoint(client, registered, sim_on):
    """接口注入后返回概要，条数与入参一致。"""
    login_session(client, *registered)
    resp = client.post('/api/dev/simulate', json={
        'scenario': 'storm', 'samples': 3, 'interval': 30})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['samples'] == 3
    assert body['scenario'] == 'storm'
    assert body['last_ts'] > body['first_ts']


def test_simulate_rejects_bad_params(client, registered, sim_on):
    """未知场景 / 非数字条数 → 400。"""
    login_session(client, *registered)
    assert client.post('/api/dev/simulate', json={'scenario': 'no-such'}).status_code == 400
    assert client.post('/api/dev/simulate', json={'samples': 'abc'}).status_code == 400
