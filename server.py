#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""青禾智灌 —— 校园网 / 局域网生产启动器。

用途
----
把本平台做成一台**校园网内其他人也能访问**的服务器。核心要点：

1. Flask-SocketIO 的 MQTT 回调在后台线程里 ``socketio.emit(...)``，
   因此 async_mode 必须是支持多线程的 ``threading``（werkzeug/waitress 走 WSGI）。
   **不要**改成 eventlet/gevent：paho-mqtt 的后台线程会和 monkey-patch 冲突。
2. HTTP 用 **waitress** 承载（纯 Python、Windows 友好、多线程 WSGI）。
   waitress 只跑 WSGI 应用，SocketIO 的长轮询请求照常由 WSGI 处理。
3. 若 waitress 不可用，回退到 ``socketio.run(..., allow_unsafe_werkzeug=True)``
   并打印显著警告（仅适合临时应急）。

环境变量
--------
``HOST``        监听地址，默认 ``0.0.0.0``（所有网卡，别人才能连进来）
``PORT``        监听端口，默认 ``5000``
``FARM_DEBUG``  调试开关，默认 ``0``（对外开放必须为 0）
``FARM_DB_PATH``/``FARM_SECRET_KEY`` 见 ``.env.example``

启动方式
--------
    python server.py            # 或双击 start_server.bat
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
DEFAULT_DEBUG = 0

#: SocketIO 使用的异步模式。本项目依赖「MQTT 后台线程 + emit」，
#: threading 是唯一安全选择，不要改成 eventlet/gevent。
SOCKETIO_ASYNC_MODE = "threading"


# ---------------------------------------------------------------------------
# 环境变量解析
# ---------------------------------------------------------------------------

def get_host(env: dict | None = None) -> str:
    """读取监听地址，缺省 ``0.0.0.0``（监听所有网卡，供校园网访问）。"""
    env = os.environ if env is None else env
    host = str(env.get("HOST", "") or "").strip()
    return host or DEFAULT_HOST


