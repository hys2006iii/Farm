"""青禾智灌 —— 业务包入口与应用工厂。

`create_app()` 负责装配 Flask 应用、注册蓝图、注册 SocketIO 事件与 after_request，
并保证数据库与缓存表已完成初始化（幂等）。
"""

import logging

from flask import Flask, jsonify
from flask_socketio import SocketIO

from qinghe import config
from qinghe.db import init_db, init_geo_cache

__all__ = ['create_app', 'socketio']

#: 进程级单例：`app.py` 与测试都通过它拿到同一个 socketio 实例
socketio = SocketIO()

_logger = logging.getLogger('qinghe')

_SECRET_WARN = (
    '安全警告：未配置环境变量 FARM_SECRET_KEY，已使用本进程随机密钥。'
    '重启后登录态（会话 / JWT）将全部失效；生产请运行 tools/gen_secret.py 生成密钥并写入 .env。'
)


def _warn_default_secret() -> None:
    """未显式配置密钥时打印一次显著警告（不改变任何启动行为）。

    注意：此时签名用的是 `config.get_secret_key()` 生成的**进程级随机密钥**，
    而非硬编码常量，因此不存在「公开密钥可伪造 JWT」的问题；告警只为提示
    运维显式配置以获得跨重启稳定的会话。
    """
    if config.secret_key_is_configured():
        return
    _logger.warning('*' * 78)
    _logger.warning(_SECRET_WARN)
    _logger.warning('*' * 78)


def _register_security_headers(app: Flask) -> None:
    """注册统一安全响应头（含 CSP）。"""

    @app.after_request
    def add_security_headers(resp):
        for key, value in config.SECURITY_HEADERS.items():
            resp.headers.setdefault(key, value)
        return resp


def _register_blueprints(app: Flask) -> None:
    """注册全部 HTTP 蓝图，URL 前缀与旧版 app.py 逐字保持一致。"""
    from qinghe.routes import (
        ai_routes,
        app_routes,
        auth_routes,
        config_routes,
        data_routes,
        export_routes,
        insight_routes,
        monitor_routes,
    )

    app.register_blueprint(app_routes.bp)
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(config_routes.bp)
    app.register_blueprint(data_routes.bp)
    app.register_blueprint(ai_routes.bp)
    app.register_blueprint(insight_routes.bp)
    app.register_blueprint(export_routes.bp)
    app.register_blueprint(monitor_routes.bp)


def _register_error_handlers(app: Flask) -> None:
    """兜底错误处理：避免未捕获异常把 500 堆栈泄露给客户端。"""

    @app.errorhandler(404)
    def _not_found(err):  # noqa: ARG001
        return jsonify({'error': '未找到资源'}), 404

    @app.errorhandler(405)
    def _method_not_allowed(err):  # noqa: ARG001
        return jsonify({'error': '请求方法不允许'}), 405


def create_app(init_storage: bool = True) -> tuple:
    """应用工厂：装配并返回 `(app, socketio)`。

    参数:
        init_storage: 是否执行建表/迁移与 geo_cache 初始化（默认 True，幂等）。

    返回:
        (Flask, SocketIO) 二元组，与旧版 `app` / `socketio` 全局对象等价。
    """
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.secret_key = config.get_secret_key()
    _warn_default_secret()

    _register_security_headers(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    if init_storage:
        init_db()
        init_geo_cache()

    socketio.init_app(app, cors_allowed_origins='*')

    # SocketIO 事件在此处导入并注册，避免与 iot 模块形成循环依赖
    from qinghe import realtime  # noqa: F401

    return app, socketio
