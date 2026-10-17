# 青禾智灌智慧灌溉管理平台 — 系统体检报告

> 体检方式：**只读静态审查 + 运行时黑盒/白盒探测**，全程未修改任何现有文件。
> 体检对象：`D:\AI\Farm`，HEAD = `ba56598`（2026-10-18 01:58:31 +0800）
> 运行环境：Windows / Python 3.14.5 / Flask + Flask-SocketIO / SQLite(WAL)
> 探测用库：`test_probe.db`（`qinghe.db` 的副本），服务以 `FARM_DB_PATH=test_probe.db PORT=5099 FARM_DEBUG=0 python app.py` 启动。
> 探测脚本：`tools/probe/` 下 `probe_typeconfusion.py`（类型混淆）、`probe_jwt.py`（JWT 绕过）、`probe_p1.py`（限流/响应头/边界）。

---

## 0. 重要前提：任务描述与实际代码不符

任务书描述「app.py 975 行、templates/index.html 1616 行」。实测：

| 文件 | 任务书描述 | 实测 |
|---|---|---|
| `app.py` | 975 行 | **23 行 / 750 字节**（仅装配入口） |
| `templates/index.html` | 1616 行 | **410 行**（已拆分） |
| `static/js/*.js` | 不存在 | **11 个文件，约 120 KB** |

仓库已重构为 `qinghe/` 包（`config / db / auth / iot / irrigation / alerts / realtime / heartbeat / metrics / logbook / planner / alert_center / weather / ai` + `routes/` 蓝图）。**本报告全部结论基于重构后的真实代码，行号均为当前 HEAD 实测行号。**

> 体检期间有并发开发者在同一工作区持续提交（我观测到 HEAD 从 `132e38b` 一路推进到 `ba56598`，共 25+ 次提交）。**本报告所有 P0/P1 结论均已在最终 HEAD `ba56598` 上重新复现确认**；被并发修复掉的项统一记录在 §四「已确认无问题的项」。

---

## 一、缺陷清单表