def get_port(env: dict | None = None) -> int:
    """读取监听端口，缺省 5000；非法值（非数字 / 越界）回退到默认端口。"""
    env = os.environ if env is None else env
    raw = str(env.get("PORT", "") or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except (TypeError, ValueError):
        print(f"[警告] PORT 取值非法（{raw!r}），已回退到 {DEFAULT_PORT}")
        return DEFAULT_PORT
    if not 1 <= port <= 65535:
        print(f"[警告] PORT 超出 1-65535（{port}），已回退到 {DEFAULT_PORT}")
        return DEFAULT_PORT
    return port


def get_debug(env: dict | None = None) -> bool:
    """读取调试开关，缺省 False（生产/对外开放必须关闭调试器）。"""
    env = os.environ if env is None else env
    raw = str(env.get("FARM_DEBUG", "") or "").strip().lower()
    if not raw:
        return bool(DEFAULT_DEBUG)
    return raw in ("1", "true", "yes", "on", "y", "t")


# ---------------------------------------------------------------------------
# 局域网地址枚举
# ---------------------------------------------------------------------------

def _iter_ipv4_candidates() -> list:
    """收集本机所有 IPv4 地址（可能包含回环 / APIPA，交给上层过滤）。"""
    candidates: list = []

    # 1) 通过 UDP「连接」一个外部地址，拿到系统选路时用的默认网卡地址。
    #    不会真的发包，但能拿到校园网 IP。
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            candidates.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    # 2) 主机名解析出的全部地址（多网卡 / 虚拟机网卡）。
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except OSError:
        pass

    return candidates


def is_usable_lan_ip(ip: str) -> bool:
    """判断一个 IPv4 地址是否适合作为「校园网访问地址」展示。

    过滤规则：非 IPv4、回环 127.0.0.0/8、链路本地 APIPA 169.254.0.0/16、
    未指定 0.0.0.0、组播与保留地址。
    """
    try:
        addr = ipaddress.IPv4Address(str(ip).strip())
    except (ipaddress.AddressValueError, ValueError):
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return False
    if addr.is_unspecified or addr.is_reserved:
        return False
    return True


def list_lan_ips(candidates=None) -> list:
    """返回排序去重后的局域网 IPv4 列表（供启动时打印给用户）。

    :param candidates: 候选地址；缺省时自动枚举本机网卡。
    """
    if candidates is None:
        candidates = _iter_ipv4_candidates()

    seen = []
    for raw in candidates:
        ip = str(raw).strip()
        if is_usable_lan_ip(ip) and ip not in seen:
            seen.append(ip)

    # 排序：10.x（校园网常见）→ 172.16-31.x → 192.168.x，其余按数值升序。
    def _rank(ip: str):
        addr = ipaddress.IPv4Address(ip)
        value = int(addr)
        if ip.startswith("10."):
            group = 0
        elif ip.startswith("172."):
            group = 1 if 16 <= int(ip.split(".")[1]) <= 31 else 3
        elif ip.startswith("192.168."):
            group = 2
        else:
            group = 3
        return (group, value)

    return sorted(seen, key=_rank)


# ---------------------------------------------------------------------------
# 应用装配（兼容重构前后两种形态）
# ---------------------------------------------------------------------------

def load_app():
    """加载 Flask 应用与 SocketIO 实例。

    优先使用应用工厂 ``qinghe.create_app()``（返回 ``(app, socketio)``）；
    失败则回退到 ``app.py`` 的模块级 ``app`` / ``socketio`` 单例。
    返回 ``(app, socketio, init_hooks)``，``init_hooks`` 为启动前需调用的初始化函数列表。

    注意：两种路径都**不需要**外部再调用 ``init_db`` / ``init_geo_cache``——
    ``create_app()`` 内部已完成（幂等），而 ``app.py`` 本身也是调用 ``create_app()`` 得到的。
    因此 ``init_hooks`` 恒为空列表，保留该返回值只是为了向后兼容。
    """
    try:
        from qinghe import create_app  # type: ignore

        result = create_app()
        if isinstance(result, tuple):
            app, socketio = result[0], result[1]
        else:  # 工厂只返回 app 时，从包内取 socketio
            app = result
            from qinghe import socketio  # type: ignore

        print("[启动] 已加载 qinghe 应用工厂 create_app()（存储已由工厂初始化）")
        return app, socketio, []
    except Exception as exc:  # noqa: BLE001 - 回退到单文件入口
        if not isinstance(exc, ImportError):
            print(f"[警告] qinghe 应用工厂加载失败（{exc}），回退到 app.py")

    # app.py 只导出 app / socketio 两个对象（其内部同样调用 create_app()），
    # 这里不要导入 init_db / init_geo_cache，否则回退路径必抛 ImportError。
    from app import app, socketio  # type: ignore

    print("[启动] 已加载 app.py 应用入口")
    return app, socketio, []


def run_init_hooks(hooks) -> None:
    """启动前执行数据库 / 地理缓存初始化，失败只告警不阻断启动。"""
    for hook in hooks or []:
        name = getattr(hook, "__name__", repr(hook))
        try:
            hook()
            print(f"[启动] {name}() 完成")
        except Exception as exc:  # noqa: BLE001 - 初始化失败不应让服务起不来
            print(f"[警告] {name}() 执行失败：{exc}")


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def print_banner(host: str, port: int, debug: bool, lan_ips: list) -> None:
    """打印启动横幅与所有可用的访问地址。"""
    line = "=" * 58
    print()
    print(line)
    print("  青禾智灌服务已启动")
    print(line)
    print(f"  本机访问:   http://127.0.0.1:{port}")
    if lan_ips:
        for idx, ip in enumerate(lan_ips):
            tip = "   ← 把这个地址发给同学" if idx == 0 else ""
            print(f"  校园网访问: http://{ip}:{port}{tip}")
    else:
        print("  校园网访问: 未检测到局域网 IP（请检查网卡是否已连接校园网）")
    print(f"  监听地址:   {host}:{port}")
    print(f"  调试模式:   {'开启（仅本机调试，不要对外开放）' if debug else '关闭（生产模式）'}")
    print(f"  异步模式:   {SOCKETIO_ASYNC_MODE}")
    if host == "127.0.0.1":
        print("  [提示] HOST=127.0.0.1 只允许本机访问，别人连不上；")
        print("         要对外开放请设置 HOST=0.0.0.0 并放行防火墙端口。")
    if debug:
        print("  [警告] FARM_DEBUG=1 会暴露调试器，对外开放前必须设为 0！")
    print(line)
    print("  停止服务：本窗口按 Ctrl+C，或运行 stop_server.bat")
    print(line)
    print(flush=True)


def main(argv=None) -> int:
    """启动生产服务，返回进程退出码。"""
    argv = sys.argv[1:] if argv is None else argv
    host = get_host()
    port = get_port()
    debug = get_debug()

    app, socketio, hooks = load_app()
    run_init_hooks(hooks)

    # 让 SocketIO 走多线程 WSGI 模式，保证 MQTT 后台线程 emit 可用。
    try:
        socketio.init_app(app, async_mode=SOCKETIO_ASYNC_MODE, cors_allowed_origins="*")
    except Exception as exc:  # noqa: BLE001 - 重复初始化等场景不致命
        print(f"[提示] socketio.init_app 跳过：{exc}")

    lan_ips = list_lan_ips()
    print_banner(host, port, debug, lan_ips)

    try:
        from waitress import serve
    except ImportError:
        print("[警告] 未安装 waitress，回退到 Werkzeug 内置服务器（仅限临时使用）！")
        print("[警告] 请执行：pip install -r requirements.txt")
        socketio.run(
            app,
            host=host,
            port=port,
            debug=debug,
            allow_unsafe_werkzeug=True,
        )
        return 0

    print(f"[启动] waitress 正在监听 {host}:{port}（多线程 WSGI）...", flush=True)
    # threads 默认 4，校园网小规模访问足够；MQTT 回调走独立线程不受影响。
    serve(app, host=host, port=port, threads=int(os.environ.get("FARM_THREADS", "8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
