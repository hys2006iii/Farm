# -*- coding: utf-8 -*-
"""插入最后 3 张图（x_tick / x_ui_panel / x_test_layers）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("x_tick.png", "图 13-1 前端统一 tick 调度与批量 DOM 更新")
def x_tick():
    W, H = 13.4, 9.0
    f, ax = canvas(W, H)
    title(ax, W, H, "图 13-1  前端统一 tick 调度与批量 DOM 更新",
          "一个 500 ms 主时钟驱动全部任务，所有 DOM 写入合并到一次 flushDom")

    box(ax, 0.55, 6.95, 2.55, 0.85, "setInterval\n每 500 ms 一次", fc=ORANGE_L, ec=ORANGE,
        fs=10, r=0.08)
    arrow(ax, (3.10, 7.375), (3.50, 7.375), color=GREEN, lw=1.7, ms=12)
    box(ax, 3.52, 6.95, 3.05, 0.85, "累加器\nacc[name] += dt", fc=LIGHT, ec=GREEN, fs=10,
        r=0.08)

    tasks = [("dom", 500, "重绘读数与状态色"), ("clock", 1000, "时钟与倒计时"),
             ("chart", 2000, "三条趋势曲线"), ("heartbeat", 5000, "设备在线探测"),
             ("persist", 30000, "批量落库 / 自动保存")]
    for i, (name, ms, desc) in enumerate(tasks):
        y = 5.60 - i * 1.02
        box(ax, 6.95, y, 2.35, 0.80, "%s\n每 %d ms" % (name, ms), fc=WHITE, ec=GREEN,
            fs=9.5, lw=1.4, r=0.07)
        label(ax, 9.55, y + 0.40, desc, fs=9, color=GRAY, ha="left")
        arrow(ax, (5.20, 5.98), (6.93, y + 0.40), color=GREEN, lw=1.3, ms=10, rad=0.05)
        box(ax, 9.50, y, 0.85, 0.80, "try\ncatch", fc=RED_L, ec=RED, fs=8.5, lw=1.1,
            r=0.06)
        arrow(ax, (9.30, y + 0.40), (9.48, y + 0.40), color=GRAY, lw=1.1, ms=9)

    label(ax, 6.95, 6.55, "任务表：到期才执行，单任务抛错不影响其它任务", fs=9,
          color=DEEP, weight="bold", ha="left")

    # 下半：批量 DOM
    label(ax, 0.55, 3.35, "批量 DOM 更新", fs=11, color=DEEP, weight="bold", ha="left")
    box(ax, 0.55, 1.75, 3.60, 1.30,
        "pending = {\n  fields, styles,\n  pumps, flags, sliders\n}", fc=ORANGE_L, ec=ORANGE,
        fs=9, r=0.07)
    arrow(ax, (4.15, 2.40), (4.65, 2.40), color=GREEN, lw=1.6, ms=12)
    box(ax, 4.67, 1.75, 2.55, 1.30, "flushDom()\n一次性写 DOM", fc=LIGHT, ec=GREEN,
        fs=9.5, r=0.07)
    arrow(ax, (7.22, 2.40), (7.72, 2.40), color=GREEN, lw=1.6, ms=12)

    box(ax, 7.74, 2.10, 2.55, 0.60, "el.__qhText\n与上次值比较", fc=WHITE, ec=GRAY, fs=9,
        lw=1.2, r=0.06)
    box(ax, 10.50, 2.60, 2.40, 0.55, "相同 → 跳过", fc=GRAY_L, ec=GRAY, fs=9, lw=1.1,
        r=0.06)
    box(ax, 10.50, 1.75, 2.40, 0.55, "不同 → 写入并缓存", fc=LIGHT, ec=GREEN, fs=9,
        lw=1.2, r=0.06)
    arrow(ax, (10.29, 2.42), (10.48, 2.80), color=GRAY, lw=1.2, ms=9, rad=-0.12)
    arrow(ax, (10.29, 2.38), (10.48, 2.05), color=GREEN, lw=1.2, ms=9, rad=0.12)

    box(ax, 0.55, 0.55, 12.35, 0.85,
        "为什么要合并：500 ms 内可能产生几十次读数更新，逐个写 DOM 会触发多次重排；"
        "先在对象里累积，最后一次写入，长列表只更新可见行。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "x_tick.png")


@fig("x_ui_panel.png", "图 14-1 主监控台区块与 DOM 挂载点")
def x_ui_panel():
    W, H = 13.6, 11.0
    f, ax = canvas(W, H)
    title(ax, W, H, "图 14-1  主监控台区块与 DOM 挂载点",
          "左列看田间、右列做调控，底部趋势，顶层弹窗覆盖全屏")

    box(ax, 0.55, 0.45, 8.75, 9.05, "", fc=WHITE, ec=GRAY, lw=1.6, r=0.06)

    # 顶栏
    box(ax, 0.70, 8.80, 8.45, 0.55, "", fc=GRAY_L, ec=GRAY, lw=1.1, r=0.04)
    box(ax, 0.85, 8.88, 2.10, 0.39, "cloudStatus", fc=LIGHT, ec=GREEN, fs=9, lw=1.1, r=0.05)
    box(ax, 3.10, 8.88, 2.10, 0.39, "deviceStatusPill", fc=LIGHT, ec=GREEN, fs=9, lw=1.1,
        r=0.05)
    label(ax, 6.90, 9.08, "顶部状态栏", fs=9, color=GRAY)

    # 左列
    box(ax, 0.70, 7.55, 4.85, 1.05, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 8.34, "田间小气候　sensorPanel", fs=9.5, color=DEEP, weight="bold",
          ha="left")

    box(ax, 0.70, 5.45, 4.85, 1.95, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 7.18, "田间实时数据", fs=9.5, color=DEEP, weight="bold", ha="left")
    disp = ["waterDisplay", "soilDisplay", "doDisplay", "ehDisplay", "deviceStatus",
            "waterPumpStatus"]
    for i, d in enumerate(disp):
        x = 0.85 + (i % 2) * 2.35
        y = 6.75 - (i // 2) * 0.55
        box(ax, x, y, 2.15, 0.42, d, fc=WHITE, ec=GRAY, fs=8.5, lw=1.0, r=0.05)

    box(ax, 0.70, 4.35, 4.85, 0.95, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 5.10, "RORI 风险指数", fs=9.5, color=DEEP, weight="bold", ha="left")
    for i, d in enumerate(["roriDisplay", "roriStatus", "ongoingAlertBanner"]):
        box(ax, 0.85 + i * 1.58, 4.48, 1.45, 0.42, d, fc=WHITE, ec=GRAY, fs=7.8, lw=1.0,
            r=0.05)

    box(ax, 0.70, 3.35, 4.85, 0.85, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 3.96, "未来七日雨情", fs=9.5, color=DEEP, weight="bold", ha="left")
    label(ax, 0.85, 3.60, "逐日柱状 + P6d 前馈提示", fs=8.5, color=GRAY, ha="left")

    box(ax, 0.70, 1.50, 4.85, 1.70, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 3.02, "告警列表　alertList", fs=9.5, color=DEEP, weight="bold", ha="left")
    for i in range(3):
        line(ax, [(0.90, 2.72 - i * 0.38), (5.35, 2.72 - i * 0.38)], color=SOFT, lw=1.0)

    # 右列
    box(ax, 5.70, 5.45, 3.45, 3.15, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 5.85, 8.34, "调控与阈值", fs=9.5, color=DEEP, weight="bold", ha="left")
    label(ax, 5.85, 8.06, "controlPanel", fs=9, color=GRAY, ha="left")
    for i in range(4):
        line(ax, [(5.90, 7.55 - i * 0.55), (8.95, 7.55 - i * 0.55)], color=SOFT, lw=1.0)

    box(ax, 5.70, 1.50, 3.45, 3.75, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 5.85, 5.02, "运行日志", fs=9.5, color=DEEP, weight="bold", ha="left")
    label(ax, 5.85, 4.74, "logList", fs=9, color=GRAY, ha="left")
    for i in range(6):
        line(ax, [(5.90, 4.40 - i * 0.42), (8.95, 4.40 - i * 0.42)], color=SOFT, lw=1.0)

    # 底部趋势
    box(ax, 0.70, 0.60, 8.45, 0.75, "", fc=PALE, ec=SOFT, lw=1.1, r=0.05)
    label(ax, 0.85, 1.17, "实时趋势", fs=9.5, color=DEEP, weight="bold", ha="left")
    for i, d in enumerate(["waterChart", "soilChart", "roriChart"]):
        box(ax, 0.85 + i * 1.62, 0.68, 1.50, 0.40, d, fc=WHITE, ec=GRAY, fs=8, lw=1.0,
            r=0.05)

    # 右侧：顶层弹窗
    label(ax, 9.65, 8.62, "顶层弹窗（position: fixed）", fs=10, color=DEEP, weight="bold",
          ha="left")
    mods = [("configModal", "配置与阈值编辑"), ("chatModal", "AI 助手对话"),
            ("insightModal", "洞察 / 知识卡"), ("pwdModal", "修改密码")]
    for i, (name, desc) in enumerate(mods):
        y = 7.60 - i * 1.05
        box(ax, 9.65, y, 3.35, 0.72, "%s\n%s" % (name, desc), fc=ORANGE_L, ec=ORANGE,
            fs=9, lw=1.3, r=0.07)
        arrow(ax, (9.63, y + 0.36), (9.35, y + 0.36), color=ORANGE, lw=1.1, ms=9, ls="--")

    box(ax, 9.65, 2.20, 3.35, 1.45,
        "层级：弹窗 z-index 最高\n打开时锁定背景滚动\nEsc / 遮罩点击关闭",
        fc=WHITE, ec=GRAY, fs=9, tc=INK, lw=1.1, r=0.07)
    save(f, "x_ui_panel.png")


@fig("x_test_layers.png", "图 16-1 测试分层")
def x_test_layers():
    W, H = 12.4, 9.0
    f, ax = canvas(W, H)
    title(ax, W, H, "图 16-1  测试分层",
          "越靠底层越快越细，越靠顶层越接近真实用户路径")

    cx = 3.90
    layers = [("单元测试", 3.10, 4.55, 3.30, 2.55, LIGHT, GREEN, "irrigation / heartbeat.silent_seconds\nmetrics 量纲 / validators"),
              ("接口与集成", 4.55, 5.85, 2.55, 1.80, ORANGE_L, ORANGE, "pytest + Flask test client"),
              ("前端逻辑", 5.85, 6.95, 1.80, 1.05, LIGHT, GREEN, "Node 内置 runner"),
              ("端到端", 6.95, 7.85, 1.05, 0.45, GRAY_L, DEEP, "tools/visual_check.py")]
    for name, y0, y1, hw0, hw1, fc, ec, _d in layers:
        ax.add_patch(Polygon([(cx - hw0, y0), (cx + hw0, y0), (cx + hw1, y1),
                              (cx - hw1, y1)], closed=True, facecolor=fc, edgecolor=ec,
                             linewidth=1.6, zorder=3))
        label(ax, cx, (y0 + y1) / 2, name, fs=11, color=INK, weight="bold")

    descs = [("最底层 · 数量最多", "irrigation 分级与滞回、heartbeat.silent_seconds\n"
                                  "metrics 量纲换算、validators 边界值", 3.10, 4.55),
             ("中层 · 用 test client 打接口", "登录限流、save_config 掩码、plan TTL、\n"
                                            "多地块隔离、CSV 导出", 4.55, 5.85),
             ("上层 · 纯函数级前端逻辑", "Node 内置 test runner 跑 9 个 .test.mjs\n"
                                    "覆盖 tick 累加、flushDom 合并", 5.85, 6.95),
             ("顶层 · 真实浏览器断言", "tools/visual_check.py 打开页面、\n断言关键 DOM 与接口联调", 6.95, 7.85)]
    for title_txt, body, y0, y1 in descs:
        box(ax, 7.85, y0 + 0.05, 4.05, (y1 - y0) - 0.10, "", fc=WHITE, ec=GRAY, lw=1.1,
            r=0.06)
        ax.text(7.98, y1 - 0.24, title_txt, ha="left", va="center", fontsize=9,
                color=DEEP, weight="bold", zorder=6)
        ax.text(7.98, y1 - 0.52, body, ha="left", va="top", fontsize=8.5, color=INK,
                zorder=6, linespacing=1.5)
        line(ax, [(cx + 0.02, (y0 + y1) / 2), (7.83, (y0 + y1) / 2)], color=SOFT, lw=1.0)

    box(ax, 0.55, 1.35, 11.35, 1.05,
        "测试隔离要点：conftest 每个用例重置 mqtt_clients 字典、停掉 logbook 写入线程、"
        "清空 AlertDeduper 的 _last、复位 _login_fail 计数器；\n"
        "数据库一律用 tmp_path 下的临时文件，绝不碰真实库。",
        fc=RED_L, ec=RED, fs=9.5, tc=INK, lw=1.2, r=0.07, ls_spacing=1.55)

    label(ax, 0.55, 2.75, "交付前必跑：python -m pytest tests -q 全绿", fs=10, color=DEEP,
          weight="bold", ha="left")
    box(ax, 0.55, 0.45, 11.35, 0.62,
        "分层收益：底层失败能立刻定位到函数，顶层失败才能证明用户路径是通的 —— 两者都不能省。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.06)
    save(f, "x_test_layers.png")


# @@APPEND@@'''

s = io.open(P, encoding="utf-8").read()
assert "# @@APPEND@@" in s
s = s.replace("# @@APPEND@@", NEW.strip("\n"))
io.open(P, "w", encoding="utf-8").write(s)
print("appended batch D")
