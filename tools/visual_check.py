"""青禾智灌 —— 最终验收：起真实服务 + headless Edge 截图与控制台检查。

用途：本轮 UI 改动（登录页水尺、系统设置分组、阈值滑块区间、两列卡片对齐、
气泵/水泵顺序、文案删改）在 pytest 里只能做静态契约断言，渲染结果必须在真实
浏览器里核对。本脚本用 CDP 驱动 headless Edge：

1. 起一个临时库的服务进程（waitress/werkzeug 均可）；
2. 注册 + 登录，进入看板、系统设置、智能洞察、知识库各截一张图；
3. 采集控制台 error 与失败请求，最后打印汇总。

用法::

    python tools/visual_check.py                 # 全部检查
    python tools/visual_check.py --port 5099

退出码 0 = 无控制台错误且关键元素齐全；1 = 有失败项。
"""

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EDGE_CANDIDATES = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
)

USERNAME = 'visualcheck'
PASSWORD = 'visualcheck123'


class CheckError(RuntimeError):
    """可预期的验收失败。"""


def find_edge() -> str:
    """定位 Edge 可执行文件。"""
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    found = shutil.which('msedge')
    if found:
        return found
    raise CheckError('未找到 Microsoft Edge，无法做浏览器验收')


def free_port(preferred: int) -> int:
    """返回一个当前空闲的端口号。

    `preferred=0` 不能直接返回：CDP 的 `--remote-debugging-port=0` 会让浏览器
    自己随机选端口，调用方无从得知，轮询必然超时。这里统一由 OS 分配后取回实际端口。
    """
    def _probe(port: int):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', port))
            return sock.getsockname()[1]

    if preferred:
        try:
            return _probe(preferred)
        except OSError:
            pass
    return _probe(0)


