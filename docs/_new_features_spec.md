# 新增功能规格（权威契约）

> 本文件是「新增功能」的唯一契约来源。实现方与设计文档撰写方都必须以本文件为准。
> 基线：`qinghe/` 包（已重构完成）。已有能力：`compute_rori/classify_rori/compute_dynamic_threshold/decide_control`（irrigation.py）、`evaluate_alerts/AlertDeduper/notify_webhook`（alerts.py）、`HistoryWriter` 批量落库（iot.py）。

## 通用约定（所有新增功能必须遵守）

1. **不得修改**以下既有文件：`app.py`、`qinghe/config.py`、`qinghe/db.py`、`qinghe/__init__.py`、`qinghe/routes/__init__.py`、`qinghe/iot.py`、`qinghe/auth.py`、`qinghe/irrigation.py`、`qinghe/alerts.py`、`qinghe/weather.py`、`qinghe/ai.py`、`qinghe/realtime.py`。集成由 Lead 统一完成。
2. 新表一律**懒建**：每个新模块自带 `_ensure_schema()`，用模块级 `_schema_ready` 标志 + `threading.Lock()` 保证只建一次，`CREATE TABLE IF NOT EXISTS`，在**每个公开函数的入口**调用。不要改 `db.py`。
3. 数据库连接一律 `with closing(get_db()) as conn:`（从 `qinghe.db` 导入），禁止泄漏。
4. 所有外部调用必须带 `timeout`，异常不得抛给请求栈（返回结构化错误）。
5. 所有新增 HTTP 接口必须做入参校验，非法入参返回 4xx。
6. 蓝图变量名统一为 `bp`，蓝图文件放在 `qinghe/routes/`，**不要**去改 `routes/__init__.py`（Lead 负责注册）。
7. 每个模块必须有中文 docstring；每个公开函数有中文 docstring；单行 ≤120 字符。
8. 新模块必须有对应 `tests/` 用例，且**不得**修改 `tests/conftest.py`。测试用 monkeypatch 把 `qinghe.config.DB_PATH` 指到临时文件，或直接依赖既有 conftest fixture（先读 conftest.py 再决定）。
9. 所有新功能在**未配置外部密钥 / 无网络**时必须优雅降级并能被测试覆盖。

---

## NF1 服务端告警中心（Alert Center）

**文件**：`qinghe/alert_center.py`

**表** `alerts`：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| user_id | INTEGER NOT NULL | |
| ts | INTEGER NOT NULL | 毫秒时间戳 |
| level | TEXT NOT NULL | `info` / `warning` / `danger` |
| code | TEXT NOT NULL | 告警类型码，见下 |
| content | TEXT NOT NULL | 告警正文，≤500 字符 |
| acked | INTEGER DEFAULT 0 | 0 未确认 / 1 已确认 |

索引：`CREATE INDEX IF NOT EXISTS idx_alerts_user_ts ON alerts(user_id, ts)`

**告警类型码 code**：`soil_low`、`soil_high`、`water_low`、`water_high`、`rori_medium`、`rori_high`、`device_offline`、`plan_pending`、`auto_action`

**公开函数**：
- `push_alert(uid: int, level: str, code: str, content: str) -> dict`
  去重（同一 `(uid, code, 归一化正文)` 在 `config.ALERT_COOLDOWN_SECONDS` 内只落一条）→ 落库 → 异步推送 webhook（`notify_webhook`，失败重试 2 次，退避 0.5s/1.0s，最终失败仅记录不抛）。返回 `{'id':..., 'deduped': bool, 'pushed': bool}`。
- `list_alerts(uid: int, limit: int = 100, since_ts: int = 0) -> list[dict]`
  返回按 `ts DESC` 排序，字段 `rid, id, ts, level, code, content, acked`（`rid` 为 1 基序号）。
- `ack_alert(uid: int, alert_id: int) -> bool` 只能确认自己的告警。
- `prune_alerts(keep_days: int = 7) -> int` 返回删除行数。
- `evaluate_and_push(uid: int, soil_pct, water_mm, rori, humi_lower, humi_upper, water_lower, water_upper) -> list[dict]`
  调用 `alerts.evaluate_alerts(...)` 拿到候选，逐个 `push_alert`，返回本次真正新增的告警列表。

---

## NF2 运行日志服务端化（Logbook）

**文件**：`qinghe/logbook.py`

**表** `logs`：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| user_id | INTEGER NOT NULL | |
| ts | INTEGER NOT NULL | 毫秒 |
| level | TEXT NOT NULL | `info`/`warning`/`error` |
| source | TEXT NOT NULL | `system`/`device`/`auto`/`manual`/`plan`/`config` |
| message | TEXT NOT NULL | ≤500 字符 |

索引：`CREATE INDEX IF NOT EXISTS idx_logs_user_ts ON logs(user_id, ts)`

