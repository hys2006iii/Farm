## 十一、HTTP接口详细设计

HTTP 层是前端与 App 访问系统的唯一入口，由 8 个蓝图构成（`app_api` / `auth_api` / `config_api` / `data_api` / `ai_api` / `monitor` / `insight` / `export`），在 `qinghe/__init__.py` 的应用工厂中统一注册。本章给出接口设计约定、完整路由清单与逐接口行为说明。

### 11.1 设计约定

**鉴权分两套，互不替代。**

| 访问方 | 凭据 | 载体 | 校验函数 |
|---|---|---|---|
| 浏览器页面 | Flask Session（Cookie） | 会话 Cookie | `session['user_id']` 是否存在 |
| 移动 App | JWT（HS256，7 天） | `Authorization: Bearer <token>` | `auth.require_token` 装饰器 |

分两套的原因：浏览器要防 CSRF、要能服务端主动失效，Session 天然满足；移动 App 没有 Cookie 容器，反复登录体验差，因此发 7 天有效的 JWT。`auth.issue_token(uid, days=7)` 的 payload **只含 `user_id` 与 `exp`**，不放用户名、权限等可被改写的业务字段；`require_token` 校验通过后把 `user_id` 作为被装饰函数的**首个位置参数**注入（例如 `def api_app_command(uid):`），因此业务函数内部不再重复解析 Token。

**统一响应形状。** 成功返回 `{'status': 'success', ...}` 或直接返回数据体；失败返回 `{'error': '<中文原因>'}` 并配以恰当的 4xx/5xx 状态码。所有面向用户的原因文本都是中文，前端可直接渲染。

**校验前置，非法入参返回 4xx 而非 500。** 所有写接口先用 `qinghe/validators.py` 做类型/范围/长度校验，不合格立即返回，不进入业务逻辑。校验器统一 API 为 `as_str` / `as_stripped` / `as_int` / `as_float` / `as_bool` / `truncated` / `get_json_object`，以及严格版 `parse_int_range(value, lo, hi, name='参数')` / `parse_float_range` / `parse_str_field` / `parse_bool_strict`；失败一律抛 `ValidationError(message, status=400)`，由路由捕获后原样转成响应，避免每个接口各写一套错误格式。

![图 11-1 HTTP 请求处理流水线](figs/x_http_pipeline.png)

### 11.2 路由总表

