"""青禾智灌 —— 设备模拟器命令行（无实物主板时替代 ESP32-E）。

它不连 MQTT、不碰数据库，只是以「设备身份」向运行中的服务端灌数：
登录拿会话 → 调 `POST /api/dev/simulate` → 服务端走与真实上报相同的链路
（历史落库 / 心跳 / RORI / 泵时长 / 自动调控 / 告警 / 前端推送）。

前置条件：服务端以 `FARM_DEV_SIM=1` 启动，否则接口返回 404。

用法示例::

    # 灌 24 条「暴雨积水缺氧」数据（默认 60 秒间隔，覆盖最近 24 分钟）
    python tools/simulate_device.py --scenario anaerobic

    # 每 10 秒灌 1 条常规数据，连续 30 轮（演示实时曲线滚动）
    python tools/simulate_device.py --scenario normal --samples 1 --repeat 30 --sleep 10

    # 指向校园网/局域网的服务
    python tools/simulate_device.py --base-url http://10.113.158.198:5000 --scenario drought
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = 'http://127.0.0.1:5000'
SCENARIO_CHOICES = ('normal', 'drought', 'anaerobic', 'storm')


class SimulatorError(RuntimeError):
    """命令行可预期的失败（网络、认证、接口错误）。"""


class Session:
    """极简 HTTP 会话：复用 Cookie（服务端用 Flask session 鉴权）。"""

    def __init__(self, base_url, timeout=15):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.cookie = ''

    def request(self, method, path, payload=None):
        """发一个 JSON 请求，返回 (status_code, parsed_json)。"""
        url = self.base_url + path
        data = None
        headers = {'Accept': 'application/json'}
        if payload is not None:
            data = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if self.cookie:
            headers['Cookie'] = self.cookie
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode('utf-8', errors='replace')
                self._store_cookie(resp.headers)
                return resp.status, _parse_json(body)
        except urllib.error.HTTPError as err:
            body = err.read().decode('utf-8', errors='replace')
            self._store_cookie(err.headers)
            return err.code, _parse_json(body)
        except urllib.error.URLError as err:
            raise SimulatorError(
                '连不上服务端 %s（%s）。先启动 server.py，并确认 FARM_DEV_SIM=1。'
                % (self.base_url, err.reason)
            ) from None

    def _store_cookie(self, headers):
        """把 Set-Cookie 里的 session 记下来。"""
        raw = headers.get('Set-Cookie') if headers else None
        if not raw:
            return
        for part in raw.split(';'):
            part = part.strip()
            if part.startswith('session='):
                self.cookie = part
                return

    def login(self, username, password):
        """登录；失败抛 SimulatorError（带服务端原话）。"""
        status, body = self.request(
            'POST', '/api/login', {'username': username, 'password': password}
        )
        if status != 200 or not isinstance(body, dict) or body.get('status') != 'success':
            message = body.get('message') if isinstance(body, dict) else body
            raise SimulatorError('登录失败（HTTP %s）：%s' % (status, message))
        return body

    def scenarios(self):
        """取可用场景列表。"""
        status, body = self.request('GET', '/api/dev/scenarios')
        if status == 404:
            raise SimulatorError(
                '服务端未开启模拟器：请用 FARM_DEV_SIM=1 启动（开发/演示环境才需要）。'
            )
        if status != 200:
            raise SimulatorError('场景列表获取失败（HTTP %s）：%s' % (status, body))
        return body.get('scenarios') or []

    def simulate(self, scenario, samples, interval):
        """灌入一段模拟数据。"""
        status, body = self.request('POST', '/api/dev/simulate', {
            'scenario': scenario,
            'samples': samples,
            'interval': interval,
        })
        if status == 404:
            raise SimulatorError('服务端未开启模拟器（FARM_DEV_SIM=1 才开放）。')
        if status != 200:
            message = body.get('message') if isinstance(body, dict) else body
            raise SimulatorError('注数失败（HTTP %s）：%s' % (status, message))
        return body


def _parse_json(text):
    """尽力把响应体解析成 dict，非 JSON 时返回原文本。"""
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return text


def build_parser():
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description='青禾智灌设备模拟器：给运行中的服务端灌入模拟遥测。'
    )
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL, help='服务端地址')
    parser.add_argument('--username', required=True, help='账号')
    parser.add_argument('--password', required=True, help='密码')
    parser.add_argument('--scenario', default='normal', choices=SCENARIO_CHOICES,
                        help='场景：normal 常规 / drought 干旱 / anaerobic 缺氧 / storm 强降雨')
    parser.add_argument('--samples', type=int, default=24, help='每次灌入的采样条数')
    parser.add_argument('--interval', type=int, default=60,
                        help='相邻采样的时间间隔（秒）')
    parser.add_argument('--repeat', type=int, default=1, help='重复轮数')
    parser.add_argument('--sleep', type=float, default=5.0,
                        help='重复轮次之间的等待秒数')
    parser.add_argument('--list', action='store_true', help='只列出场景后退出')
    return parser


def main(argv=None):
    """命令行入口，返回进程退出码。"""
    args = build_parser().parse_args(argv)
    session = Session(args.base_url)
    try:
        session.login(args.username, args.password)
        if args.list:
            for item in session.scenarios():
                print('%-10s %s' % (item['key'], item['name']))
            return 0
        print('已登录 %s，开始注入（场景 %s，%d 条/轮，间隔 %ds，共 %d 轮）'
              % (args.base_url, args.scenario, args.samples, args.interval, args.repeat))
        for round_index in range(max(1, args.repeat)):
            result = session.simulate(args.scenario, args.samples, args.interval)
            print('  第 %d 轮：%s，采样 %s 条，时间窗 %s → %s'
                  % (round_index + 1, result.get('scenario_name'),
                     result.get('samples'), result.get('first_ts'),
                     result.get('last_ts')))
            if round_index + 1 < args.repeat:
                time.sleep(max(0.0, args.sleep))
    except SimulatorError as err:
        print('失败：%s' % err, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('已中断', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