**公开函数**：
- `add_log(uid: int, message: str, level: str = 'info', source: str = 'system') -> None`
  写入**模块级队列**，由单个守护线程每 1.0s 或积攒 ≥20 条时批量 `executemany` 落库；队列满（1000）丢弃最旧并计数。不得阻塞调用方。
- `flush_logs(timeout: float = 2.0) -> None` 测试与退出时强制刷盘。
- `query_logs(uid: int, limit: int = 200, since_ts: int = 0) -> list[dict]`
  按 `ts DESC`，字段 `rid, ts, level, source, message`。
- `prune_logs(keep_days: int = 7) -> int`

---

## NF3 设备心跳与离线判定（Heartbeat）

**文件**：`qinghe/heartbeat.py`

**表** `device_status`：
| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | INTEGER PK | |
| last_seen_ts | INTEGER NOT NULL | 毫秒 |
| online | INTEGER NOT NULL DEFAULT 0 | |
| last_reason | TEXT DEFAULT '' | 最近一次上下线原因 |

**公开函数**：
- `mark_seen(uid: int, ts: int = None) -> None` 收到任意上报即刷新（若由离线转在线，写日志 `device` 源 + 推送 `info` 告警恢复可不推）。
- `get_status(uid: int, offline_seconds: int = None) -> dict`
  返回 `{'online': bool, 'last_seen_ts': int, 'silent_seconds': int}`；`silent_seconds > config.DEVICE_OFFLINE_SECONDS`（新增常量放本模块，默认 30）即判离线。
- `sweep_offline(uids: list[int]) -> list[int]` 批量判定并落 `online` 字段，返回本次**变为离线**的用户 id 列表。
- `start_watcher(get_uids, emit, interval: float = 5.0) -> threading.Thread`
  守护线程周期性扫描（`get_uids()` 返回当前所有有配置的 user_id，`emit(uid, event)` 用于推 SocketIO），退出用 `stop_watcher()`。**默认不自动启动**，由 Lead 在 `create_app` 中决定。

---

## NF4 AI 决策预案闭环（Human-in-the-Loop Planner）

**文件**：`qinghe/planner.py`

**表** `plans`：
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| user_id | INTEGER NOT NULL | |
| ts | INTEGER NOT NULL | |
| status | TEXT NOT NULL DEFAULT 'pending' | `pending`/`confirmed`/`rejected`/`expired`/`failed` |
| context_json | TEXT NOT NULL | 感知上下文快照 |
| reasoning | TEXT NOT NULL DEFAULT '' | 思维链推理文本 |
| proposal_json | TEXT NOT NULL | `{'actions':[{'device','action','reason'}], 'summary','risk'}` |
| decided_ts | INTEGER | 确认/拒绝时间 |
| apply_result | TEXT DEFAULT '' | 下发结果 JSON |

索引：`CREATE INDEX IF NOT EXISTS idx_plans_user_ts ON plans(user_id, ts)`

**公开函数**：
- `build_context(uid: int) -> dict`
  汇总：`rori`、`rori_level`(code/name)、`water_mm`、`soil_pct`、`do_mgl`、`eh_mv`、`air_pump`、`water_pump`、`p6d`、`alpha`、`eff_lower`、`eff_upper`、`manual_mode`、`ts`。数据来源：最近一次遥测缓存（本模块维护 `_latest[uid]` 字典，提供 `update_telemetry(uid, **kw)` 供 Lead 在 iot 回调里调用）+ `db.load_thresholds` + `weather` 最近预报（可选，失败则为 None）。
- `propose_plan(uid: int, question: str = '') -> dict`
  1) 若配置了 `ai_key`：把 `build_context` 结果序列化进 prompt，要求模型**只输出 JSON**（`reasoning` + `actions` + `summary` + `risk`），`timeout=25`，解析失败则回退规则方案。
  2) 否则（无 key / 调用失败）：**规则回退方案**——用 `irrigation.decide_control(...)` 生成 actions，`reasoning` 写明确规则依据（RORI 分级 + 水位滞回 + 降雨前馈）。
  落 `plans` 表（status=pending）并返回 `{'plan_id','status','reasoning','actions','summary','risk','ai_used': bool}`。
- `confirm_plan(uid: int, plan_id: int) -> dict` 校验归属与 `status=='pending'`、**过期判定**（超过 `PLAN_TTL_SECONDS=600` 置 `expired` 并拒绝）→ 逐条 `iot.send_property_command`（只允许 `air_pump`/`water_pump` 与 `on`/`off`）→ 写日志（source=`plan`）+ 告警（code=`auto_action`）→ 更新 status。返回 `{'ok','applied':[...], 'failed':[...]}`。
- `reject_plan(uid: int, plan_id: int, reason: str = '') -> bool`
- `list_plans(uid: int, limit: int = 20) -> list[dict]`

---

