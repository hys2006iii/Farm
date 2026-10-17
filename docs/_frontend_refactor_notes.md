# 前端重构说明（模板拆分 · 性能治理 · XSS 修复）

> 对应共享任务 **task-2**。本文件记录拆分前后的量化对比、性能治理逐条改法、XSS 改动清单与页面回归自测清单。
> 所有结论基于真实执行结果（`node --test`、Flask test_client 渲染、静态资源 200 校验），非估算。

---

## 一、拆分前后对比

### 1.1 模板行数

| 文件 | 拆分前 | 拆分后 | 变化 |
| --- | ---: | ---: | --- |
| `templates/index.html` | 1616 | **339** | −1277（−79.0%） |
| `templates/login.html` | 210 | **68** | −142（−67.6%） |

`index.html` 现为纯结构（HTML 骨架 + Jinja 变量 + 资源引用），已满足「< 350 行」验收项。

### 1.2 新增静态资源

| 文件 | 行数 | 职责 |
| --- | ---: | --- |
| `static/css/base.css` | 172 | CSS 变量、topbar、footer、通用按钮/卡片/toast |
| `static/css/dashboard.css` | 87 | 面板、传感器网格、RORI、阈值滑块、图表容器、响应式 |
| `static/css/modal.css` | 72 | 配置弹窗、改密弹窗、AI 对话弹窗 |
| `static/css/login.css` | 82 | 登录/注册页（原 login.html 内联样式） |
| `static/js/core.js` | 232 | 全局状态、工具函数、**统一 tick 调度器**、DOM 批量更新队列 |
| `static/js/store.js` | 191 | localStorage 内存态 + 节流批量落盘 + 容量上限 |
| `static/js/charts.js` | 209 | Chart.js 初始化与统一刷新 |
| `static/js/irrigation.js` | 143 | `computeRori` / `classifyRori` / `computeDynamicThreshold`（纯函数） |
| `static/js/realtime.js` | 372 | SocketIO 连接、消息分发、心跳、告警巡检、RORI |
| `static/js/config.js` | 217 | 配置弹窗读写、阈值滑块、模式切换、改密 |
| `static/js/ai.js` | 57 | AI 对话 |
| `static/js/weather.js` | 241 | 天气 / 6 日预报 / 逆地理 / 阈值融合提示 |
| `static/js/app.js` | 215 | 启动引导、tick 任务注册、日志与告警增量渲染 |
| `static/js/login.js` | 91 | 登录/注册（原 login.html 内联脚本） |

### 1.3 加载顺序

`index.html` 底部统一用 `defer` 引用，`defer` 保证按书写顺序执行：

```
core → store → charts → irrigation → config → ai → weather → realtime → app
```

`core.js` 必须最先（提供 `QH` / `S`），`app.js` 必须最后（启动引导）。`login.js` 为独立 IIFE，仅依赖 `window`，与主应用无耦合。

Jinja 变量保留方式：`<body data-username="{{ username }}">`，另有配置弹窗内的 `value="{{ username }}"` 未改动。

---

## 二、性能与卡顿治理（问题 → 改法 → 预期收益）

### 2.1 定时器合并为统一 tick 调度器

- **问题**：拆分前存在多个独立 `setInterval`（心跳、时钟、图表各自一套），互相叠加触发重排，定时器无法统一清理。
- **改法**：`core.js` 提供唯一主循环 `startTicker()`（`TICK_MS = 500`）+ `registerTask(name, everyMs, fn)` 分频注册；`app.js` 注册 5 个任务：

  | 任务 | 分频 | 职责 |
  | --- | ---: | --- |
  | `dom` | 500ms | `flushDom()` 批量刷写 |
  | `clock` | 1s | 顶栏日期与时钟 |
  | `chart` | 2s | 图表刷新 + 追加趋势点 |
  | `heartbeat` | 5s | 心跳检测 + 告警巡检 |
  | `persist` | 30s | 趋势/日志/告警批量落盘 |

- **收益**：全页面只剩 **1 个 `setInterval`**（已实测断言通过）；单任务抛异常被 `try/catch` 吞掉，不拖垮主循环。