| 编号 | 严重度 | 位置（文件:行） | 现象（实测证据） | 根因 | 建议修法 |
|---|---|---|---|---|---|
| **D1** | **P0** | `qinghe/routes/auth_routes.py:22`（register）、`:43`（login）、`:88`（app_login）、`:73`（change_password）；`qinghe/routes/data_routes.py:105`、`:106` | **非字符串 JSON 字段直接 500**。POST `/api/register` body `{"username":12345,...}` → **500 Internal Server Error**（HTML 错误页）。实测 13 个类型混淆用例中 **11 个返回 500**。异常：`AttributeError: 'int' object has no attribute 'strip'`（`'list'`/`'dict'`/`'bool'` 同理） | 代码写 `(data.get('username') or '').strip()`，只兜住 falsy，未校验类型；int/list/dict 是 truthy，直接调 `.strip()` 崩 | 统一入口做类型校验：`if not isinstance(username, str): return 400`；或封装 `_str_field(data, key, maxlen)` 工具函数。**所有** `data.get(x).strip()` 处都要改 |
| **D2** | **P0** | `qinghe/config.py:21` + `:174`；消费点 `qinghe/auth.py:129`、`:164` | **JWT 鉴权可被完全绕过，任意用户越权**。未设 `FARM_SECRET_KEY` 时 `app.secret_key` 回落到硬编码常量 `'smart_irrigation_secret_2026'`。攻击者用该常量自签 token，**实测成功**：`user_id=1/2/22` 三个伪造 token 调 `/api/app_send_command` 全部 **200 `{"status":"success"}`**，服务端实际执行 `(1,{'water_pump':'on'})`、`(2,...)`、`(22,...)` | 兜底密钥是源码里的固定字面量，等同公开密钥；`require_token` 用它验签，签名因此"验证通过" | 未设 `FARM_SECRET_KEY` 时**拒绝启动**（或随机生成并打印一次性密钥），绝不使用固定兜底值。同时 `FALLBACK_SECRET_KEY` 从源码删除 |
| **D3** | **P1** | `qinghe/auth.py:26-31`（`_client_ip`）→ `:34-36`（`_login_key`） | **登录限流可被单请求头绕过**。同一 IP 连续失败：`[401,401,401,401,401,429,429,429]`（第 6 次起 429，符合 `LOGIN_MAX_FAIL=5`）；但**每次轮换 `X-Forwarded-For`** 后连续 12 次失败**全部 401，无一次 429** | `_client_ip()` 无条件信任客户端可伪造的 `X-Forwarded-For` 首段，限流键 = `用户名:伪造IP`，每次换 IP 即重置计数 | 仅在受信反向代理后启用 XFF 解析（如 `FARM_TRUSTED_PROXY=1`），否则用 `request.remote_addr`；或改用「仅用户名」+ 全局兜底限流 |
| **D4** | **P1** | `qinghe/iot.py:474` | **脏 `iot_port` 使 MQTT 连接线程崩溃**。直连调用 `connect_huawei_iot(uid)`（库中 `iot_port='abc'`）抛 **`ValueError: invalid literal for int() with base 10: 'abc'`**（`qinghe/iot.py:474`，`port = int(cfg['iot_port'] or config.IOT_PORT_DEFAULT)`） | `int()` 无异常兜底；旧库/直改库/迁移残留都可能留下非数字端口 | `try: port = int(...) except (TypeError, ValueError): port = config.IOT_PORT_DEFAULT`，并加日志 |
| **D5** | **P1** | `qinghe/routes/data_routes.py:105-106` | 同 D1，但为**需登录**接口：`/api/notify_alert` 传 `{"msg":12345}` / `{"level":123}` / list 型 → **500**。该接口会向用户配置的 webhook 外发，异常路径可被用于**探测/骚扰** | 同 D1 | 同 D1 |
| **D6** | **P2** | `qinghe/routes/auth_routes.py:73,78` → `qinghe/auth.py:107` | `/api/change_password` 传 `{"old_password":123,...}` → **500**，异常 `AttributeError: 'int' object has no attribute 'encode'`（`auth.py:107` `check_password_hash`） | 同上，且 `verify_password` 未做类型防御 | 同 D1；`verify_password` 内加 `if not isinstance(password,str): return False` |
| **D7** | **P2** | `qinghe/auth.py:19`、`81-96` | 限流状态 `_login_fail` 为**进程内 dict**。多 worker（`gunicorn -w N` / 多实例）部署时各进程独立计数，限流阈值实际放大 N 倍 | 用进程内存做限流，未用共享存储 | 生产多 worker 时改用 Redis / 数据库计数 |
| **D8** | **P2** | `qinghe/config.py:21`、`qinghe/__init__.py:28-36` | 兜底密钥仅在**启动日志**里 warning，不阻止运行。`FARM_DEBUG` 默认已是 `'0'`（**此项已修好**，见 §四），故默认会打印警告但服务照常起 | 警告非强制 | 与 D2 合并处理：改为启动即失败 |
| **D9** | **P2** | `qinghe/routes/data_routes.py:86` 区域（`/api/notify_alert`） | `msg` 用 `[:500]` 截断但**未过滤控制字符**；`level` 直接拼进 webhook 标题 `'[青禾智灌] %s 告警' % level`（`data_routes.py:90`），可注入换行/`@` 等影响钉钉等接收端渲染 | 拼接外部输入未净化 | 对 `level` 做白名单（`info/warn/error`），对 `msg` 过滤控制字符 |
| **D10** | **P2** | `qinghe/auth.py:127` | 使用 `datetime.datetime.utcnow()`（Python 3.12+ 已弃用，3.14 实测 `DeprecationWarning`） | 未用 timezone-aware | 改 `datetime.datetime.now(datetime.UTC)` |

> **未发现的项（经实测排除，见 §四）**：SQLite `database is locked`、前端 XSS、CSP 与 CDN 不一致、`setInterval` 泛滥、`localStorage` 全表读写、`sqlite3` 连接泄漏、`mqtt_clients` 竞态。这些在旧代码中确实存在，但**当前 HEAD 已修复**。

---

## 二、性能与卡顿点清单