## NF5 节水减碳看板（Metrics）

**文件**：`qinghe/metrics.py`

**表** `pump_runtime`：
| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | INTEGER | |
| device | TEXT | `air_pump`/`water_pump` |
| day | TEXT | `YYYY-MM-DD`（本地时区） |
| seconds | INTEGER DEFAULT 0 | 当日累计运行秒数 |
| PRIMARY KEY(user_id, device, day) | | |

**公开函数**：
- `note_pump_state(uid: int, device: str, state: str, ts: int = None) -> None`
  状态去重累加：内部 `_last[uid][device] = (state, ts)`，状态切换时把上一段时长累加进 `pump_runtime`。`state` 只接受 `on/off`。
- `estimate(uid: int, days: int = 7) -> dict`
  返回 `{'days': n, 'water_liters': float, 'pump_minutes': float, 'air_minutes': float, 'ch4_saved_g': float, 'co2e_saved_g': float, 'method': str}`
  估算口径（**工程估算，非实测，必须写进返回值与文档**）：
  - 灌溉用水量 = 水位抬升体积估算：`water_liters = Σ (Δwater_mm /1000) * CHANNEL_AREA_M2 * 1000`，`CHANNEL_AREA_M2` 默认 `0.5`，可由环境变量 `FARM_CHANNEL_AREA_M2` 覆盖。
  - 增氧时长 = `air_pump` 当日秒数 / 60。
  - 甲烷减排 = `air_minutes / 60 * CH4_SAVED_G_PER_HOUR`，默认 `0.8 g/h`（环境变量 `FARM_CH4_SAVED_G_PER_HOUR` 可覆盖）。
  - `co2e_saved_g = ch4_saved_g * 28`（GWP100=28）。
- `daily_series(uid: int, days: int = 7) -> list[dict]` 逐日返回 `{'day','water_liters','pump_minutes','air_minutes','ch4_saved_g','co2e_saved_g'}`。

---

## NF6 数据导出（Export）

**文件**：`qinghe/routes/export_routes.py`（蓝图 `bp`）

- `GET /api/export/history.csv`
  查询 `sensor_history`（可按 `?limit=` 与 `?since_ts=`），**流式**返回 `text/csv; charset=utf-8`，带 UTF-8 BOM（`\ufeff`），表头 `时间,时间戳,水位ADC,土壤ADC,溶解氧mg/L,氧化还原电位mV`（若列不存在则留空）。文件名 `qinghe_history_<uid>_<ts>.csv`。
- `GET /api/export/alerts.csv` 导出告警（字段同上风格：`时间,时间戳,级别,类型,内容,已确认`）。

---

## NF7 服务端自动调控引擎（可选托管）

**文件**：`qinghe/autocontrol.py`

**表** `auto_control`：`user_id INTEGER PK, enabled INTEGER DEFAULT 0, last_action_ts INTEGER DEFAULT 0, state_json TEXT DEFAULT ''`

**公开函数**：
- `set_enabled(uid: int, enabled: bool) -> None`
- `is_enabled(uid: int) -> bool`（**默认 False**，避免与前端 JS 自动调控重复下发）
- `evaluate(uid: int, telemetry: dict) -> list[dict]`
  仅当 enabled 时工作：用 `irrigation.decide_control` 得目标动作 → **滞回**：同一设备两次动作间隔 < `AUTO_MIN_INTERVAL_SECONDS`（默认 60）则跳过 → 下发并写日志，返回实际下发的动作列表。
- `status(uid: int) -> dict` `{'enabled','last_action_ts','state'}`

---

## 接口汇总（Lead 负责注册蓝图后的最终形态）

| 方法 | 路径 | 归属 | 说明 |
|---|---|---|---|
| GET | `/api/alerts` | NF1 | `?limit=100&since_ts=0` |
| POST | `/api/alerts/ack` | NF1 | body `{'id': int}` |
| GET | `/api/logs` | NF2 | `?limit=200&since_ts=0` |
| GET | `/api/device_status` | NF3 | 返回 online/last_seen_ts/silent_seconds |
| POST | `/api/plan/propose` | NF4 | body `{'question': '可选'}` |
| POST | `/api/plan/confirm` | NF4 | body `{'id': int}` |
| POST | `/api/plan/reject` | NF4 | body `{'id': int, 'reason': '可选'}` |
| GET | `/api/plans` | NF4 | `?limit=20` |
| GET | `/api/metrics` | NF5 | `?days=7` |
| GET | `/api/export/history.csv` | NF6 | CSV 下载 |
| GET | `/api/export/alerts.csv` | NF6 | CSV 下载 |
| GET | `/api/auto_control` | NF7 | 查询开关 |
| POST | `/api/auto_control` | NF7 | body `{'enabled': bool}` |

**鉴权**：全部沿用现有会话登录（`session['user_id']`），未登录返回 401 JSON。