def wait_http(url: str, timeout: float = 25.0) -> None:
    """轮询直到服务端返回任意 HTTP 响应。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except urllib.error.HTTPError:
            return
        except Exception as exc:  # noqa: BLE001 - 服务尚未起来，继续等
            last = exc
            time.sleep(0.4)
    raise CheckError('服务端未在 %.0fs 内就绪：%s' % (timeout, last))


class Browser:
    """极简 CDP 客户端（只用到 Page / Runtime / Network 三个域）。

    单线程收发，但**任何等待都必须边等边排空事件**。
    CDP 的事件（网络请求、控制台、异常…）会源源不断推过来，若我们只是
    `time.sleep()` 不读 socket，接收缓冲区会被填满，Chromium 的发送端随之阻塞，
    之后的命令（尤其 `Page.captureScreenshot`）永远等不到响应。
    看板页加载 Chart.js/Socket.IO 时事件量远大于登录页，正是这个现象只在看板复现。

    也不用「常驻读线程 + 主线程发送」的写法：websocket-client 的 `recv()`
    在等待数据期间会一直持有内部 `self.lock`，主线程的 `send()` 会因此永久阻塞。
    """

    def __init__(self, edge: str, port: int, profile: str):
        self.port = port
        self.profile = profile
        self.proc = subprocess.Popen(
            [edge, '--headless=new', '--disable-gpu', '--no-first-run',
             '--no-default-browser-check', '--disable-extensions', '--disable-sync',
             '--disable-background-networking', '--disable-component-update',
             '--remote-debugging-port=%d' % port,
             # Chromium 111+ 默认拒绝带 Origin 的 WebSocket 连接，需显式放行
             '--remote-allow-origins=*',
             '--user-data-dir=%s' % profile,
             '--window-size=1600,1200', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.ws = None
        self._msg_id = 0
        self._events = []

    def connect(self, timeout: float = 30.0) -> None:
        """等 CDP 端点就绪并建立 WebSocket。

        `/json/list` 里混着 Edge 自己的内部页（同步提示、扩展后台页…），
        必须挑一个 url 是 `about:blank`/`http(s)` 的真实页面，否则会把
        `edge://sync-confirmation-dialog/` 当成被控页面，后续导航全部无效。
        """
        import websocket  # 延迟导入，缺依赖时给出可读报错

        deadline = time.time() + timeout
        target = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        'http://127.0.0.1:%d/json/list' % self.port, timeout=2) as resp:
                    items = json.loads(resp.read().decode('utf-8'))
                pages = [
                    item for item in items
                    if item.get('type') == 'page'
                    and str(item.get('url', '')).startswith(('about:blank', 'http'))
                ]
                if pages:
                    target = pages[0]
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        if target is None:
            raise CheckError('Edge 调试端口 %d 未就绪（浏览器可能启动失败）' % self.port)
        self.ws = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=60)
        self.call('Page.enable')
        self.call('Runtime.enable')
        self.call('Network.enable')

    def _pump(self, seconds: float) -> None:
        """在 `seconds` 内持续读 socket，事件入 `_events`（顺便让浏览器发送端畅通）。

        用很短的 socket 超时轮询：既能把事件及时排空，又不会让我们长时间离开
        发送路径。
        """
        deadline = time.time() + max(0.0, seconds)
        self.ws.settimeout(0.05)
        try:
            while True:
                remain = deadline - time.time()
                if remain <= 0:
                    return
                try:
                    self._events.append(json.loads(self.ws.recv()))
                except Exception:  # noqa: BLE001 - 读超时属正常，继续轮询
                    if self.ws.sock is None:
                        return
        finally:
            self.ws.settimeout(60)

    def call(self, method: str, params: dict = None, timeout: float = 60.0):
        """发一条 CDP 命令并等它的响应（等的过程同样持续排空事件）。"""
        self._msg_id += 1
        msg_id = self._msg_id
        self.ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
        deadline = time.time() + timeout
        self.ws.settimeout(0.05)
        try:
            while time.time() < deadline:
                try:
                    data = json.loads(self.ws.recv())
                except Exception:  # noqa: BLE001
                    if self.ws.sock is None:
                        raise CheckError('CDP 连接已断开（%s）' % method) from None
                    continue
                if data.get('id') == msg_id:
                    if 'error' in data:
                        raise CheckError('%s 失败：%s' % (method, data['error']))
                    return data.get('result')
                if data.get('method'):
                    self._events.append(data)
        finally:
            self.ws.settimeout(60)
        raise CheckError('%s 响应超时（%.0fs）' % (method, timeout))

    def drain(self) -> list:
        """取走并清空已积累的事件。"""
        events, self._events = self._events, []
        return events

    def goto(self, url: str, settle: float = 2.5) -> list:
        """导航并收集这段时间内的事件。"""
        self.call('Page.navigate', {'url': url})
        self._pump(settle)
        return self.drain()

    def evaluate(self, expression: str):
        """在页面里执行表达式并返回 JSON 值。"""
        result = self.call('Runtime.evaluate', {
            'expression': expression, 'returnByValue': True, 'awaitPromise': True,
        })
        if result.get('exceptionDetails'):
            details = result['exceptionDetails']
            raise CheckError('页面脚本异常：%s' % (
                (details.get('exception') or {}).get('description') or details.get('text')))
        return result.get('result', {}).get('value')

    def wait(self, seconds: float) -> None:
        """等待若干秒，期间持续排空事件（避免浏览器发送端被堵住）。"""
        self._pump(seconds)

    def screenshot(self, path: str) -> bool:
        """视口截图落盘，返回是否成功（截图失败不算验收失败）。

        - 不用 `captureBeyondViewport`：新版 headless 里它经常卡住不返回；
        - 默认走合成器（`fromSurface` 缺省 True）才能拿到完整画面；
          `fromSurface=False` 只取渲染器主帧，CSS 背景等合成层会缺失，截出来是空白。
          若合成器因地图瓦片不可达而卡住，再退回 `fromSurface=False` 兜底。

        截图是给人看的辅助产物，**任何失败都只告警、不中断验收**；
        真正的验收靠下面的 DOM 断言。
        """
        attempts = (
            {'format': 'png'},
            {'format': 'png', 'fromSurface': False},
        )
        for params in attempts:
            try:
                result = self.call('Page.captureScreenshot', params, timeout=15.0)
            except CheckError:
                continue
            try:
                with open(path, 'wb') as fh:
                    fh.write(base64.b64decode(result['data']))
                return True
            except (KeyError, TypeError):
                continue
        print('  [警告] 截图失败（已跳过）：%s' % os.path.basename(path), flush=True)
        return False

    def close(self) -> None:
        """关闭浏览器进程。"""
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def http_login(base: str, username: str, password: str) -> str:
    """用 Python 侧的 HTTP 会话登录，返回 `session` Cookie 的值。

    走真实接口而不是在页面里跑 handleLogin()：后者成功后页面会自行跳转，
    与脚本后续的 `Page.navigate` 竞争，是"截图永远不返回"的根因。
    """
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({'username': username, 'password': password}).encode('utf-8')
    req = urllib.request.Request(base + '/api/login', data=body,
                                 headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    if payload.get('status') != 'success':
        raise CheckError('登录失败：%s' % payload.get('message'))
    for cookie in jar:
        if cookie.name == 'session':
            return cookie.value
    raise CheckError('登录成功但未拿到 session Cookie')


def collect_errors(events: list) -> list:
    """从 CDP 事件里挑出控制台 error 与失败请求。"""
    problems = []
    for event in events:
        method = event.get('method')
        params = event.get('params') or {}
        if method == 'Runtime.exceptionThrown':
            detail = params.get('exceptionDetails') or {}
            problems.append('未捕获异常：%s' % (detail.get('text') or detail))
        elif method == 'Runtime.consoleAPICalled' and params.get('type') == 'error':
            text = ' '.join(str(a.get('value', a.get('description', '')))
                            for a in params.get('args') or [])
            problems.append('console.error：%s' % text[:200])
        elif method == 'Network.loadingFailed':
            problems.append('请求失败：%s %s' % (params.get('type'), params.get('errorText')))
    return problems


def run(args) -> int:
    """执行完整验收，返回退出码。"""
    import websocket  # noqa: F401 - 仅探测依赖是否可用

    edge = find_edge()
    port = free_port(args.port)
    base = 'http://127.0.0.1:%d' % port
    out_dir = os.path.join(ROOT, 'docs', '_shots')
    os.makedirs(out_dir, exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix='qinghe_visual_')
    env = dict(os.environ)
    env.update({
        'FARM_DB_PATH': os.path.join(tmpdir, 'visual.db'),
        'FARM_SECRET_KEY': 'visual_check_secret_key_0123456789abcdef',
        'FARM_DEBUG': '0',
        'PORT': str(port),
        'HOST': '127.0.0.1',
        'PYTHONIOENCODING': 'utf-8',
    })

    print('启动服务 %s（临时库 %s）...' % (base, env['FARM_DB_PATH']))
    # 用 server.py（waitress 多线程 WSGI）而不是 app.py 的 Werkzeug 开发服务器：
    # 看板页有 SocketIO 长轮询，开发服务器线程数有限，容易被长连接占满而让
    # 后续页面请求排队，表现为浏览器侧命令迟迟不返回。同时也更贴近生产形态。
    server = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    results = []
    try:
        wait_http(base + '/')
        # 注册一个验收账号
        body = json.dumps({'username': USERNAME, 'password': PASSWORD}).encode()
        req = urllib.request.Request(base + '/api/register', data=body,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200, '注册失败'

        profile = tempfile.mkdtemp(prefix='qinghe_edge_')
        browser = Browser(edge, free_port(0), profile)
        browser.connect()

        # 1) 登录页：水尺标尺
        events = browser.goto(base + '/')
        problems = collect_errors(events)
        gauge = browser.evaluate("""(() => {
            const g = document.querySelector('.gauge');
            const wrap = document.querySelector('.gauge-wrap');
            if (!g) return null;
            const r = g.getBoundingClientRect();
            const pr = document.querySelector('.brand-panel').getBoundingClientRect();
            return {w: Math.round(r.width), h: Math.round(r.height),
                    panelH: Math.round(pr.height), ratio: +(r.height / pr.height).toFixed(2),
                    hasWrap: !!wrap};
        })()""")
        browser.screenshot(os.path.join(out_dir, '01_login.png'))
        ok = gauge is not None and gauge['h'] >= 320
        results.append(('登录页水尺标尺放大', ok, gauge))
        results.append(('登录页控制台无错误', not problems, problems))
        print('  登录页截图完成', flush=True)

        # 2) 登录进看板：用 Python 侧的 HTTP 会话拿 Cookie 再注入浏览器。
        #    不通过页面里的 handleLogin() 驱动：它成功后会 window.location.href 跳转，
        #    与后续 Page.navigate 竞争，会让之后的页面命令（尤其截图）永远等不到响应。
        session_cookie = http_login(base, USERNAME, PASSWORD)
        browser.call('Network.setCookie', {
            'name': 'session', 'value': session_cookie,
            'domain': '127.0.0.1', 'path': '/',
        })
        events = browser.goto(base + '/index', settle=4.0)
        problems = collect_errors(events)
        title = browser.evaluate("document.title")
        print('  看板已加载（title=%r），截图…' % title, flush=True)
        if '登录' in str(title):
            raise CheckError('Cookie 注入后仍停在登录页，会话未生效（title=%r）' % title)
        browser.screenshot(os.path.join(out_dir, '02_dashboard.png'))
        print('  看板截图完成，读取布局…', flush=True)

        layout = browser.evaluate("""(() => {
            const s = document.getElementById('sensorPanel');
            const c = document.getElementById('controlPanel');
            const t = s.querySelector('.section-hd').textContent.trim();
            const cells = [...s.querySelectorAll('.sensor-cell .sensor-name')].map(e => e.textContent.trim());
            const fills = [...document.querySelectorAll('.dual-range-fill')].map(e => {
                const r = e.getBoundingClientRect();
                const c = e.parentElement.getBoundingClientRect();
                return {left: +((r.left - c.left) / c.width * 100).toFixed(1),
                        width: +(r.width / c.width * 100).toFixed(1)};
            });
            return {sensorBottom: Math.round(s.getBoundingClientRect().bottom),
                    controlBottom: Math.round(c.getBoundingClientRect().bottom),
                    title: t, cells: cells, fills: fills,
                    logH: Math.round(document.querySelector('.log-scroll').getBoundingClientRect().height),
                    overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth};
        })()""")
        results.append(('读数卡标题已改为「田间实时数据」',
                        layout['title'] == '田间实时数据', layout['title']))
        pump_idx = layout['cells'].index('气泵') if '气泵' in layout['cells'] else -1
        water_idx = layout['cells'].index('水泵') if '水泵' in layout['cells'] else -1
        results.append(('气泵读数卡在水泵之上', 0 <= pump_idx < water_idx,
                        '气泵@%s 水泵@%s' % (pump_idx, water_idx)))
        delta = abs(layout['sensorBottom'] - layout['controlBottom'])
        results.append(('调控卡与读数卡底部对齐（差 ≤2px）', delta <= 2,
                        'delta=%dpx' % delta))
        results.append(('阈值滑块有区间高亮', len(layout['fills']) == 2
                        and all(f['width'] > 0 for f in layout['fills']), layout['fills']))
        results.append(('日志卡高度正常（未塌陷）', layout['logH'] > 100, layout['logH']))
        results.append(('无横向溢出', layout['overflowX'] <= 0, layout['overflowX']))

        # 3) 系统设置弹窗
        # 关掉 Leaflet：底图瓦片在离线/校园网不可达，地图实例会让合成器一直等帧，
        # 截图会卡住。关掉后正好走 farm.js 的「地图降级为手填经纬度」分支，
        # 这也是真实校园网环境的形态，顺带把降级路径一起验证了。
        browser.evaluate("(() => { window.L = undefined; return true; })()")
        browser.evaluate("openModal('configModal')")
        browser.wait(1.4)
        cfg = browser.evaluate("""(() => {
            const m = document.getElementById('configModal');
            const blocks = [...m.querySelectorAll('.cfg-block-hd h3')].map(e => e.textContent.trim());
            const ids = ['cfgUsername','cfgFarmName','cfgFarmLat','cfgFarmLng','cfgIotHost',
                         'cfgIotClientId','cfgIotDeviceId','cfgTargetDeviceId','cfgIotUser',
                         'cfgIotPass','cfgM2mTopic','cfgCmdTopic','cfgWeatherDomain',
                         'cfgWeatherKey','cfgAiDomain','cfgAiKey','cfgWebhookUrl'];
            const missing = ids.filter(i => !document.getElementById(i));
            const hasSim = !!document.getElementById('simBlock');
            return {blocks: blocks, missing: missing, hasSim: hasSim};
        })()""")
        browser.screenshot(os.path.join(out_dir, '03_settings.png'))
        results.append(('系统设置已按语义分组', len(cfg['blocks']) >= 6, cfg['blocks']))
        results.append(('设置字段 id 无缺失', not cfg['missing'], cfg['missing']))
        results.append(('「演示数据」模块已移除', not cfg['hasSim'], cfg['hasSim']))
        results.append(('地图降级提示可见（离线可用）',
                        browser.evaluate(
                            "(() => { const f = document.getElementById('farmMapFallback');"
                            " return !!f && !f.hidden; })()"), 'farmMapFallback'))
        browser.evaluate("closeModal('configModal')")
        browser.wait(0.6)

        # 4) 智能洞察
        browser.evaluate("openInsight()")
        browser.wait(2.5)
        insight = browser.evaluate("document.querySelectorAll('.insight-tab').length")
        browser.screenshot(os.path.join(out_dir, '04_insight.png'))
        results.append(('智能洞察 5 个 Tab 可打开', insight == 5, insight))
        browser.evaluate("closeInsight()")
        browser.wait(0.6)

        # 5) 知识库
        events = browser.goto(base + '/knowledge', settle=2.5)
        problems += collect_errors(events)
        browser.screenshot(os.path.join(out_dir, '05_knowledge.png'))
        results.append(('看板全流程控制台无错误', not problems, problems))

        # 6) 窄屏：单列不塌陷
        browser.call('Emulation.setDeviceMetricsOverride',
                     {'width': 860, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        events = browser.goto(base + '/index', settle=3.5)
        narrow = browser.evaluate("""(() => {
            const s = document.getElementById('sensorPanel');
            const c = document.getElementById('controlPanel');
            return {stacked: c.getBoundingClientRect().top > s.getBoundingClientRect().bottom - 2,
                    logH: Math.round(document.querySelector('.log-scroll').getBoundingClientRect().height),
                    overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth};
        })()""")
        browser.screenshot(os.path.join(out_dir, '06_narrow.png'))
        results.append(('860px 窄屏两列改单列堆叠', narrow['stacked'], narrow))
        results.append(('窄屏无横向溢出', narrow['overflowX'] <= 0, narrow['overflowX']))
        results.append(('窄屏控制台无错误', not collect_errors(events), ''))

        print('\n截图输出目录：%s' % out_dir)
        failed = 0
        for name, ok, detail in results:
            print('%s  %s%s' % ('PASS' if ok else 'FAIL', name,
                                '' if ok else '  → %s' % (detail,)))
            if not ok:
                failed += 1
        print('\n%s：%d/%d 通过' % ('全部通过' if not failed else '存在失败',
                                    len(results) - failed, len(results)))
        return 0 if not failed else 1
    finally:
        if browser is not None:
            browser.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv=None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description='青禾智灌浏览器验收（headless Edge + CDP）')
    parser.add_argument('--port', type=int, default=5099, help='服务端口（默认 5099）')
    args = parser.parse_args(argv)
    try:
        return run(args)
    except CheckError as exc:
        print('失败：%s' % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