表 11-1 完整路由清单
| 方法 | 路径 | 处理函数 | 鉴权 | 说明 |
|---|---|---|---|---|
| GET | `/` | `route_root` | 无 | 未登录跳登录页，已登录渲染主监控台 |
| GET | `/index` | `route_index` | 无 | 主监控台别名入口 |
| GET | `/knowledge` | `route_knowledge` | 无 | 知识库页面（作物-缺氧-调控知识） |
| GET | `/static/<path:filename>` | Flask 静态 | 无 | 静态资源，第三方库全部本地化 |
| POST | `/api/register` | `api_register` | 无 | 注册账号（IP 限流） |
| POST | `/api/login` | `api_login` | 无 | 登录（用户名维度限流） |
| GET | `/api/logout` | `api_logout` | Session | 退出登录 |
| POST | `/api/change_password` | `api_change_password` | Session | 修改密码 |
| POST | `/api/app_login` | `api_app_login` | 无 | App 登录，返回 JWT 并触发 MQTT 建连 |
| POST | `/api/app_send_command` | `api_app_command` | JWT | App 下发控制指令 |
| GET | `/api/get_config` | `api_get_config` | Session | 读配置（敏感字段打码） |
| POST | `/api/save_config` | `api_save_config` | Session | 存配置（掩码即保留原值） |
| POST | `/api/diag/<target>` | `api_diag` | Session | 外部接入连通性自检 |
| GET | `/api/thresh_settings` | `api_get_thresh` | Session | 读阈值 |
| POST | `/api/thresh_settings` | `api_save_thresh` | Session | 存阈值 |
| GET | `/api/history` | `api_history` | Session | 历史采样（按当前地块） |
| GET | `/api/forecast` | `api_forecast` | Session | 7 日天气预报代理 |
| GET | `/api/reverse_geocode` | `api_reverse_geocode` | Session | 逆地理（带缓存） |
| POST | `/api/notify_alert` | `api_notify_alert` | Session | 手动触发告警推送 |
| POST | `/api/ai_chat` | `api_ai_chat` | Session | AI 问答（带实时快照） |
| GET | `/api/alerts` | `list_alerts` | Session | 告警列表 |
| POST | `/api/alerts/ack` | `ack_alert` | Session | 确认单条告警 |
| POST | `/api/alerts/ack_all` | `ack_all_alerts` | Session | 一键全部确认 |
| GET | `/api/logs` | `list_logs` | Session | 运行日志列表 |
| GET | `/api/device_status` | `device_status` | Session | 设备在线状态 |
| GET | `/api/telemetry` | `latest_telemetry` | Session | 最新遥测快照（页面刷新后恢复） |
| POST | `/api/plan/propose` | `plan_propose` | Session | 生成 AI 决策预案 |
| POST | `/api/plan/confirm` | `plan_confirm` | Session | 人工确认并逐条下发 |
| POST | `/api/plan/reject` | `plan_reject` | Session | 人工拒绝预案 |
| GET | `/api/plans` | `plan_list` | Session | 预案列表 |
| GET | `/api/metrics` | `metrics_overview` | Session | 节水减碳指标 |
| GET | `/api/auto_control` | `auto_control_status` | Session | 读自动调控开关 |
| POST | `/api/auto_control` | `auto_control_toggle` | Session | 切换自动调控开关 |
| GET | `/api/advice/calendar` | `api_advice_calendar` | Session | 未来 7 日雨情与灌溉建议 |
| GET | `/api/export/history.csv` | `export_history_csv` | Session | 导出历史采样 CSV |
| GET | `/api/export/alerts.csv` | `export_alerts_csv` | Session | 导出告警 CSV |
| GET | `/api/farms` | `api_list_farms` | Session | 地块列表 |
| POST | `/api/farms` | `api_create_farm` | Session | 新建地块 |
| POST | `/api/farms/switch` | `api_switch_farm` | Session | 切换当前地块 |
| POST | `/api/farms/update` | `api_update_farm` | Session | 更新地块信息 |
| POST | `/api/farms/delete` | `api_delete_farm` | Session | 删除地块 |

路由挂载位置在 `qinghe/routes/` 下按模块分文件：`advice_routes.py:17`、`ai_routes.py:18`、`app_routes.py:15/23/31/39`、`auth_routes.py:37/66/106/113/141`、`config_routes.py:140/156/232/248/259`、`data_routes.py:24/51/73/99`、`farm_routes.py:134/149/180/219/261`、`insight_routes.py:67/86/106/130`、`monitor_routes.py:66/89/107/129/152/173`。

### 11.3 认证与配置类接口

**`POST /api/register`。** 用户名 3–20 字符、密码 6–64 字符，均先 trim。注册本身按来源 IP 限流：`config.REGISTER_MAX_ATTEMPTS = 10` 次以内放行，超出返回 429。注册成功不自动登录，需回到登录页走一次登录流程。

**`POST /api/login`。** 失败计数按**用户名**维度而非 IP 维度统计，采用滑动窗口：`config.LOGIN_MAX_FAIL = 5` 次失败后锁定 `config.LOGIN_LOCK_SECONDS = 600` 秒（10 分钟），期间返回 429 与 `'尝试次数过多，请 10 分钟后再试'`。选用户名维度是因为"同一 IP 下有多个师生账号"是校园网的常态，按 IP 锁会误伤同寝室的其他人；而按用户名锁能精准拦住针对某个账号的暴力破解。登录成功会清空该用户名的失败计数。

登录流程内还有一个**密码哈希自动升级**动作。历史版本用明文存密码，`auth.verify_password` 在比对成功且发现库中存的是明文（`is_password_hash(stored)` 为假）时会调用 `upgrade_plaintext_password(uid, password)` 就地替换为 PBKDF2 哈希——老用户在下一次登录时无感迁移，不需要管理员批量重置。

**`POST /api/app_login`。** 与网页登录同源校验，但返回 JWT，并异步触发该用户的 MQTT 建连（复用 `auth_routes._connect_iot_async`），避免 App 登录时 60 秒的 broker 连接超时阻塞响应。

**`GET /api/get_config` 与 `POST /api/save_config`。** 一对读写接口，通过**掩码占位**实现"只改想改的字段"。读取时 `iot_pass`、`weather_key`、`ai_key` 三个敏感字段一律替换为 `config.MASK = '••••••••'`；写入时的规则是：

