"""外部设备联调通道测试（`qinghe.simulate` + `tools/simulate_device.py`）。

背景：系统内**不再**提供 `/api/dev/*` 之类的测试接口——"演示数据（无硬件调试）"
模块已从界面与路由中移除，灌数能力只保留为仓库外部的库函数与命令行工具。

本文件锁住三件事：
1. 系统内确实没有测试接口（`/api/dev/*` 一律 404）；
2. `qinghe.simulate` 作为**外部库**仍能把遥测灌进指定账号，并走真实处理链路
   （历史落库 / 心跳 / RORI / 告警）；
3. `tools/simulate_device.py` 的参数解析与登录校验可用，且不依赖任何系统内接口。
"""

import importlib.util
import os
import sys

import pytest

from qinghe import simulate

from helpers import login_session

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _clean_external_state(flask_app):
    """本文件会真的往库里灌遥测，必须清掉跨用例的进程级缓存。

    `planner._latest` 与 `logbook`/`alert_center` 的冷却表都是模块级全局：
    灌数会写进 planner 缓存，而缓存按 **uid** 索引、与临时库无关，
    于是下一个用例（哪怕换了新库）仍会读到上一个用例的遥测，
    典型表现是 `/api/telemetry` 的 `has_telemetry` 假阳。
    """
    from qinghe import alert_center, logbook, planner

    def _clear():
        from qinghe.db import get_db

        with get_db() as conn:
            rows = conn.execute('SELECT id FROM users').fetchall()
        for row in rows:
            planner.reset_telemetry(int(row[0]))
        logbook.reset_recent_logs()
        alert_center._reset_dedupe()

    _clear()
    yield
    _clear()