### 2.2 MQTT 消息合并为批量 DOM 更新

- **问题**：SocketIO 每收到一条 MQTT 消息（3 秒一条，多设备更高频）就立即写 DOM + 调 `updateRori()` + 可能 `pushChartPoint()`，消息密集时反复重排。
- **改法**：`core.js` 维护 `pending` 队列（`fields` / `styles` / `pumps` / `flags` / `sliders`）。`realtime.js` 的 `hw_data` 回调**只解析入队**，由 `dom` 任务每 500ms 合并成一次 `flushDom()`。`setText` / `setStyle` / `setAttr` / `toggleClass` 均带**值比对短路**（`el.__qhText` 等缓存），值没变直接 return。
- **收益**：实测「100 次入队 → 1 次 DOM 写」；同值重复推送写 DOM 次数为 **0**。

### 2.3 图表刷新节流

- **问题**：每条消息调一次 `chart.update()`，且带默认过渡动画。
- **改法**：`charts.js` 中 `chart.update('none')` 关闭过渡；`Chart.defaults.animation = false`；每个图表配置 `animation: false` + `parsing: false` + `normalized: true`；仅由 `chart` 任务（2s）在 `S.chartDirty` 为真时刷新；数据点超上限用 `shift()` 弹出而非整数组重建；渲染前按 `CHART_LIMIT = 300` 抽样。
- **收益**：图表重绘频率由「每条消息」降到 **0.5 次/秒**，且无动画过渡开销。

### 2.4 localStorage 写入节流 + 容量上限

- **问题**：`farmTrend` / `farmTrendRori` / `farmLogs` / `farmAlerts` 每次都是「读全量 → 改 → 写全量」，数据增长后 `JSON.parse` / `stringify` 阻塞主线程。
- **改法**：`store.js` 以**内存态为唯一数据源**（`mem`），写操作只改内存 + 置脏标记，真正的落盘由 `persist` 任务每 **30s** 批量执行（`FLUSH_MS = 30000`）；页面 `pagehide` / `beforeunload` 时强制 flush 兜底。硬上限：趋势 **2000 点**、日志 **500 条**、告警 **200 条**，超限裁剪；另有时间保留窗（趋势 3 天、日志/告警 24 小时）。
- **收益**：实测 600 条日志仅保留 500 条且 `pushLog` 期间 **0 次** localStorage 写入；落盘次数由「每次写入」降到 **每 30s 一次**。

### 2.5 列表增量渲染

- **问题**：`renderLogs` / `renderAlerts` 每次全量重建 DOM。
- **改法**：首次渲染全量，之后按 `__qhFirstTs` 时间戳**增量 prepend** 新节点（`DocumentFragment` 一次性插入），并裁剪尾部超出上限的节点；渲染上限 `LOG_RENDER_MAX = 60`、`ALERT_RENDER_MAX = 30`。告警首次出现时移除「暂无告警记录」占位。
- **收益**：新增 1 条日志的 DOM 操作从「重建 N 个节点」降为「插入 1 个节点」。

### 2.6 首屏与 CLS

- **改法**：两个 CDN 脚本（socket.io 4.7.1、Chart.js 4.4.1）加 `defer crossorigin="anonymous" referrerpolicy="no-referrer"`；图表容器 `.chart-box` 使用固定高度，避免 canvas 初始化引起布局抖动。
- **收益**：CDN 脚本不再阻塞 HTML 解析，图表区域无 CLS 抖动。

---

## 三、XSS 改动清单

拆分前 `index.html` 内联脚本中有 16 处 `innerHTML`。拆分后**业务代码中 `innerHTML` 出现次数为 0**（仅注释中提及，已用 grep 全量核对 `static/js/*.js` + `templates/*.html`，无 `innerHTML` / `insertAdjacentHTML` / `outerHTML` / `document.write` 实际调用）。