```python
def val(key):
    v = data.get(key)
    if v == config.MASK or v is None:
        return old.get(key)
    return v
```

即**值为掩码或 None 时保留数据库原值**，只有提交了新值才覆盖。这样前端不需要维护"哪些字段被改动过"的状态，直接把整张表单回传即可。`db.save_config(uid, values)` 实现的是**整行覆盖**：`values` 由 `{col: val(col) for col in db.CONFIG_COLUMNS}` 生成，覆盖全部 21 个配置列。这一设计有两个必须注意的后果：其一，前端**必须回传完整表单**，漏传的字段会被写为 `None` 而不是保持原值；其二，掩码保护只对上述三个敏感字段生效，别的字段传空串就是真的清空。

`iot_port` 单独处理，不参与整行覆盖的兜底逻辑：

```python
port = _to_int(data.get('iot_port'))
if port is None or not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
    port = _to_int(old.get('iot_port'), config.IOT_PORT_DEFAULT)
    if not (config.IOT_PORT_MIN <= port <= config.IOT_PORT_MAX):
        port = config.IOT_PORT_DEFAULT
values['iot_port'] = port
```

即非数字或越界的端口回退到旧值，旧值也非法时再回退到 `IOT_PORT_DEFAULT = 1883`。这道兜底是必要的：`connect_huawei_iot` 内部会做 `int(port)`，若把 `'abc'` 落库，每次重连都会抛异常并静默失败，故障点会离保存动作很远。

保存成功后还有两个副作用同步，都包在独立的 try/except 里，**失败不影响配置保存本身**：把农场名与经纬度同步到当前地块记录（`db.save_active_farm_meta`），以及把本次提交的物联网接入字段同步到当前地块（`db.save_farm_iot`）。坐标同步用 `_COORD_CLEARED` 哨兵区分两种语义——键存在且值为空串表示"真的清空这一维"，键不存在表示"不改动这一维"，避免了只改纬度时把经度一起抹掉。

**`POST /api/save_config` 响应前会调用 `_reconnect_async(uid)`。** 原因是 `connect_huawei_iot` 内部的 broker 连接带 60 秒超时，同步执行会让保存按钮转一分钟；异步重连后接口立刻返回 `{'status': 'success', 'message': '配置已更新'}`。

**`POST /api/diag/<target>`。** 设置页"测试连接"按钮的后端，`target ∈ {'iot', 'weather', 'ai', 'webhook'}`。它做一次**只读**连通性探测：已配置的目标真的发一次请求，未配置的目标直接判定为"未填写"且不发请求。**无论探测结果如何都返回 HTTP 200**，通过响应体里的 `ok` 字段表达成功与否。这一点的理由是：这个接口的语义是"报告状态"，不是"执行操作"，用状态码表达会把"探测失败"误报成"接口调用失败"，前端还得分两种失败路径处理。返回的详情文本截断到 `DETAIL_MAX_LEN = 300` 字符。

### 11.4 数据与监控类接口

**`GET /api/history`。** 参数 `limit` 由 `_parse_limit` 收敛到 `config.HISTORY_MIN_LIMIT = 1` 至 `config.HISTORY_MAX_LIMIT = 5000`，默认 `HISTORY_DEFAULT_LIMIT = 1000`。查询走 `db.query_history(uid, limit, farm_id=db.get_active_farm_id(uid))`，SQL 条件为 `AND (farm_id = ? OR farm_id = 0)`——`farm_id = 0` 那条兼容分支是为了让多地块功能上线前写入的旧数据仍能被看到，否则升级后历史曲线会突然空白。返回结果按时间**反转为升序**后再给前端，直接可画折线。响应行含 `ts`、`water_adc`、`soil_adc`、`do_mgl`、`eh_mv`，其中后两列由迁移 D-01 新增，早期行返回 `None`，前端作图时跳过空点。

**`GET /api/telemetry`。** 返回当前地块的最新一份遥测快照，用于页面刷新或断线重连后**立即恢复界面**。前端 `applySnapshot(data)` 用它一次性填充读数卡、设备状态与 RORI，不必等下一帧 `hw_data` 到来，避免刷新后看到一片 `--`。