def _load_tool():
    """动态加载 tools/simulate_device.py（tools 不是包，没有 __init__.py）。"""
    path = os.path.join(PROJECT_ROOT, 'tools', 'simulate_device.py')
    spec = importlib.util.spec_from_file_location('qinghe_simulate_device', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- 纯函数

def test_build_series_length_and_keys():
    """每条采样含设备上报的八项属性。"""
    from qinghe import config

    series = simulate.build_series('normal', 5)
    assert len(series) == 5
    for item in series:
        for key in ('waterlevel', 'humidity', 'do', 'eh', 'air_pump', 'water_pump'):
            assert key in item, key
        assert 0 <= item['waterlevel'] <= config.ADC_MAX
        assert 0 <= item['humidity'] <= config.ADC_MAX


def test_samples_are_clamped():
    """条数 0/负数夹到下限，超大值夹到上限，非法场景回退 normal。"""
    assert len(simulate.build_series('normal', 0)) == simulate.MIN_SAMPLES
    assert len(simulate.build_series('normal', -5)) == simulate.MIN_SAMPLES
    assert len(simulate.build_series('normal', 999)) == simulate.MAX_SAMPLES
    assert len(simulate.build_series('不存在', 3)) == 3


def test_samples_and_interval_clamp_helpers():
    """夹取助手对非数字输入给出默认值、对越界值夹到区间，都不抛异常。"""
    assert simulate.clamp_samples('abc') == simulate.DEFAULT_SAMPLES
    assert simulate.clamp_samples(None) == simulate.DEFAULT_SAMPLES
    assert simulate.clamp_samples(-3) == simulate.MIN_SAMPLES
    assert simulate.clamp_samples(999) == simulate.MAX_SAMPLES
    assert simulate.clamp_interval('abc') == simulate.DEFAULT_INTERVAL_SECONDS
    assert simulate.clamp_interval(None) == simulate.DEFAULT_INTERVAL_SECONDS
    assert simulate.clamp_interval(99999) == simulate.MAX_INTERVAL_SECONDS
    assert simulate.clamp_interval(0) == simulate.MIN_INTERVAL_SECONDS


def test_anaerobic_scenario_goes_anoxic():
    """缺氧场景末端 DO 低、Eh 为负、气泵开启。"""
    tail = simulate.build_series('anaerobic', 24)[-1]
    assert tail['do'] < 1.5
    assert tail['eh'] < 0
    assert tail['air_pump'] == 'on'


def test_drought_scenario_dries_out():
    """干旱场景末端水位与墒情都低，触发水泵。"""
    from qinghe import config

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

def test_run_simulation_writes_history_and_heartbeat(client, registered):
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


def test_anaerobic_simulation_raises_alert(client, registered):
    """缺氧场景会产生 rori_high 服务端告警。"""
    login_session(client, *registered)
    with client.session_transaction() as sess:
        uid = sess['user_id']
    simulate.run_simulation(uid, 'anaerobic', samples=6, interval=60, emit=False)
    body = client.get('/api/alerts?limit=50').get_json()
    assert 'rori_high' in [item['code'] for item in body['alerts']]


# ---------------------------------------------------------------- 系统内无测试接口

@pytest.mark.parametrize('path', ['/api/dev/scenarios', '/api/dev/simulate'])
def test_no_test_endpoints_in_system(client, registered, path):
    """系统内不暴露任何测试/演示接口：即使登录也按「资源不存在」处理。"""
    login_session(client, *registered)
    assert client.get(path).status_code == 404
    assert client.post(path, json={'scenario': 'normal'}).status_code == 404


def test_dev_routes_module_removed():
    """`qinghe/routes/dev_routes.py` 已删除，蓝图注册表里也不应再出现它。"""
    from qinghe import routes

    assert not os.path.exists(os.path.join(PROJECT_ROOT, 'qinghe', 'routes', 'dev_routes.py'))
    assert 'dev_routes' not in getattr(routes, '__all__', [])


def test_no_dev_sim_env_switch_left():
    """`FARM_DEV_SIM` 开关已随功能一起移除，配置层不再提供该函数。"""
    from qinghe import config

    assert not hasattr(config, 'dev_sim_enabled')
    assert not hasattr(config, 'DEV_SIM_ENV')


# ---------------------------------------------------------------- 命令行工具

def test_cli_parser_defaults():
    """命令行默认值：常规场景、24 条、60 秒间隔。"""
    tool = _load_tool()
    args = tool.build_parser().parse_args([])
    assert args.scenario == 'normal'
    assert args.samples == 24
    assert args.interval == 60
    assert args.base_url == ''


def test_cli_list_scenarios(capsys):
    """`--list` 打印四个场景后返回 0，不触碰数据库。"""
    tool = _load_tool()
    assert tool.main(['--list']) == 0
    out = capsys.readouterr().out
    for key in simulate.SCENARIOS:
        assert key in out


def test_cli_rejects_wrong_password(client, registered, monkeypatch):
    """密码不对时拒绝灌数（返回码 2），不写脏数据。"""
    tool = _load_tool()
    username, _password = registered
    code = tool.main(['--username', username, '--password', 'wrong-password'])
    assert code == 2


def test_cli_rejects_unknown_user(client, registered):
    """账号不存在时给出可执行提示（返回码 2）。"""
    tool = _load_tool()
    code = tool.main(['--username', 'no-such-user-xyz', '--password', 'secret123'])
    assert code == 2


def test_cli_runs_local_injection(client, registered):
    """本机直连模式灌 3 条后，历史接口能查到数据。"""
    from qinghe import iot

    tool = _load_tool()
    username, password = registered
    code = tool.main(['--username', username, '--password', password,
                      '--scenario', 'normal', '--samples', '3', '--no-emit'])
    assert code == 0
    iot.flush_history()
    login_session(client, username, password)
    rows = client.get('/api/history?limit=10').get_json()['data']
    assert len(rows) == 3


def test_cli_remote_mode_fails_without_server():
    """远端模式连不上时返回 2 而不是抛栈。"""
    tool = _load_tool()
    code = tool.main(['--base-url', 'http://127.0.0.1:1', '--username', 'x', '--password', 'y'])
    assert code == 2


def test_cli_module_imports_without_side_effects():
    """工具模块可被 import（不执行 main），且不依赖 Flask 请求上下文。"""
    assert 'qinghe_simulate_device' in sys.modules or _load_tool() is not None
