"""pytest 公共 fixture。

关键约定：
- `FARM_DB_PATH` 指向 tmp 文件，测试之间完全隔离，不碰真实 qinghe.db；
- `FARM_SECRET_KEY` 固定，保证 JWT 断言稳定；
- `FARM_DEBUG=0`，避免兜底密钥警告刷屏；
- 每个测试用例前后重置登录限流状态与 MQTT 注册表。

helper 函数（make_user / login_session 等）放在 `helpers.py`，测试模块直接
`from helpers import make_user`（rootdir 已加入 sys.path）。
"""

import importlib
import os
import sys

import pytest

# 让 tests/ 能 import 到仓库根目录的 app / qinghe，以及同目录的 helpers
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for path in (ROOT, TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """把环境变量指向临时数据库，并返回该路径。"""
    db_path = str(tmp_path / 'test_qinghe.db')
    monkeypatch.setenv('FARM_DB_PATH', db_path)
    monkeypatch.setenv('FARM_SECRET_KEY', 'test_secret_key_2026')
    monkeypatch.setenv('FARM_DEBUG', '0')
    return db_path


@pytest.fixture()
def flask_app(app_env):
    """装配好的 Flask 应用（已建表），每个用例一个全新临时库。"""
    import qinghe
    import qinghe.db as db

    # 强制重新执行建表（临时库是新的）
    db.init_db(force=True)
    db.init_geo_cache()
    app, _socketio = qinghe.create_app()
    app.config.update(TESTING=True)
    yield app


@pytest.fixture()
def socketio_instance(flask_app):
    """与 flask_app 绑定的 SocketIO 实例。"""
    import qinghe
    return qinghe.socketio


@pytest.fixture()
def client(flask_app):
    """Flask 测试客户端。"""
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_global_state():
    """每个用例前后清理全局状态：登录限流、MQTT 注册表。"""
    from qinghe import auth, iot

    auth.reset_login_failures()
    iot.mqtt_clients.clear()
    # 告警判定限频表是进程级全局，测试之间必须清掉，否则后一个用例的首批上报会被跳过
    iot._alert_eval_last.clear()
    yield
    auth.reset_login_failures()
    iot.mqtt_clients.clear()
    iot._alert_eval_last.clear()


@pytest.fixture()
def registered(client):
    """已注册并登录的用户：返回 (username, password)。"""
    username, password = 'farmer01', 'secret123'
    resp = client.post('/api/register', json={'username': username, 'password': password})
    assert resp.get_json()['status'] == 'success'
    resp = client.post('/api/login', json={'username': username, 'password': password})
    assert resp.get_json()['status'] == 'success'
    return username, password


@pytest.fixture()
def auth_headers(client, registered):
    """通过 /api/app_login 拿到 JWT 请求头。"""
    username, password = registered
    resp = client.post('/api/app_login', json={'username': username, 'password': password})
    token = resp.get_json()['token']
    return {'Authorization': 'Bearer %s' % token}


def reload_module(name):
    """重新导入模块（用于验证 import 期副作用）。"""
    return importlib.import_module(name)