| # | 原位置 | 数据来源 | 改法 |
| --- | --- | --- | --- |
| 1 | `cloudStatus` 状态点 | 无（静态文案） | `textContent = ''` + `createElement('span')` 拼装 |
| 2 | `deviceStatusPill` 状态点 | 无 | 同上 |
| 3 | `roriStatus` 等级名 + 策略 | 本地计算 | `textContent` + `appendChild(document.createElement('br'))` |
| 4 | 阈值融合提示条 | **天气接口** | 改为 DOM 节点构建（`createTextNode` / `createElement('b')`） |
| 5 | 6 日预报卡片 | **天气接口 `fxDate` / `precip`** | 每张卡片 `createElement` + `textContent`，日期不再拼接 |
| 6 | 预报摘要条 | 天气接口派生值 | DOM 节点构建 |
| 7 | 预报错误提示 | **天气接口 `d.error`** | `div.textContent = text`（原为 `innerHTML` 裸拼） |
| 8 | 运行日志列表 | **设备 MQTT `log` 主题 payload** | `makeLogNode()`：`span.textContent = l.msg` |
| 9 | 告警列表 | 设备数据 + 阈值派生 | `makeAlertNode()`：全部 `textContent` |
| 10 | AI 对话气泡 | **AI 接口返回 `message.content`** | `div.textContent = data.choices[0].message.content` |
| 11 | toast 提示 | 告警文本 | `el.textContent = String(msg)` |
| 12 | 逆地理名称 | **逆地理接口 `d.name`** | `QH.setText(locDisplay, name)`（原为拼接） |
| 13 | 温度显示 | **Open-Meteo 接口** | `QH.setText(tempDisplay, ...)` |
| 14 | 湿度显示 | Open-Meteo 接口 | `QH.setText(humidityDisplay, ...)` |
| 15 | 阈值滑杆数值 | 后端阈值接口 | `QH.setText(humiDownVal, ...)` 等 4 处 |
| 16 | 时钟显示 | 无 | `QH.setText(sysDate / sysTime, ...)` |

**兜底**：`core.js` 保留 `esc()`（转义 `& < > " '`）并在 `globalThis` 上导出，供后续任何必须拼接 HTML 的场景使用；测试覆盖 `<script>` 与引号转义。

> 说明：`{{ username }}` 由 Jinja2 自动转义后输出，属服务端已转义路径，未改动。

---

## 四、登录页修复

| 问题 | 改法 |
| --- | --- |
| `handleRegister` 的 `fetch` 无 `.catch`，网络异常时静默无反馈 | 补 `.catch` → `alert('网络异常，请检查后端服务是否在线')` |
| 登录/注册按钮可重复点击造成重复提交 | 新增 `lockButton(id, locked, lockedText, normalText)`，提交期间 `disabled = true` 且文案切为「登录中...」/「注册中...」，成功或失败后恢复 |
| `handleLogin` 同样缺 `.catch` | 一并补上 |

---

## 五、测试

新增 `tests/js/irrigation.test.mjs`（Node 内置 `node --test`，零依赖，不引入 jest/vitest）。

```bash
node --test "tests/js/**/*.test.mjs"   # 等价于 npm run test:js
```

覆盖范围（**28 passed / 0 failed**，实测）：

- `computeRori`：ADC=0、ADC=4095、中间值 2048（含手工复算）、NaN/undefined/非数字、超量程夹逼、水位 5mm 死区、DO 边界 0 / 8.0 / >8、Eh 边界 −150 / 300。
- `classifyRori`：边界 0 / 39.99 / 40 / 69.99 / 70 / 100，等级名与策略文案，NaN/负值回退。
- `computeDynamicThreshold`：无预报回退、非数组入参回退、P6d=0 / 10 / 50 / 100 各分段、分段切换点（10↔10.01、50↔50.01）、6 日衰减权重累加、超过 6 条只取前 6 条、45% 下限保底、上限放宽 95% 与 100% 天花板、precip 非法值按 0 计、基础阈值缺省回退 40/80。
- `esc()`：`<script>` 标签、单双引号、`&`、null/undefined/数字降级、中文不改动。