| 编号 | 位置 | 量化依据 | 结论 |
|---|---|---|---|
| P-1 | `qinghe/iot.py:83-176` `HistoryWriter` | 队列 `HISTORY_QUEUE_MAX=2000`、`HISTORY_FLUSH_INTERVAL=1.0s`、`HISTORY_FLUSH_BATCH=200`（`config.py:162-164`）。MQTT 回调仅 `enqueue()`（O(1) 非阻塞），后台单线程批量落库 | ✅ **已优化**：回调线程零阻塞，符合 AGENTS.md「落库走批量/队列」 |
| P-2 | `qinghe/iot.py:390-412` `handle_mqtt_message` | 函数内不再 `get_db()` 建连接；落库走 `writer.enqueue()` | ✅ **已优化**：原「每条消息建一次连接」已消除 |
| P-3 | 实测吞吐（2000 条消息） | 逐条 `connect+commit` 路径约 **180-207 msg/s**；瓶颈在 SQLite 单条 commit 的 fsync，非代码 | ⚠️ **可再优化**：`insert_history_rows` 已批量，但 WAL 下 `synchronous=NORMAL` 未设，仍每次 fsync。建议 `PRAGMA synchronous=NORMAL` |
| P-4 | `static/js/core.js:185-216` 统一 tick | 全局仅 **1 个 `setInterval`**（`core.js:203`，`TICK_MS=500`），分频：时钟 1s / DOM 500ms / 图表 2s / 心跳 5s / 告警 5s / 趋势落盘 30s | ✅ **已优化**：原先「时钟 1s、心跳 10s、图表 2s」多个 `setInterval` 已合并为单 tick |
| P-5 | `static/js/core.js:68-73` `setText` | 值未变则直接 return，不触碰 DOM（`el.__qhText` 缓存） | ✅ **已优化**：消除无谓重排 |
| P-6 | `static/js/store.js:12-20, 30-35, 54-60` | 内存态为唯一数据源；`FLUSH_MS=30000` 节流批量落盘（仅脏标记时写）；硬上限裁剪：趋势 2000 点 / 日志 500 条 / 告警 200 条 | ✅ **已优化**：原「每次读全量→改→写全量」已消除 |
| P-7 | `templates/index.html` | 410 行（原 1616 行），JS 已拆到 `static/js/` 11 个文件，按需加载 | ✅ **已优化** |
| P-8 | 历史列表渲染 | `/api/history` 有 `limit` 上限校验（`limit=999999` 被拒/钳制） | ✅ 见 API 矩阵 §三 |

---

## 三、API 实测矩阵

服务：`FARM_DB_PATH=test_probe.db PORT=5099 FARM_DEBUG=0 python app.py`（`0.0.0.0:5099`）

### 3.1 注册 `/api/register`

| 场景 | 请求 | 实际返回 |
|---|---|---|
| 正常 | `{"username":"probe_12345","password":"Passw0rd!"}` | `200` `{"status":"success",...}` |
| 重复用户名 | 同上再发 | `400` `{"status":"error","message":"账号已存在"}` |
| 超短用户名 | `{"username":"ab",...}` | `400` `{"status":"error","message":"用户名长度需为 3-20 字符"}` |
| 超短密码 | `{"username":"...","password":"123"}` | `400` `{"status":"error","message":"密码长度需为 6-64 字符"}` |
| 非 JSON body | `data="username=a&password=b"` | `400` `{"status":"error",...}`（`request.json` 为 None → `or {}`） |
| 超大 body | password = 1 MB | `400` `{"status":"error","message":"密码长度需为 6-64 字符"}` |
| 超长用户名 500 字符 | | `400` `{"status":"error",...}` |
| SQL 注入用户名 | `"a'; DROP TABLE users;--"` | `200` 正常处理（参数化查询，**无注入**） |
| **username = int/list/dict/bool** | `{"username":12345}` 等 | **`500` Internal Server Error** ❌ **D1** |
| 缺字段 | `{"username":"..."}` | `400` `{"status":"error",...}` |

### 3.2 登录 `/api/login` 与限流

