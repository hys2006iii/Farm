"""青禾智灌智慧灌溉管理平台 —— 应用入口。

职责仅有两件事：
1. 调用 `qinghe.create_app()` 装配应用，导出 `app` / `socketio`（供 WSGI 与测试引用）；
2. 直接 `python app.py` 时启动开发服务器。

业务逻辑一律放在 `qinghe/` 包内，本文件不再新增任何路由或业务代码。
"""

import os

from qinghe import config, create_app

app, socketio = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', str(config.DEFAULT_PORT)))
    # 生产环境必须 FARM_DEBUG=0；debug 模式会暴露调试器，不要对外开放
    debug = config.is_debug()
    socketio.run(
        app, debug=debug, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True
    )