**`GET /api/alerts`。** `limit` 范围 1–500（默认 100），`since_ts` 必须为非负数，否则 400 与 `'limit 必须是 1-500 的整数'` 风格的中文提示。底层 `alert_center.list_alerts` 用**严格大于** `ts > ?` 过滤并按 `ORDER BY ts DESC, id DESC` 排序——加 `id` 作次级排序键是为了让同一毫秒内产生的多条告警也有稳定顺序，否则分页会出现重复或漏项。

**`POST /api/alerts/ack` 与 `/api/alerts/ack_all`。** 前者按 `id` 确认单条，用 `rowcount` 判断是否真的改动了行，据此决定返回成功还是"无权操作/不存在"；后者一键确认当前用户的全部未确认告警，供告警中心的"全部确认"按钮使用。

**`GET /api/logs`。** `limit` 范围 1–1000（默认 200），底层 `logbook.query_logs(uid, limit, since_ts)` 从内存写队列落库后的 `logs` 表读取。

**`GET /api/device_status`。** 返回 `heartbeat.get_status(uid)` 的结果：`online` 布尔、`last_seen_ts`、`silent_seconds`、`last_reason`。离线判定阈值为 `heartbeat.DEVICE_OFFLINE_SECONDS = 30` 秒，即超过 30 秒没有上报即视为离线；与前端 6×5 秒 = 30 秒的看门狗阈值对齐。

**`GET /api/forecast` 与 `GET /api/reverse_geocode`。** 详见第十章：预报失败时返回 502 加错误体；逆地理要求同时提供 `lat` 与 `lng`，缺失返回 400，格式错误返回 `'坐标格式错误'`，取不到地名时用 `weather.geo_fallback_text` 生成坐标文本兜底，绝不返回空。

**`POST /api/notify_alert`。** 手动触发一次告警推送，`msg` 截断到 500 字、`level` 截断到 20 字（对应 `config.ALERT_CONTENT_MAX_LEN` 与 `ALERT_LEVEL_MAX_LEN`），空 `msg` 返回 400。推送失败**不算接口失败**：返回 `{'status': 'skipped', 'sent': false}` 加 HTTP 200。这一取舍的理由是，webhook 是外部通道，其可用性不应影响站内闭环——站内弹窗已经提示过用户，钉钉群没收到不该让页面弹一个失败框。

**`POST /api/ai_chat`。** 详见第十章。

### 11.5 洞察与预案类接口

**`POST /api/plan/propose`。** 请求体字段 `question` 必须是字符串（否则 400），长度不超过 500 字（否则 400 与 `'question 过长（最多 500 字）'`），随后调用 `planner.propose_plan(uid, question.strip())`。预案由 AI 生成失败时自动落到规则预案（见第十二章），接口层不区分两者，只把结果原样返回。

**`POST /api/plan/confirm`。** 这是全系统安全等级最高的接口之一——它真的会让水泵或气泵动作。它的校验链条是：`id` 必须是 1..2³¹-1 的整数（否则 400 `'缺少合法的预案 id'`）→ 预案必须属于当前用户 → 预案状态必须是 `pending` → 且未超过 `planner.PLAN_TTL_SECONDS = 600` 秒的时效窗口。任一条不满足都会失败，其中超时的那条会把预案状态置为 `expired` 再返回。逐条下发前，动作还要再过一遍白名单：`ALLOWED_DEVICES = ('air_pump', 'water_pump')`、`ALLOWED_ACTIONS = ('on', 'off')`。

600 秒 TTL 的设计意图是**防止用陈旧决策指挥现场**：AI 预案是基于某一时刻的土壤湿度、溶解氧与降雨预报生成的，如果用户十分钟后才点确认，而这段时间里已经下过雨，执行预案反而有害。超时作废比静默执行安全。失败时接口返回 400；若底层没给出具体原因，路由补一句 `'预案下发失败（设备可能未连接），请稍后重试'`，避免用户面对一个空错误信息。

**`POST /api/plan/reject`。** `id` 同上，可选 `reason` 必须是字符串且不超过 200 字。失败返回 400 与 `'预案不存在、无权操作或状态不允许'`。拒绝与确认一样落入终态，预案不会被重复处理。

**`GET /api/plans`。** `limit` 默认 20、上限 100，按时间倒序。

**`GET /api/metrics`。** `days` 参数默认 7、上限 90（`insight_routes.DEFAULT_METRIC_DAYS` / `MAX_METRIC_DAYS`），返回近 N 日的灌溉用水（升）、气泵/水泵运行时长（分钟）、折算的甲烷减排量与 CO₂ 当量。

