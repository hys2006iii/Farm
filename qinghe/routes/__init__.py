"""青禾智灌 —— HTTP 蓝图包。

各蓝图 URL 规则与旧版 app.py 逐字一致（不含 url_prefix，直接写全路径）。
"""

from qinghe.routes import (  # noqa: F401
    ai_routes,
    app_routes,
    auth_routes,
    config_routes,
    data_routes,
    export_routes,
    insight_routes,
    monitor_routes,
)

__all__ = [
    'ai_routes',
    'app_routes',
    'auth_routes',
    'config_routes',
    'data_routes',
    'export_routes',
    'insight_routes',
    'monitor_routes',
]
