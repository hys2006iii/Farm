# -*- coding: utf-8 -*-
"""插入详细设计说明书前 4 张图（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("x_layers.png", "图 2-1 分层调用与命名约定")
def x_layers():
    W, H = 12.0, 9.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 2-1  分层调用与命名约定",
          "五层竖排：上层可调下层，下层不得反向引用；每层有固定的命名与职责边界")

    rows = [
        ("路由层", "routes/*.py", "只做参数校验与响应组装；不写 SQL、不写算法", "函数名 api_*，蓝图前缀 /api"),
        ("业务层", "irrigation / planner / alerts / weather / ai",
         "纯函数与状态机，不做 IO，可直接单测", "动词 + 名词：evaluate_alerts"),
        ("数据访问层", "db.py DAO", "get_* / save_* / insert_*，参数化 SQL（占位 ?）",
         "动词开头：get_x / save_x / list_x"),
        ("配置常量层", "config.py", "只 import os；阈值、量程、限流常量集中定义", "模块级常量 UPPER_SNAKE_CASE"),
        ("存储层", "SQLite 单文件（WAL）", "12 张业务表 + 索引 + 迁移，不含业务语义", "表名 snake_case 复数"),
    ]
    ys = [7.10, 5.93, 4.76, 3.59, 2.42]
    for (name, mod, duty, conv), y in zip(rows, ys):
        box(ax, 0.55, y, 2.15, 0.85, name, fc=DEEP if name != "存储层" else GRAY, ec=DEEP,
            fs=12, tc=WHITE, weight="bold", r=0.08)
        box(ax, 2.90, y, 4.95, 0.85, "", fc=WHITE, ec=GREEN, lw=1.3, r=0.08)
        ax.text(3.02, y + 0.62, mod, ha="left", va="center", fontsize=9.5, color=GREEN,
                weight="bold", zorder=6)
        ax.text(3.02, y + 0.26, duty, ha="left", va="center", fontsize=9, color=INK, zorder=6)
        box(ax, 8.05, y, 3.40, 0.85, conv, fc=LIGHT, ec=SOFT, fs=9, tc=GRAY, lw=1.1,
            r=0.08, ls="--")
    for i in range(4):
        arrow(ax, (5.35, ys[i]), (5.35, ys[i + 1] + 0.85), color=GREEN, lw=1.6, ms=11)

    label(ax, 9.75, 8.02, "命名约定", fs=10, color=DEEP, weight="bold")
    box(ax, 0.55, 1.15, 10.90, 0.80,
        "依赖方向：只允许上层调用下层。路由里直接写 SQL、config import db、业务层直连 SQLite 均视为违规；"
        "跨层调用必须经过 DAO。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "x_layers.png")


@fig("x_thread.png", "图 2-2 并发线程模型")
def x_thread():
    W, H = 13.6, 9.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 2-2  并发线程模型",
          "五条泳道并行：橙色为可能阻塞的线程，绿色为必须快速返回的线程")

    lanes = [
        ("主请求线程\nwaitress × 8", ORANGE_L, ORANGE,
         ["waitress worker", "Flask 路由 + 鉴权", "DAO 读写 SQLite"],
         "连接按线程持有；WAL 允许读并发"),
        ("MQTT 回调线程\n每用户一条", GREEN, LIGHT,
         ["on_message", "parse_mqtt_payload", "put_nowait / emit"],
         "回调绝不碰磁盘，< 5 ms 返回"),
        ("落库线程\nHistoryWriter", ORANGE_L, ORANGE,
         ["取批（≤ 200 条）", "批量 INSERT", "commit + 清空"],
         "有界队列 2000，溢出丢最旧"),
        ("日志线程\nlogbook", ORANGE_L, ORANGE,
         ["日志入队", "批量写 logs 表", "异常吞掉不抛"],
         "有界队列 1000，满则丢弃"),
        ("巡检线程\nheartbeat", GREEN, LIGHT,
         ["sleep 定时", "扫 last_seen", "置离线 + 告警"],
         "threading.RLock 保护共享态"),
    ]
    ys = [7.15, 5.90, 4.65, 3.40, 2.15]
    for (name, fc, ec, nodes, chan), y in zip(lanes, ys):
        box(ax, 0.55, y, 2.45, 1.05, name, fc=fc, ec=ec, fs=10, lw=1.5, r=0.08)
        box(ax, 3.20, y, 6.75, 1.05, "", fc=WHITE, ec=SOFT, lw=1.2, r=0.06, ls="--")
        for i, n in enumerate(nodes):
            x = 3.40 + i * 2.15
            box(ax, x, y + 0.14, 2.00, 0.77, n, fc=PALE, ec=GRAY, fs=9, lw=1.1, r=0.06)
            if i < 2:
                arrow(ax, (x + 2.00, y + 0.525), (x + 2.15, y + 0.525), color=GRAY,
                      lw=1.3, ms=10)
        box(ax, 10.20, y + 0.14, 2.85, 0.77, chan, fc=GRAY_L, ec=GRAY, fs=9, tc=INK,
            lw=1.1, r=0.06)

    label(ax, 10.20, 8.02, "线程间通道", fs=10, color=DEEP, weight="bold", ha="left")
    box(ax, 0.55, 0.75, 12.50, 0.95,
        "红线：MQTT 回调线程只做解析与入队，落库、推送、写日志全部交给独立的阻塞型线程；"
        "线程间只通过有界队列与 threading.Lock / RLock 通信，共享 SQLite 连接一律 WAL 模式。",
        fc=RED_L, ec=RED, fs=9.5, tc=INK, lw=1.2, r=0.07)
    save(f, "x_thread.png")


@fig("x_migration.png", "图 4-1 幂等迁移流程")
def x_migration():
    W, H = 11.4, 10.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 4-1  幂等迁移流程",
          "init_db 可被任意多次调用：进程内只迁移一次，每个 ALTER 都先判列是否存在")

    cx, cw = 3.05, 4.40
    steps = [
        ("init_db(force=False)", "启动时由 create_app() 调用", LIGHT, GREEN),
        ("检查 _initialized", "force=True 时跳过此检查（测试用）", LIGHT, GREEN),
        ("取 _init_lock", "进程内互斥，避免并发建表", LIGHT, GREEN),
        ("CREATE TABLE IF NOT EXISTS", "建 12 张基表与索引，天然幂等", LIGHT, GREEN),
        ("逐列迁移（三组清单）",
         "PRAGMA table_info 判列存在才 ALTER\n"
         "_CONFIG_MIGRATIONS 8 列 ｜ _HISTORY_MIGRATIONS do_mgl / eh_mv / farm_id\n"
         "_FARM_MIGRATIONS 9 个 iot_* 列", ORANGE_L, ORANGE),
        ("_initialized = True", "释放锁，后续调用直接返回", LIGHT, GREEN),
        ("return，连接交给请求使用", "存量库升级与全新库初始化走同一条路径", GRAY_L, DEEP),
    ]
    ys = [8.55, 7.70, 6.85, 6.00, 4.75, 2.55, 1.70]
    hs = [0.55, 0.55, 0.55, 0.55, 1.05, 0.55, 0.55]
    for (name, desc, fc, ec), y, h in zip(steps, ys, hs):
        box(ax, cx, y, cw, h, "%s\n%s" % (name, desc) if h > 0.9 else name,
            fc=fc, ec=ec, fs=10 if h <= 0.9 else 9.5, lw=1.4, r=0.08)
        if h <= 0.9:
            label(ax, 8.05, y + h / 2.0, desc, fs=9, color=GRAY, ha="left")

    arrow(ax, (5.25, 8.55), (5.25, 8.25), color=GREEN, lw=1.6, ms=11)
    arrow(ax, (5.25, 7.70), (5.25, 7.40), color=GREEN, lw=1.6, ms=11)
    arrow(ax, (5.25, 6.85), (5.25, 6.55), color=GREEN, lw=1.6, ms=11)
    arrow(ax, (5.25, 6.00), (5.25, 5.80), color=GREEN, lw=1.6, ms=11)
    arrow(ax, (5.25, 4.75), (5.25, 3.10), color=ORANGE, lw=1.8, ms=12)
    arrow(ax, (5.25, 2.55), (5.25, 2.25), color=GREEN, lw=1.6, ms=11)

    # 逐列循环
    ax.add_patch(Arc((5.25, 3.92), 1.30, 0.62, theta1=200, theta2=340, color=ORANGE,
                     lw=1.4, zorder=6))
    arrow(ax, (4.62, 3.72), (4.95, 3.62), color=ORANGE, lw=1.4, ms=10, style="-|>")
    label(ax, 6.15, 3.92, "循环：逐列判存在 → 缺失才 ALTER", fs=9, color=ORANGE, ha="left")

    box(ax, 8.05, 4.55, 3.00, 1.60, "", fc=PALE, ec=ORANGE, lw=1.2, r=0.07, ls="--")
    label(ax, 8.20, 5.95, "幂等三原则", fs=10, color=ORANGE, weight="bold", ha="left")
    for i, t in enumerate(["建表一律 IF NOT EXISTS", "列迁移先 PRAGMA 再 ALTER",
                           "整个过程只加不删"]):
        label(ax, 8.20, 5.62 - i * 0.32, "· " + t, fs=9, color=INK, ha="left")

    box(ax, 0.55, 0.55, 10.50, 0.82,
        "异常处理：任一 DDL 失败则回滚当前事务并抛出，_initialized 保持 False，下次启动重试；"
        "全部 DDL 幂等，可安全重复执行。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "x_migration.png")


@fig("x_rori_norm.png", "图 5-1 四路风险因子归一化曲线")
def x_rori_norm():
    W, H = 13.0, 9.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-1  四路风险因子归一化曲线",
          "四路原始读数各自映射到 [0, 1]，边界处饱和截断")

    def panel(rect, xt, yt, xl, yl, xs, ys, marks, note, color=GREEN):
        a = f.add_axes(rect)
        a.plot(xs, ys, color=color, lw=2.4, zorder=4)
        a.set_xlim(xs[0], xs[-1])
        a.set_ylim(-0.05, 1.10)
        a.set_title(xt, fontsize=10.5, color=DEEP, pad=7)
        a.set_xlabel(xl, fontsize=9.5, color=INK, labelpad=2)
        a.set_ylabel(yt, fontsize=9.5, color=INK, labelpad=2)
        a.tick_params(labelsize=8.5, colors=GRAY, length=3)
        a.grid(True, color=SOFT, lw=0.8, ls=":")
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            a.spines[s].set_color(GRAY)
        for mx, my, txt, dx, dy, ha in marks:
            a.plot([mx], [my], "o", ms=6, color=ORANGE, zorder=6)
            a.annotate(txt, xy=(mx, my), xytext=(mx + dx, my + dy), fontsize=8.5,
                       color=ORANGE, ha=ha, va="center",
                       arrowprops=dict(arrowstyle="-", color=ORANGE, lw=1.0,
                                       shrinkA=1, shrinkB=4))
        a.text(0.03, 0.94, note, transform=a.transAxes, fontsize=8.5, color=GRAY,
               va="top", ha="left")
        return a

    eh = np.linspace(-300, 320, 400)
    s_eh = np.clip((300.0 - eh) / 450.0, 0, 1)
    panel([0.86 / W, 5.05 / H, 5.30 / W, 3.10 / H], "① S_Eh：氧化还原电位（mV）",
          "S_Eh", "Eh (mV)", "归一化风险",
          eh, s_eh, [(-150, 1.0, "Eh ≤ -150 饱和为 1", 30, -0.22, "left"),
                     (300, 0.0, "Eh ≥ 300 归零", -10, 0.28, "right")],
          "S_Eh = clamp(0, 1, (300 − Eh) / 450)")

    do = np.linspace(0, 10, 400)
    s_do = np.clip((8.0 - do) / 8.0, 0, 1)
    panel([7.20 / W, 5.05 / H, 5.30 / W, 3.10 / H], "② S_DO：溶解氧（mg/L）",
          "S_DO", "DO (mg/L)", "归一化风险",
          do, s_do, [(0, 1.0, "DO = 0 饱和为 1", 0.5, -0.25, "left"),
                     (8, 0.0, "DO ≥ 8 归零", -0.4, 0.30, "right")],
          "S_DO = clamp(0, 1, (8.0 − DO) / 8.0)", color=MID)

    wat = np.linspace(0, 100, 400)
    r_w = np.maximum(0.0, (wat - 5.0) / 100.0)
    panel([0.86 / W, 1.30 / H, 5.30 / W, 3.10 / H], "③ Risk_water：积水深度（mm）",
          "Risk_water", "Water (mm)", "归一化风险",
          wat, r_w, [(5, 0.0, "5 mm 以下按 0 计", 6, 0.30, "left"),
                     (100, 0.95, "100 mm → 0.95", -6, -0.28, "right")],
          "Risk_water = max(0, (Water − 5) / 100)", color=ORANGE)

    soil = np.linspace(0, 3000, 400)
    r_s = np.clip((2000.0 - soil) / 2000.0, 0, 1)
    panel([7.20 / W, 1.30 / H, 5.30 / W, 3.10 / H], "④ Risk_soil：土壤 ADC 读数",
          "Risk_soil", "Soil_A2 (ADC)", "归一化风险",
          soil, r_s, [(0, 1.0, "ADC = 0 饱和为 1", 120, -0.25, "left"),
                      (2000, 0.0, "ADC ≥ 2000 归零", 80, 0.32, "left")],
          "Risk_soil = (2000 − Soil_A2) / 2000", color=DEEP)

    box(ax, 0.86, 0.55, 11.64, 0.50,
        "四路曲线共用同一套权重；饱和段的意义是极端读数不再线性放大风险，避免单个探头异常拉满 RORI。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.06)
    save(f, "x_rori_norm.png")


# @@APPEND@@'''

s = io.open(P, encoding="utf-8").read()
assert "# @@APPEND@@" in s
s = s.replace("# @@APPEND@@", NEW.strip("\n"))
io.open(P, "w", encoding="utf-8").write(s)
print("appended batch A")
