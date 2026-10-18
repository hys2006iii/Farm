"""青禾智灌 —— 外部设备联调客户端（**不在系统内体现测试功能**）。

定位
----
本脚本是仓库**外部**的联调/压测工具：它以"设备身份"把遥测直接喂给
`qinghe.iot.ingest_telemetry()`，走的是与真实 ESP32-E 上报**完全相同**的
链路（历史落库 / 心跳 / RORI / 泵时长 / 自动调控 / 告警 / 前端推送），
但**不依赖任何系统内的测试接口**——服务端不暴露 `/api/dev/*`。

两种用法
--------
1) 本机直连（默认，推荐）：直接在本机进程内灌数，需要能读到同一个数据库。

       python tools/simulate_device.py --scenario anaerobic --samples 24
       python tools/simulate_device.py --username farmer01 --repeat 30 --sleep 10

2) 远端 HTTP（`--base-url`）：不碰数据库，改用**系统已经对外开放的正式接口**
   `POST /api/app_send_command` 无法上报遥测，因此远端模式只做"登录 + 参数回显"
   的自检，不灌数。真正要往远端服务灌遥测，请让远端以相同账号运行本脚本，
   或接入真实设备 / MQTT Broker。

退出码：0 成功；2 可预期的失败（参数、登录、数据库）；130 被 Ctrl+C 中断。
"""

import argparse
import os
import sys

# 允许从仓库根目录直接运行（tools/ 不是包）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台默认 GBK，打印中文与单位符号会 UnicodeEncodeError，这里强制 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from qinghe import simulate  # noqa: E402  (需要上面的 sys.path 处理)

DEFAULT_USERNAME = 'farmer01'
DEFAULT_PASSWORD = 'secret123'


class SimulatorError(RuntimeError):
    """命令行可预期的失败（参数、账号、数据库）。"""


def _resolve_uid(username: str) -> int:
    """按用户名取用户 id；不存在则抛 SimulatorError（附可执行的提示）。"""
    from qinghe.db import get_db

    with get_db() as conn:
        row = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if row is None:
        raise SimulatorError(
            '账号 %s 不存在。先在网页上注册该账号，或用 --username 指定已有账号。' % username
        )
    return int(row['id'])


def _verify_login(username: str, password: str) -> None:
    """用同一套口令校验逻辑核对账号密码，避免灌数到别人的地块。"""
    from qinghe import auth
    from qinghe.db import get_db

    with get_db() as conn:
        row = conn.execute(
            'SELECT id, password FROM users WHERE username = ?', (username,)
        ).fetchone()
    if row is None:
        raise SimulatorError('账号 %s 不存在。' % username)
    if not auth.verify_password(row['password'], password):
        raise SimulatorError('账号 %s 的密码不正确。' % username)


def run_local(args) -> int:
    """本机直连模式：按场景灌数到指定账号，返回退出码。"""
    from qinghe import config, iot

    _verify_login(args.username, args.password)
    uid = _resolve_uid(args.username)

    print('数据库：%s' % config.get_db_path())
    print('账号：%s（uid=%s）' % (args.username, uid))
    print('开始注入：场景 %s，%d 条/轮，间隔 %ds，共 %d 轮'
          % (args.scenario, args.samples, args.interval, max(1, args.repeat)))

    for round_index in range(max(1, args.repeat)):
        result = simulate.run_simulation(
            uid, args.scenario, samples=args.samples, interval=args.interval, emit=args.emit
        )
        print('  第 %d 轮：%s，采样 %s 条，时间窗 %s → %s'
              % (round_index + 1, simulate.SCENARIO_META[result['scenario']]['name'],
                 result['samples'], result['first_ts'], result['last_ts']))
        if round_index + 1 < max(1, args.repeat):
            import time

            time.sleep(max(0.0, args.sleep))
    return 0


def run_remote(args) -> int:
    """远端模式：只做连通性与账号自检（远端不提供测试接口）。"""
    import json
    import urllib.error
    import urllib.request

    url = args.base_url.rstrip('/') + '/api/login'
    payload = json.dumps({'username': args.username, 'password': args.password}).encode('utf-8')
    req = urllib.request.Request(
        url, data=payload, headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode('utf-8', errors='replace') or '{}')
    except urllib.error.HTTPError as err:
        raise SimulatorError('远端登录失败（HTTP %s）。' % err.code) from None
    except urllib.error.URLError as err:
        raise SimulatorError('连不上 %s（%s）。' % (args.base_url, err.reason)) from None
    if not isinstance(body, dict) or body.get('status') != 'success':
        raise SimulatorError('远端登录失败：%s' % (body.get('message') if isinstance(body, dict) else body))
    print('远端 %s 连通，账号 %s 可登录。' % (args.base_url, args.username))
    print('提示：远端模式只做连通性自检；往远端灌遥测请在远端主机上运行本脚本，或接入真实设备。')
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description='青禾智灌外部设备联调工具：把带物理合理性的遥测灌进指定账号。'
    )
    parser.add_argument('--username', default=DEFAULT_USERNAME, help='账号（默认 farmer01）')
    parser.add_argument('--password', default=DEFAULT_PASSWORD, help='密码')
    parser.add_argument('--scenario', default='normal',
                        choices=list(simulate.SCENARIOS),
                        help='场景：normal 常规 / drought 干旱 / anaerobic 缺氧 / storm 强降雨')
    parser.add_argument('--samples', type=int, default=24, help='每轮采样条数（1–240）')
    parser.add_argument('--interval', type=int, default=60, help='相邻采样间隔（秒）')
    parser.add_argument('--repeat', type=int, default=1, help='重复轮数')
    parser.add_argument('--sleep', type=float, default=5.0, help='轮次之间的等待秒数')
    parser.add_argument('--no-emit', action='store_true',
                        help='不向在线页面推送（离线灌数时更安静）')
    parser.add_argument('--base-url', default='', help='远端模式：只做登录自检，例如 http://10.0.0.5:5000')
    parser.add_argument('--list', action='store_true', help='只列出场景后退出')
    return parser


def main(argv=None) -> int:
    """命令行入口，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    args.emit = False if args.no_emit else None

    if args.list:
        for item in simulate.describe_scenarios():
            print('%-10s %s' % (item['key'], item['name']))
        return 0

    try:
        if args.base_url:
            return run_remote(args)
        return run_local(args)
    except SimulatorError as err:
        print('失败：%s' % err, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('已中断', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