**`GET /api/auto_control` 与 `POST /api/auto_control`。** 读/写服务端自动调控开关。`autocontrol.is_enabled` 的默认值是 **False**——即服务端引擎默认不接管。这是刻意的保守默认：服务端自动调控是"页面关闭时的保底"，一旦默认开启就会和前端页面的 `autoControl()` 同时下发指令，两条控制回路互相打架。最小动作间隔 `autocontrol.AUTO_MIN_INTERVAL_SECONDS = 60` 秒同样是为了抑制抖动。

**`GET /api/advice/calendar`。** 返回未来 7 日的雨情与灌溉建议，由 `qinghe/advice.py` 的 `build_calendar(...)` 生成，建议档位有四档：`wait_rain`（等雨）、`watch`（观察）、`irrigate`（建议灌溉）、`hold`（暂缓）。判定用到三个常量：`RAIN_EFFECTIVE_MM = 5.0`（视为有效降雨的日雨量门槛）、`SOIL_GAP_PCT = 3.0`（土壤湿润度与动态下限的差距容差）、`RAIN_TINY_MM = 1.0`（可忽略的小雨门槛）。

### 11.6 导出与地块类接口

**`GET /api/export/history.csv` 与 `/api/export/alerts.csv`。** 响应带 UTF-8 BOM（`BOM = '\ufeff'`），文件名形如 `qinghe_history_<uid>_<毫秒时间戳>.csv`，并设置 `Cache-Control: no-store`。BOM 是必需的：Excel 打开无 BOM 的 UTF-8 CSV 会把中文表头显示成乱码，这是交付后必然收到的一类"bug 报告"，不如在源头解决。单次导出行数上限 `MAX_EXPORT_ROWS = 50000`。

表头由 `_table_columns` 通过 `PRAGMA table_info` **动态探测**，而不是硬编码列名：

```python
HISTORY_HEADER = ['时间', '时间戳', '水位ADC', '土壤ADC', '溶解氧mg/L', '氧化还原电位mV']
ALERTS_HEADER = ['时间', '时间戳', '级别', '类型', '内容', '已确认']
```

动态探测的必要性在于历史库的列是逐步迁移出来的（`do_mgl`、`eh_mv`、`farm_id` 都是后加的），若按固定列名拼 SQL，旧版数据库文件一上来就会报 `no such column`。

**地块接口族。** `GET /api/farms` 列出本人全部地块；`POST /api/farms` 新建；`POST /api/farms/switch` 切换当前地块；`POST /api/farms/update` 更新；`POST /api/farms/delete` 删除。校验规则集中在 `config.py`：名称 1–20 字符、`lat ∈ [-90, 90]`、`lon ∈ [-180, 180]`、面积 0–1,000,000 m²、圈地边界点数 ≤200 且 JSON 串长 ≤20000、单账号地块数上限 `FARM_MAX_COUNT = 12`。删除受一条硬约束保护：**至少保留一块地，不能删除最后一块**——`active_farm_id` 一旦指向不存在的记录，遥测写入与历史查询会同时失去归属，属于难以自愈的状态，因此从接口层直接拒绝。

切换地块是一个有实际副作用的动作：它会改变 `configs.active_farm_id`，进而改变 `/api/history` 的查询范围、`/api/telemetry` 的返回内容、以及 MQTT 的连接参数（物联网接入按地块独立，见第六章）。因此切换成功后前端会重新拉取配置并重建图表数据，而不是复用旧曲线。

**`POST /api/app_send_command` 与指令下发。** App 端下发走 JWT 鉴权，校验比 SocketIO 通道更严：设备名必须在 `PROP_MAP` 之中（否则 400 `'未知设备'`），`action` 必须**精确等于** `'on'` 或 `'off'`（否则 400 `'action 仅支持 on / off'`），设备未连接时返回 `{'status': 'error', 'message': '设备未连接'}`。与 SocketIO 通道"非 on 一律按 off 处理"的宽松策略相比，HTTP 侧选择严格拒绝，因为 App 调用是程序化调用，把拼写错误当成成功下发会让调用方产生"指令已生效"的错误认知，而 SocketIO 侧面对的是人手点击，宽松处理不会造成误解。
