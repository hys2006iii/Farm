# AGENTS.md — 青禾智灌智慧灌溉管理平台 开发规范

> 本文件是仓库的**强制开发契约**。任何 Agent / 开发者在本仓库做改动前必须先读本文件。

## 一、硬性规则（不可协商）

1. **每次改动必须 Git commit**
   - 一次逻辑改动 = 一次提交，禁止把多个不相关改动混在一个提交里。
   - 提交信息格式：`<type>(<scope>): <中文简述>`
     - `type` ∈ `feat` | `fix` | `refactor` | `test` | `docs` | `chore` | `perf` | `style`
     - `scope` 为模块名，如 `api` / `iot` / `ui` / `docs` / `db`
     - 例：`fix(iot): 修复 MQTT 断线重连后订阅丢失`
   - **禁止** `git commit --amend` 覆盖已推送的提交；**禁止** 使用 `git reset --hard` 丢弃他人改动。
   - 交付前工作区必须是干净的（`git status` 无未提交改动）。

2. **每次改动后编写/更新相关测试，交付前确保测试通过**
   - 测试放在 `tests/` 目录，用 `pytest` 运行。
   - 新增/修改任何 API、算法、控制策略、数据表，**必须**同步新增或更新对应测试。
   - 交付前的验收命令（必须全绿）：
     ```bash
     python -m pytest tests -q
     ```
   - 不允许用 `pytest.skip` / 注释掉断言来"让测试通过"。

## 二、工程约定

### 目录结构
```
Farm/
├─ app.py                 # Flask 应用入口（应用装配 + 蓝图注册 + 启动）
├─ qinghe/                # 业务包（按模块拆分，避免单文件膨胀）
│   ├─ __init__.py        # create_app() 应用工厂
│   ├─ config.py          # 配置与常量（阈值、限流、量程标定）
│   ├─ db.py              # SQLite 连接、建表、迁移、DAO
│   ├─ auth.py            # 登录/注册/会话/JWT/限流
│   ├─ iot.py             # MQTT / 华为云 IoTDA 接入与指令下发
│   ├─ irrigation.py      # 灌溉决策：RORI、动态阈值、自动调控
│   ├─ alerts.py          # 告警判定与 webhook 推送
│   ├─ weather.py         # 天气预报、逆地理、气象融合
│   ├─ ai.py              # AI 助手对话代理
│   └─ routes/            # HTTP 蓝图（api_*.py）
├─ templates/             # Jinja2 模板（index.html / login.html）
├─ static/                # 前端静态资源（拆分后的 css/js）
├─ tests/                 # pytest 测试
├─ docs/                  # 设计文档（概要设计、详细设计、材料）
└─ tools/                 # 开发/演示辅助脚本（设备模拟器等）
```

### 代码规范
- Python 3.10+，4 空格缩进，单行 ≤ 120 字符；公共函数必须有中文 docstring。
- **禁止**在 SQL 里用 f-string / `%` 拼接用户输入，一律用参数化 `?`。
- 外部网络调用（天气 / AI / webhook / 逆地理）必须设 `timeout`，且异常不得向上抛到请求栈。
- 所有写接口必须做**入参校验**（类型、范围、长度），非法入参返回 4xx 而不是 500。
- 前端：不使用 `innerHTML` 拼接未转义的用户/设备数据，统一走 `esc()` 或 `textContent`。
- 数据库连接一律用 `with closing(get_db()) as conn:` 或 try/finally 关闭，禁止泄漏。

### 并发与性能
- MQTT 回调用独立线程，禁止在回调里做长耗时阻塞操作；落库走批量/队列。
- 前端定时器必须可清理；图表刷新走统一 tick，禁止多个 `setInterval` 各刷一遍。
- 大数据量列表（历史/日志）必须分页或采样，禁止一次渲染上千 DOM 节点。

### 配置与安全
- 密钥、设备口令、API Key **不得**硬编码进源码，一律从环境变量或数据库读取。
- `FARM_SECRET_KEY`、`FARM_DB_PATH`、`PORT`、`FARM_DEBUG` 为约定环境变量。
- 生产部署必须 `FARM_DEBUG=0`；对外开放时用 `waitress`/`gunicorn` + 反向代理，不用 Werkzeug 调试服务器。

## 三、验收清单（交付前逐条勾选）
- [ ] `git status` 干净，改动均已 commit
- [ ] `python -m pytest tests -q` 全绿
- [ ] 新增/修改功能有对应测试
- [ ] 未引入硬编码密钥
- [ ] 文档（docs/）与代码行为一致