| 场景 | 实际返回 |
|---|---|
| 正常 | `200` `{"status":"success",...}` + `Set-Cookie` session |
| 错误密码 | `401` `{"status":"error","message":"账号或密码错误"}` |
| 不存在用户 | `401` `{"status":"error",...}`（**不区分**用户是否存在，防枚举 ✅） |
| 缺字段 / `password:null` | `400` `{"status":"error","message":"请输入账号和密码"}` |
| 非 JSON | `400` `{"status":"error",...}` |
| 连续失败 8 次（同 IP） | `[401,401,401,401,401,429,429,429]` ✅ 限流生效 |
| **轮换 X-Forwarded-For 连续 12 次** | `[401]×12`，**无 429** ❌ **D3** |
| `username` = int/list | **`500`** ❌ **D1** |

### 3.3 配置 `/api/get_config` `/api/save_config`

| 场景 | 实际返回 |
|---|---|
| 未登录 GET | `401` `{"error":"未授权"}` ✅ |
| 未登录 POST | `401` ✅ |
| 已登录 GET | `200`，返回配置字典（敏感字段掩码 `••••••••`）✅ |
| 掩码回写（原样 save 回 get 的结果） | `200`；**实测掩码未被写入真实字段**（服务端识别掩码并跳过）✅ |
| 全 null 字段 | `200`，未把配置清空 ✅ |
| `farm_name` 10 万字符 | `200`（已截断/校验） |
| `iot_port='abc'` | `200` `{"status":"error",...}`（路由层拒绝非数字）✅ **但** `qinghe/iot.py:474` 无兜底 → **D4** |
| `iot_port=-1/0/70000/3.7/True` | 均被校验拒绝 ✅ |

### 3.4 历史 `/api/history`

| 场景 | 实际返回 |
|---|---|
| 未登录 | `401` `{"error":"未授权"}` ✅ |
| `limit=0` / `-1` / `abc` / `999999` / `5001` | 均被钳制/拒绝，**无 500、无全表返回** ✅（旧代码此处 `int('abc')` 会 500，**已修**） |

### 3.5 阈值 `/api/thresh_settings`

| 场景 | 实际返回 |
|---|---|
| GET 未登录 | `401` ✅ |
| POST `humi_down=90 > humi_up=10` | 被拒/纠正，不产生非法区间 ✅ |
| 非数字 `'abc'` | `200` `{"status":"error",...}` ✅ |
| 负数 / 超大值 / null / 缺字段 | 均被校验处理，无 500 ✅ |
| 全部合法 | `200` `{"status":"success"}` ✅ |

### 3.6 外部依赖与其它

| 接口 | 场景 | 实际返回 |
|---|---|---|
| `/api/ai_chat` | 无 key | `200`，返回提示「未检测到 AI Key，请在【设置】中配置」（**不 500** ✅） |
| `/api/ai_chat` | 未登录 | `401` ✅ |
| `/api/ai_chat` | `msg` 传 int/list | `200`（有 `str()` 兜底）✅ |
| `/api/forecast` | 非法 `lng/lat` | 优雅降级，无 500 ✅ |
| `/api/reverse_geocode` | 缺参数 / 非法坐标 / 正常坐标 | 均正常处理 ✅ |
| `/api/notify_alert` | 未登录 | `401` ✅ |
| `/api/notify_alert` | 缺 `msg` | `400` `{"status":"error","message":"缺少告警内容"}` ✅ |
| `/api/notify_alert` | 超长 msg 20 万字符 | `200`（截断至 500）✅ |
| `/api/notify_alert` | **`msg`/`level` 传 int/list** | **`500`** ❌ **D5** |
| `/api/app_login` | 正常 | `200` `{"status":"success","token":"eyJ..."}`（HS256，7 天）✅ |
| `/api/app_send_command` | 无 token / 空 Bearer / `Basic abc` | `401` ✅ |
| `/api/app_send_command` | 篡改签名 | `401` `{"message":"Token无效或过期"}` ✅ |
| `/api/app_send_command` | **兜底密钥自签 token（user_id=1/2/22）** | **`200` `{"status":"success","message":"指令已发送"}`** ❌❌ **D2** |
| `/api/app_send_command` | 真 token + 非法 device | `400` `{"message":"未知设备"}` ✅ |
| `/api/app_send_command` | 真 token + 非法 action | `200`，归一化为 `off` ✅ |
| `/api/change_password` | 未登录 | `401` ✅ |
| `/api/change_password` | 原密码错误 | `200` `{"status":"error","message":"原密码错误"}` ✅ |
| `/api/change_password` | 新密码太短 | `200` `{"status":"error","message":"新密码长度需为 6-64 字符"}` ✅ |
| `/api/change_password` | **`old_password` 传 int** | **`500`** ❌ **D6** |
| `/` | 未登录 | `200` 渲染 `login.html` ✅ |
| `/index` | 未登录 | `302` → `/` ✅ |
| `/index` | 已登录 | `200` 渲染 `index.html` ✅ |
| `/api/logout` | 已登录 / 未登录 | 均正常 ✅ |

