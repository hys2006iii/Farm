# -*- coding: utf-8 -*-
"""部署相关单元测试：启动器环境变量解析、局域网 IP 枚举、.env 生成。

说明：本文件**不依赖** tests/conftest.py，自行管理临时目录与 monkeypatch，
以便与 architect 的应用工厂测试并行开发、互不干扰。
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import server  # noqa: E402  (需要上面的 sys.path 处理)

# 动态加载 tools/gen_secret.py（tools 不是包，没有 __init__.py）
_gen_secret_path = os.path.join(PROJECT_ROOT, "tools", "gen_secret.py")
_spec = importlib.util.spec_from_file_location("qinghe_gen_secret", _gen_secret_path)
gen_secret = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_secret)


# ---------------------------------------------------------------------------
# 一、环境变量解析
# ---------------------------------------------------------------------------

class TestEnvParsing:
    """HOST / PORT / FARM_DEBUG 的解析规则。"""

    def test_defaults_when_env_empty(self):
        """全部缺省时：0.0.0.0 / 5000 / 关闭调试。"""
        assert server.get_host({}) == "0.0.0.0"
        assert server.get_port({}) == 5000
        assert server.get_debug({}) is False

    def test_host_override_and_blank_fallback(self):
        """HOST 可覆盖；空字符串/纯空格回退到默认值。"""
        assert server.get_host({"HOST": "0.0.0.0"}) == "0.0.0.0"
        assert server.get_host({"HOST": "192.168.1.10"}) == "192.168.1.10"
        assert server.get_host({"HOST": "   "}) == "0.0.0.0"
        assert server.get_host({"HOST": " 10.0.0.5 "}) == "10.0.0.5"

    def test_port_override(self):
        """PORT 支持任意合法端口。"""
        assert server.get_port({"PORT": "5098"}) == 5098
        assert server.get_port({"PORT": " 8080 "}) == 8080
        assert server.get_port({"PORT": "1"}) == 1
        assert server.get_port({"PORT": "65535"}) == 65535

    @pytest.mark.parametrize("bad", ["abc", "", "  ", "70000", "0", "-1", "50.5"])
    def test_port_invalid_falls_back(self, bad):
        """非法 PORT（非数字/越界）回退到 5000，不抛异常。"""
        assert server.get_port({"PORT": bad}) == 5000

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", " y "])
    def test_debug_truthy(self, raw):
        """常见真值写法都识别为开启调试。"""
        assert server.get_debug({"FARM_DEBUG": raw}) is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "", "  ", "2"])
    def test_debug_falsy(self, raw):
        """0/空值/未知值一律按关闭处理（对外开放必须为 0）。"""
        assert server.get_debug({"FARM_DEBUG": raw}) is False

    def test_defaults_read_real_environ(self, monkeypatch):
        """不传参时读取 os.environ。"""
        monkeypatch.setenv("HOST", "10.113.158.198")
        monkeypatch.setenv("PORT", "5098")
        monkeypatch.setenv("FARM_DEBUG", "0")
        assert server.get_host() == "10.113.158.198"
        assert server.get_port() == 5098
        assert server.get_debug() is False


# ---------------------------------------------------------------------------
# 二、局域网 IP 过滤与排序
# ---------------------------------------------------------------------------

class TestLanIpFiltering:
    """is_usable_lan_ip 的过滤规则。"""

    @pytest.mark.parametrize(
        "ip",
        ["10.113.158.198", "192.168.1.20", "172.16.5.9", "172.31.255.254", "100.64.3.4"],
    )
    def test_accepts_lan_ips(self, ip):
        """校园网/私网地址应被接受。"""
        assert server.is_usable_lan_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",        # 回环
            "127.5.5.5",        # 回环网段
            "169.254.13.7",     # APIPA 链路本地
            "0.0.0.0",          # 未指定
            "224.0.0.1",        # 组播
            "not-an-ip",        # 非法
            "",                 # 空
            "::1",              # IPv6 回环（非 IPv4）
            "240.0.0.1",        # 保留
        ],
    )
    def test_rejects_unusable_ips(self, ip):
        """回环 / APIPA / 非法地址必须被过滤掉，避免把错误地址发给同学。"""
        assert server.is_usable_lan_ip(ip) is False

    def test_list_lan_ips_filters_and_dedupes(self):
        """候选列表去重 + 过滤，且 10.x 优先排在最前。"""
        candidates = [
            "127.0.0.1",
            "169.254.13.7",
            "192.168.1.20",
            "10.113.158.198",
            "10.113.158.198",   # 重复
            "0.0.0.0",
            "garbage",
        ]
        assert server.list_lan_ips(candidates) == ["10.113.158.198", "192.168.1.20"]

    def test_list_lan_ips_sort_order(self):
        """排序优先级：10.x → 172.16-31.x → 192.168.x → 其他。"""
        candidates = ["192.168.0.9", "8.8.8.8", "172.20.1.1", "10.1.1.1"]
        assert server.list_lan_ips(candidates) == [
            "10.1.1.1",
            "172.20.1.1",
            "192.168.0.9",
            "8.8.8.8",
        ]

    def test_list_lan_ips_empty_when_only_loopback(self):
        """只有回环时应返回空列表（启动横幅会提示未检测到局域网 IP）。"""
        assert server.list_lan_ips(["127.0.0.1", "169.254.1.1"]) == []

    def test_list_lan_ips_uses_socket_when_no_candidates(self, monkeypatch):
        """不传候选时走 socket 枚举；monkeypatch 伪造网卡返回值。"""

        class FakeSock:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, addr):
                return None

            def getsockname(self):
                return ("10.113.158.198", 54321)

            def close(self):
                return None

        monkeypatch.setattr(server.socket, "socket", lambda *a, **k: FakeSock())
        monkeypatch.setattr(
            server.socket,
            "getaddrinfo",
            lambda *a, **k: [
                (2, 1, 6, "", ("127.0.0.1", 0)),
                (2, 1, 6, "", ("192.168.31.77", 0)),
            ],
        )
        assert server.list_lan_ips() == ["10.113.158.198", "192.168.31.77"]

    def test_list_lan_ips_survives_socket_errors(self, monkeypatch):
        """socket 异常时不能崩溃，退化为空列表。"""

        def boom(*args, **kwargs):
            raise OSError("no network")

        monkeypatch.setattr(server.socket, "socket", boom)
        monkeypatch.setattr(server.socket, "getaddrinfo", boom)
        assert server.list_lan_ips() == []


# ---------------------------------------------------------------------------
# 三、启动横幅
# ---------------------------------------------------------------------------

class TestBanner:
    """启动横幅必须打印可直接复制给同学的访问地址。"""

    def test_banner_contains_all_addresses(self, capsys):
        server.print_banner("0.0.0.0", 5098, False, ["10.113.158.198", "192.168.1.5"])
        out = capsys.readouterr().out
        assert "青禾智灌服务已启动" in out
        assert "http://127.0.0.1:5098" in out
        assert "http://10.113.158.198:5098" in out
        assert "http://192.168.1.5:5098" in out
        assert "把这个地址发给同学" in out
        assert "0.0.0.0:5098" in out

    def test_banner_warns_on_loopback_and_debug(self, capsys):
        """HOST 只绑本机 / 开着调试器时都要给出警告。"""
        server.print_banner("127.0.0.1", 5000, True, [])
        out = capsys.readouterr().out
        assert "别人连不上" in out
        assert "FARM_DEBUG=1" in out
        assert "未检测到局域网 IP" in out


# ---------------------------------------------------------------------------
# 四、.env 生成逻辑
# ---------------------------------------------------------------------------

class TestGenSecret:
    """tools/gen_secret.py 的密钥生成与不覆盖策略。"""

    def test_generate_secret_length_and_uniqueness(self):
        """token_urlsafe(48) 长度约 64，且两次生成不重复。"""
        a = gen_secret.generate_secret()
        b = gen_secret.generate_secret()
        assert a != b
        assert len(a) >= 60
        assert all(c.isalnum() or c in "-_" for c in a)

    def test_write_env_creates_file(self, tmp_path):
        """首次写入应创建 .env 并包含密钥行。"""
        env_path = tmp_path / ".env"
        secret = "unit-test-secret"
        assert gen_secret.write_env(secret, str(env_path)) is True
        content = env_path.read_text(encoding="utf-8")
        assert f"FARM_SECRET_KEY={secret}" in content

    def test_write_env_does_not_overwrite_existing(self, tmp_path):
        """已有 .env 时默认不覆盖（避免换掉正在使用的会话密钥）。"""
        env_path = tmp_path / ".env"
        env_path.write_text("FARM_SECRET_KEY=old-secret\n", encoding="utf-8")
        assert gen_secret.write_env("new-secret", str(env_path)) is False
        assert env_path.read_text(encoding="utf-8") == "FARM_SECRET_KEY=old-secret\n"

    def test_write_env_force_overwrites(self, tmp_path):
        """显式 --force 时才覆盖。"""
        env_path = tmp_path / ".env"
        env_path.write_text("FARM_SECRET_KEY=old-secret\n", encoding="utf-8")
        assert gen_secret.write_env("new-secret", str(env_path), force=True) is True
        assert "FARM_SECRET_KEY=new-secret" in env_path.read_text(encoding="utf-8")

    def test_main_skips_existing_without_force(self, tmp_path, monkeypatch, capsys):
        """main() 在 .env 已存在且未加 --force 时跳过，返回码 0。"""
        env_path = tmp_path / ".env"
        env_path.write_text("FARM_SECRET_KEY=old\n", encoding="utf-8")
        monkeypatch.setattr(gen_secret, "ENV_PATH", str(env_path))
        assert gen_secret.main([]) == 0
        assert "未覆盖" in capsys.readouterr().out
        assert env_path.read_text(encoding="utf-8") == "FARM_SECRET_KEY=old\n"

    def test_main_writes_when_missing(self, tmp_path, monkeypatch):
        """main() 在 .env 缺失时生成随机密钥。"""
        env_path = tmp_path / ".env"
        monkeypatch.setattr(gen_secret, "ENV_PATH", str(env_path))
        assert gen_secret.main([]) == 0
        content = env_path.read_text(encoding="utf-8")
        assert "FARM_SECRET_KEY=" in content
        assert "请替换为随机长字符串" not in content

    def test_env_example_contains_all_keys(self):
        """.env.example 必须覆盖 AGENTS.md 约定的全部环境变量。"""
        path = os.path.join(PROJECT_ROOT, ".env.example")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        for key in ("FARM_SECRET_KEY", "FARM_DB_PATH", "HOST", "PORT", "FARM_DEBUG"):
            assert key in text, f".env.example 缺少 {key}"

    def test_gitignore_ignores_env(self):
        """.env 必须被 .gitignore 忽略，防止密钥入库。"""
        path = os.path.join(PROJECT_ROOT, ".gitignore")
        with open(path, "r", encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh]
        assert ".env" in lines


# ---------------------------------------------------------------------------
# 五、部署脚本存在性与关键内容
# ---------------------------------------------------------------------------

class TestDeployScripts:
    """一键脚本必须存在，且关键安全约束不能被删掉。"""

    @pytest.mark.parametrize(
        "name",
        ["start_server.bat", "stop_server.bat", "firewall_allow.bat", "run.bat", "requirements.txt"],
    )
    def test_file_exists(self, name):
        assert os.path.isfile(os.path.join(PROJECT_ROOT, name)), f"缺少部署文件 {name}"

    def test_start_server_sets_debug_off(self):
        """start_server.bat 必须把 FARM_DEBUG 设为 0。"""
        text = open(os.path.join(PROJECT_ROOT, "start_server.bat"), encoding="utf-8").read()
        assert "set FARM_DEBUG=0" in text
        assert "server.py" in text

    def test_run_bat_sets_debug_on(self):
        """run.bat 是本地调试入口，FARM_DEBUG=1。"""
        text = open(os.path.join(PROJECT_ROOT, "run.bat"), encoding="utf-8").read()
        assert "set FARM_DEBUG=1" in text
        assert "app.py" in text

    def test_firewall_script_checks_admin(self):
        """防火墙脚本必须先检测管理员权限，并给出右键以管理员身份运行的提示。"""
        text = open(os.path.join(PROJECT_ROOT, "firewall_allow.bat"), encoding="utf-8").read()
        assert "net session" in text
        assert "以管理员身份运行" in text
        assert "netsh advfirewall firewall add rule" in text
        assert "localport=%PORT%" in text

    def test_stop_script_prints_pid_before_kill(self):
        """stop_server.bat 必须先打印 PID 并等待确认，不能盲杀。"""
        text = open(os.path.join(PROJECT_ROOT, "stop_server.bat"), encoding="utf-8").read()
        assert "netstat -ano" in text
        assert "taskkill" in text
        assert "确认结束该进程吗" in text
        # 确认提示必须出现在 taskkill 之前
        assert text.index("确认结束该进程吗") < text.index("taskkill")

    def test_requirements_include_deploy_deps(self):
        """依赖清单必须包含 waitress 与 pytest。"""
        text = open(os.path.join(PROJECT_ROOT, "requirements.txt"), encoding="utf-8").read().lower()
        for pkg in ("flask", "flask-socketio", "pyjwt", "paho-mqtt", "requests", "waitress", "pytest"):
            assert pkg in text, f"requirements.txt 缺少 {pkg}"

    def test_server_uses_threading_async_mode(self):
        """必须使用 threading async_mode（MQTT 后台线程 emit 的前提）。"""
        assert server.SOCKETIO_ASYNC_MODE == "threading"
        text = open(os.path.join(PROJECT_ROOT, "server.py"), encoding="utf-8").read()
        assert "from waitress import serve" in text
        assert "allow_unsafe_werkzeug=True" in text


# ---------------------------------------------------------------------------
# 六、应用加载（兼容重构前后）
# ---------------------------------------------------------------------------

class TestLoadApp:
    """load_app() 必须能在重构前后两种形态下拿到 app 与 socketio。"""

    def test_load_app_returns_triple(self):
        app, socketio, hooks = server.load_app()
        assert app is not None
        assert socketio is not None
        assert hasattr(app, "test_client")
        assert isinstance(hooks, list)

    def test_loaded_app_serves_index(self):
        """装配出的应用应能响应根路径（重定向到登录页也算通过）。"""
        app, _socketio, _hooks = server.load_app()
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code in (200, 302, 401)