> 注：`core.js` 是浏览器 IIFE（不导出 `module.exports`），测试用最小 `document` / `localStorage` 桩加载后从 `globalThis.esc` 取值，**未为测试改动任何业务逻辑**。
>
> 与后端 `qinghe/irrigation.py` 的常量已逐项核对一致：`EFF_LOWER_FLOOR = 45.0`、`EFF_UPPER_RAIN = 15.0`、`EFF_UPPER_BONUS = 15.0`、`EFF_UPPER_CAP = 100.0`、`H_ROOT = 200.0`、`RAIN_WEIGHTS = [1.0, 0.9, 0.7, 0.5, 0.4, 0.3]`。注意「有效下限」始终受 45% 保底约束，因此基础下限 40% 时 `effLower` 也为 45%。

---

## 六、页面回归自测清单（人工验证）

### 6.0 前置

```bash
python app.py            # 或 python server.py
```

浏览器打开对应地址 → 注册/登录 → 进入监控中心。打开 DevTools Console，**全程应无报错**。

### 6.1 结构完整性

- [ ] 传感器 **6 个数值格**齐全：渠道水位 / 土壤湿度 / 根区溶解氧 / 根区氧化还原电位 / 气泵状态 / 水泵状态
- [ ] RORI 区域显示指数 + 分级说明
- [ ] 未来 6 日降雨量预测区显示 6 张卡片 + 摘要条
- [ ] 告警记录列表存在（空时有「暂无告警记录」）
- [ ] 手动调控区：气泵/水泵各 2 个按钮 + 模式切换按钮
- [ ] 阈值滑块 2 组（土壤湿度、渠道水位），各含下限/上限双滑块
- [ ] 运行日志列表存在
- [ ] 实时趋势区 **3 个图表**（水位、土壤湿度、RORI）
- [ ] 顶栏：AI 助手 / 系统设置 / 智能洞察 按钮、华为云与传感器状态点、日期与时钟（每秒走动）

### 6.2 三个弹窗

- [ ] 「系统设置」弹窗可打开，14 个配置项 + 农场名称/经纬度齐全，「保存设置」有反馈，「退出登录」可用
- [ ] 弹窗内「修改密码」可打开改密弹窗，可取消
- [ ] 「AI 助手」弹窗可打开，可输入并发送，气泡正常追加

### 6.3 交互

- [ ] 手动/自动模式切换：按钮文案与颜色变化，手动组可用性同步切换
- [ ] 拖动阈值滑块：数值标签实时跟随，下限不得越过上限，融合提示条同步刷新
- [ ] 「应用参数」有成功提示
- [ ] 图表「柱状图 / 折线图」切换生效

### 6.4 实时数据

- [ ] 设备上报后 6 个数值格刷新，RORI 数值与颜色随分级变化
- [ ] 趋势图每 2s 刷新一次，无动画闪烁
- [ ] 断网/停设备：约 **20s** 后状态点转红、显示「设备离线」（`heartbeatMissLimit = 4` × 5s）
- [ ] 恢复上报后自动回到在线

### 6.5 性能与存储

- [ ] DevTools Performance 录制 10s：主线程无长任务堆积，无持续 layout thrashing
- [ ] `localStorage` 中 `farmTrend` / `farmTrendRori` 长度 **≤ 2000**，`farmLogs` **≤ 500**，`farmAlerts` **≤ 200**
- [ ] 页面放置 1 分钟后，`farmLogs` 的写入次数明显少于日志条数（30s 节流生效）
- [ ] 关闭标签页后重开，日志与告警仍保留

### 6.6 自动化命令

```bash
node --test "tests/js/**/*.test.mjs"    # 或 npm run test:js —— 应 28 passed / 0 failed
python -m pytest tests -q               # 后端回归（由 architect 负责，不应因前端改动变红）
git status                              # 应为干净工作区
```

---

## 七、已知取舍

1. `core.js` 采用 IIFE + `globalThis` 挂载（而非 ESM），是为兼容模板内联 `onclick="..."` 与保持零构建工具链；代价是无法直接 `import`，测试需最小 DOM 桩。
2. 图表横轴使用**抽样后的标签数组**（`CHART_LIMIT = 300`），点数极多时时间轴为等距近似，非严格时间比例尺。
3. `esc()` 保留但当前业务路径已无 `innerHTML` 调用，属防御性保留，供后续新增功能使用。