### 3.7 安全响应头（`GET /` 实测）

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'
  https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline';
  img-src 'self' data:; connect-src 'self' https:; font-src 'self' data:;
  object-src 'none'; base-uri 'self';
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: no-referrer
Strict-Transport-Security: （未设置）
```

- **CSP 与实际 CDN 一致 ✅**：全仓外部 URL 仅 5 条，脚本仅 2 条 —— `templates/index.html:8` cdnjs socket.io 4.7.1、`templates/index.html:10` jsdelivr chart.js 4.4.1，两者都在 `script-src` 白名单内，**无遗漏、无冲突**。其余 3 条是文档文案（`index.html:270` deepseek、`index.html:278` 钉钉）与 `weather.js:15` open-meteo（由 `connect-src 'self' https:` 覆盖）。
- `script-src` 含 `'unsafe-inline'` ⚠️：削弱了 XSS 防护。当前前端已无内联事件处理器，建议后续移除（需先确认无内联 `<script>`）。
- 缺 `Strict-Transport-Security`：若走 HTTPS 反代建议补。

---

## 四、已确认「无问题」的项（实测排除）

| 项 | 验证方式 | 结论 |
|---|---|---|
| **SQLite 并发写 `database is locked`** | 20 线程并发写入 `sensor_history` | ✅ **未复现**。`qinghe/db.py:25-30` 已启用 `PRAGMA journal_mode=WAL` + `busy_timeout=10000`（`DB_TIMEOUT=10`）。WAL 下读不阻塞写、写串行化由 busy_timeout 兜住 |
| **`sqlite3.connect` 泄漏** | 全仓仅 **1 处** `sqlite3.connect`（`qinghe/db.py:25`），封装在 `get_db()`；58 处 `get_db` 引用中 48 处显式 `with closing(...)`，其余为 `import`/`def`/`get_db_path` | ✅ **无泄漏**。AGENTS.md「一律用 `closing(get_db())`」已被遵守 |
| **`mqtt_clients` 线程竞态** | `qinghe/iot.py:28-29` `mqtt_clients = {}` + `mqtt_lock = threading.RLock()`；`get_client/is_connected/set_connected/_stop_client/clear_clients`（`:32-75`）**全部**持锁访问 | ✅ **已加锁**。`get_client` 还返回 `dict(entry)` 副本，避免外部持引用改内部状态 |
| **前端 XSS（`innerHTML` 拼接外部数据）** | 全仓 `innerHTML` 出现 **5 次，全在注释里**，**0 处赋值**；`textContent` 使用 **58 处**；`esc()` 定义于 `core.js:49-53` | ✅ **已消除**。MQTT payload / 天气 / 逆地理返回值均走 `textContent` 或 DOM 节点构建（`realtime.js:94` 注释明确「DOM 节点构建，避免 innerHTML 拼接」） |
| **`setInterval` 泛滥** | 全仓仅 **1 处实际调用**（`core.js:203`），另 2 处为注释 | ✅ **已统一** |
| **图表 `update()` 频率** | 统一 tick 内 2s 分频（`core.js:183`） | ✅ 合理 |
| **`localStorage` 全表读写** | `store.js` 内存态 + 30s 节流 + 硬上限裁剪 | ✅ **已优化** |
| **`FARM_DEBUG` 默认值** | `qinghe/config.py:167-169`：`os.environ.get('FARM_DEBUG','0') == '1'` | ✅ **默认已是 0（生产安全）**。任务书假设的「默认 1」在旧代码成立，**现已修复** |
| **SQL 注入** | 注册/登录用户名传 `"a'; DROP TABLE users;--"` | ✅ 参数化查询，无注入 |

---

## 五、与代码注释/文档不符之处

1. **任务书与代码规模不符（最大）**：任务书称 `app.py` 975 行、`templates/index.html` 1616 行；实测 `app.py` **23 行**、`index.html` **410 行**。项目已重构为 `qinghe/` 包 + `static/js/` 拆分，行号引用需全部重算。
2. **`qinghe/__init__.py:28-36` 注释称警告「不改变任何启动行为」** —— 实测属实（仅打日志）。但该注释把「用兜底密钥继续运行」表述为既定设计，掩盖了 D2 的真实风险等级：它不是「提示」而是**可被完全绕过的鉴权**。
3. **`qinghe/auth.py:26-27` 文档串**「取真实来源 IP（若有反向代理 X-Forwarded-For 则取其第一段）」—— 措辞暗示这是可信 IP，实际**未验证来源**，任何客户端可伪造（D3）。
4. **`qinghe/db.py:4` 注释**「连接一律通过 `closing()` 或 `with closing(get_db()) as conn:` 关闭，禁止泄漏」—— 与实测一致 ✅，**但** `qinghe/iot.py:474` 的 `int(cfg['iot_port'])` 这类**值级**健壮性无约定，导致 D4。
5. **`qinghe/iot.py:390-394` 注释**「本函数在 MQTT 回调线程中执行，**不得**做任何阻塞 IO」—— 实测 `handle_mqtt_message` 确实只做 `enqueue()` ✅；但其调用的 `_feed_insight`（`:279-388`）内部有同步 DB 读写（`planner`/`alert_center`/`heartbeat`/`metrics`），**与注释的「零阻塞」承诺存在张力**，高并发上报时该路径仍会阻塞回调线程。
6. **AGENTS.md 要求「`python -m pytest tests -q` 全绿」** —— 体检期间实测**曾多次不达标**（最多一次 `20 failed, 536 passed`，失败集中在 `tests/test_socket_events.py`，因 `realtime.register_events` 的 `on_ws_connect` 增加 `sid` 参数而测试未同步，另有 `test_weather.py` / `test_alerts.py` 跨模块污染）。**在 HEAD `b16bb62` 上连续 3 次实测 `565 passed` 全绿**，属并发开发者已修复。此条记录的是「契约在体检窗口内曾被破坏」，非当前缺陷。

---

## 六、修复优先级建议

1. **立即（P0）**：D2（删除硬编码兜底密钥 + 未配置即拒绝启动）、D1/D5/D6（统一 `data.get(x)` 类型校验）。
2. **本迭代（P1）**：D3（`_client_ip` 信任边界）、D4（`iot_port` 解析兜底）。
3. **跟进（P2）**：D7（多 worker 限流）、D9（webhook 输入净化）、D10（`utcnow()` 弃用）、移除 CSP `'unsafe-inline'`、补 HSTS。
4. **性能**：P-3 建议加 `PRAGMA synchronous=NORMAL`；`_feed_insight` 的同步 DB 调用考虑改为异步/批量（见 §五-5）。

---

## 附录：复现命令

```powershell
# 1) 准备测试库并启动服务
cd D:\AI\Farm
copy qinghe.db test_probe.db
$env:FARM_DB_PATH='test_probe.db'; $env:PORT='5099'; $env:FARM_DEBUG='0'
python app.py    # 后台运行

# 2) P0 类型混淆（D1/D5/D6）
python tools/probe/probe_typeconfusion.py

# 3) P0 JWT 绕过（D2）
python tools/probe/probe_jwt.py

# 4) P1 限流绕过（D3）+ 其它
python tools/probe/probe_p1.py

# 5) 测试套件
python -m pytest tests -q
```

**体检结束后台服务已停止**（已确认 5099 端口无监听）。
