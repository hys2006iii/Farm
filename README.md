# 青禾智灌 · 智慧灌溉管理平台

基于 **Flask + Flask-SocketIO + SQLite** 的智能灌溉管理系统，面向小型农田 / 试验田 / 校园农业实践场景。
系统通过 **MQTT** 接入 ESP32-E 传感器节点，按 **RORI 风险指数** 与 **动态阈值** 自动决策水泵 / 气泵动作，
并把遥测、告警、运行日志、AI 决策预案与节水减碳核算统一到一块实时看板上。

> 开发契约见 [`AGENTS.md`](AGENTS.md)：每次改动必须 Git commit、必须同步测试、交付前 `pytest` 全绿。

---

## 一、功能一览

### 1. 既有核心功能（说明书已定义）

| 模块 | 说明 |
| --- | --- |
| 实时监控 | 水位 / 土壤湿度 / 溶解氧 / 氧化还原电位四路遥测，SocketIO 秒级推送 |
| 手动控制 | 水泵、气泵远程开 / 关，指令经 MQTT/Topic 下发到 ESP32-E |
| RORI 决策 | 厌氧胁迫风险指数打分，输出满载 / 脉冲 / 待机三档灌溉强度 |
| 动态阈值 | 6 日前馈降雨量修正湿度上下限，雨天放宽灌溉上限 |
| 天气融合 | 逐 6 小时降雨预报 + 逆地理编码，用于前馈与界面展示 |
| AI 助手 | 大模型对话，解释当前工况与建议 |
| 告警推送 | 阈值越界判定 + 钉钉 webhook 推送 |
| 历史曲线 | `sensor_history` 落库与图表回溯 |
| 账户体系 | 账号注册 / 登录 / 会话 / JWT（小程序接口预留） |

### 2. 本轮新增功能（NF1–NF7，已实现并测试）

| 编号 | 功能 | 要点 |
| --- | --- | --- |
| NF1 | 服务端告警中心 | 告警落库、冷却去重、确认（ack）、分页查询、按用户隔离 |
| NF2 | 服务端运行日志 | 异步写队列批量落库，`system/device/auto/manual/plan/config` 六类来源 |
| NF3 | 设备心跳与离线判定 | 遥测即心跳，超 30s 判离线并向页面推 `device_status` 事件 |
| NF4 | AI 决策预案（HITL） | AI 生成可执行动作 → 人工确认 / 驳回 → 再下发，附 600s 有效期 |
| NF5 | 节水与减碳核算 | 按泵运行时长方差估算用水量与 CH₄/CO₂e 减排量 |
| NF6 | 自动调控闭环 | 服务端按 RORI 与动态阈值自动开关泵，默认关闭、60s 最小间隔 |
| NF7 | 数据导出 | 历史数据 / 告警列表导出 CSV（BOM，Excel 可直接打开） |

新增 HTTP 接口 13 个（预案 4、指标 1、自动调控 1、告警 2、日志 1、设备状态 1、导出 2、告警推送 1），
接口明细见 [`docs/20_概要设计说明书.md`](docs/20_概要设计说明书.md) 4.2 节。

---

## 二、系统架构

```
浏览器（Jinja2 模板 + 原生 JS 模块化 + Chart.js）
        │  HTTP /api/*            │  WebSocket(SocketIO, threading 模式)
        ▼                        ▼
┌───────────────────────────────────────────────┐
│ Flask 应用（waitress 生产承载，多线程）        │
│  qinghe/routes/*  蓝图层（8 个蓝图）           │
│  qinghe/{auth,iot,irrigation,alerts,weather,ai}│
│  qinghe/{alert_center,logbook,heartbeat,       │
│          planner,metrics,autocontrol} 新模块   │
│  qinghe/db.py  SQLite（WAL、参数化、连接池化） │
└───────────────────────────────────────────────┘
        │ MQTT（paho-mqtt 后台线程）
        ▼
ESP32-E 节点（D7/D9 水泵、D5 气泵 PWM、A0 水位、A2 土壤、A4 DO、A6 Eh）
        │
        └── 华为云 IoTDA（Topic: /esp32e/data、/esp32e/cmd）
```

- 后端按模块拆包，`app.py` 只剩装配入口（约 20 行）。
- 前端拆分为 `static/js/{core,store,charts,irrigation,config,ai,weather,realtime,insight,app}.js`
  与 `static/css/{base,dashboard,login,modal,insight}.css`，`templates/index.html` 从 1616 行降到 339 行。
- 遥测回调线程内做「心跳 → 上下文 → 泵时长 → 自动调控 → 告警判定」旁路，每个子系统独立 try/except，
  任一失败不影响主链路落库与推送。

---

## 三、快速开始

### 1. 安装依赖

```bash
python -m pip install -r requirements.txt
```

要求 Python 3.10+（开发验证于 3.14）。

### 2. 配置环境变量

```bash
python tools/gen_secret.py          # 生成随机密钥，写入 .env 提示值
```

`.env.example` 列出全部约定变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `FARM_SECRET_KEY` | 内置兜底值 | 会话签名密钥，**生产必须设置** |
| `FARM_DB_PATH` | `qinghe.db` | SQLite 文件路径 |
| `PORT` | `5000` | 监听端口 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `FARM_DEBUG` | `0` | 生产必须为 `0` |
| `FARM_THREADS` | `8` | waitress 工作线程数 |

### 3. 开发模式运行

```bash
python app.py                       # 或 run.bat
```

### 4. 生产模式运行（推荐，校园网内他人访问）

```bash
python server.py                    # 或 start_server.bat
```

启动横幅会打印本机地址与**局域网地址**（如 `http://10.113.158.198:5000`），
同一路由器 / 同一 WiFi 下的同学用该地址即可访问。
防火墙放行、跨网段、AP 隔离、实名认证环境的排查方法见
[`docs/部署说明_校园网服务器.md`](docs/部署说明_校园网服务器.md)（三种典型拓扑 A/B/C）。

---

## 四、测试

```bash
python -m pytest tests -q           # Python 侧全量
npm run test:js                     # 前端纯函数（node --test，需 Node 18+）
```

- Python 用例覆盖：鉴权与限流、配置读写、遥测解析与落库、RORI 与动态阈值、告警判定与推送、
  预案状态机、自动调控、指标核算、CSV 导出、SocketIO 事件、部署脚本静态检查。
- 前端用例抽出纯函数（`computeRori`、分级、动态阈值、仪表盘格式化等）做无浏览器测试。
- 交付验收命令（AGENTS.md）：`python -m pytest tests -q` 必须全绿。

---

## 五、目录结构

```
Farm/
├─ app.py                 # 开发入口（装配 qinghe，启动 werkzeug/socketio）
├─ server.py              # 生产入口（waitress + socketio threading 模式 + 局域网地址横幅）
├─ qinghe/                # 业务包
│  ├─ __init__.py         # create_app() 应用工厂、蓝图注册、安全响应头
│  ├─ config.py           # 常量与阈值（不依赖其他子模块）
│  ├─ db.py               # SQLite 连接、建表迁移、DAO
│  ├─ auth.py             # 登录/注册/会话/JWT/限流
│  ├─ iot.py              # MQTT 接入、遥测解析、指令下发、遥测旁路编排
│  ├─ irrigation.py       # RORI 与动态阈值算法
│  ├─ alerts.py           # 阈值告警判定与 webhook
│  ├─ weather.py          # 天气预报与逆地理
│  ├─ ai.py               # AI 对话代理
│  ├─ alert_center.py     # NF1 告警中心
│  ├─ logbook.py          # NF2 运行日志
│  ├─ heartbeat.py        # NF3 设备心跳/离线巡检
│  ├─ planner.py          # NF4 AI 决策预案
│  ├─ metrics.py          # NF5 节水减碳核算
│  ├─ autocontrol.py      # NF6 自动调控
│  ├─ realtime.py         # SocketIO 事件与设备状态推送
│  └─ routes/             # 8 个蓝图：app/auth/config/data/ai/insight/export/monitor
├─ templates/             # index.html / login.html
├─ static/                # css/ + js/ 前端资源
├─ tests/                 # pytest 用例 + js/ 前端用例
├─ docs/                  # 设计文档与交付材料
├─ tools/                 # gen_secret.py 等辅助脚本
└─ *.bat                  # run/start_server/stop_server/firewall_allow 运维脚本
```

---

## 六、文档索引

| 文档 | 内容 |
| --- | --- |
| [`docs/10_项目设计材料_设计主题功能与创新点.md`](docs/10_项目设计材料_设计主题功能与创新点.md) | 设计主题、系统功能、创新点、实现思路与技术方法（课程材料） |
| [`docs/20_概要设计说明书.md`](docs/20_概要设计说明书.md) | 总体架构、模块划分、接口关系、数据结构、数据流（12 张架构/时序/流程图） |
| [`docs/30_详细设计说明书.md`](docs/30_详细设计说明书.md) | 各模块内部实现、数据结构、算法（含 RORI / 动态阈值 / 节水减碳三个数值算例）、接口细节 |
| [`docs/部署说明_校园网服务器.md`](docs/部署说明_校园网服务器.md) | 校园网三种拓扑、启动/停止/防火墙脚本、常见故障排查表 |
| [`docs/40_测试与验收报告.md`](docs/40_测试与验收报告.md) | 测试用例统计、端到端冒烟记录、缺陷清单与修复台账 |
| [`docs/_materials_digest.md`](docs/_materials_digest.md) | 说明书 / 用户手册 / 申请表的原始资料提取与缺口分析 |

---

## 七、硬件与协议约定

| 项目 | 约定 |
| --- | --- |
| 主控 | ESP32-E |
| 执行器 | D7 + D9 水泵，D5 气泵（PWM 5 kHz / 8 bit） |
| 传感器 | A0 水位、A2 土壤湿度、A4 溶解氧、A6 氧化还原电位 |
| 上报 Topic | `/esp32e/data`（自有 Broker）；华为云 `$oc/devices/{device_id}/sys/properties/report` |
| 下发 Topic | `/esp32e/cmd`；华为云 `$oc/devices/{device_id}/sys/properties/set/#` |
| RORI 权重 | ω₁=ω₂=0.35、ω₃=0.30、γ=0.5；分级 ≥70 满载 / 40–70 脉冲 / <40 待机 |
| 边缘强控红线 | Eh ≤ −100 mV 或 DO ≤ 1.5 mg/L 时强制启动气泵（固件侧，当前为设计约束） |

---

## 八、许可与致谢

课程设计项目，仅供学习与校园实践使用。第三方依赖见 `requirements.txt` 与 `package.json`。
