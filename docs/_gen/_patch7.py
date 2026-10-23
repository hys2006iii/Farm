# -*- coding: utf-8 -*-
"""插入详细设计说明书第 5~8 张图（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("x_rori_fuse.png", "图 5-2 RORI 融合与分级数值轴")
def x_rori_fuse():
    W, H = 13.0, 9.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-2  RORI 融合与分级数值轴",
          "四路归一化值加权融合后取整，落到 0–100 的三段区间")

    ins = [("S_Eh", "ω₁ = 0.35", 7.55), ("S_DO", "ω₂ = 0.35", 6.95),
           ("R_water", "ω₃ · max 取大", 6.35), ("R_soil", "R_water 与 R_soil", 5.75)]
    for name, wtxt, y in ins:
        box(ax, 0.60, y, 2.10, 0.48, name, fc=LIGHT, ec=GREEN, fs=10, r=0.06)
        label(ax, 3.05, y + 0.24, wtxt, fs=9, color=ORANGE, ha="left")

    # 汇聚总线
    line(ax, [(4.25, 7.79), (4.25, 5.99), (4.45, 5.99), (4.45, 7.10)], color=GREEN, lw=1.5)
    for _n, _w, y in ins:
        arrow(ax, (2.70, y + 0.24), (4.23, y + 0.24), color=GREEN, lw=1.4, ms=10,
              shrinkA=0.5, shrinkB=0.5)
    arrow(ax, (4.45, 7.10), (4.70, 7.10), color=GREEN, lw=1.6, ms=11)

    box(ax, 4.72, 6.55, 2.55, 1.10, "加权融合\nP_risk", fc=ORANGE_L, ec=ORANGE, fs=10.5,
        weight="bold", r=0.08)
    box(ax, 4.72, 5.35, 2.55, 0.95, "叠加惩罚\nγ · R_water · R_soil", fc=WHITE, ec=ORANGE,
        fs=9.5, r=0.08, ls="--")
    arrow(ax, (5.99, 5.83), (5.99, 6.53), color=ORANGE, lw=1.5, ms=11)

    arrow(ax, (7.27, 7.10), (7.70, 7.10), color=GREEN, lw=1.8, ms=12)
    box(ax, 7.72, 6.60, 2.60, 1.00, "RORI = ⌊P_risk × 100⌋", fc=LIGHT, ec=GREEN, fs=10.5,
        weight="bold", r=0.08)
    arrow(ax, (10.32, 7.10), (10.72, 7.10), color=GREEN, lw=1.8, ms=12)
    box(ax, 10.74, 6.60, 1.80, 1.00, "0 – 100\n整数", fc=GRAY_L, ec=GRAY, fs=10, r=0.08)

    box(ax, 10.40, 5.10, 2.20, 1.15,
        "γ = 0.5\n水旱叠加惩罚\n仅在两者同高时生效", fc=WHITE, ec=SOFT, fs=9, tc=GRAY,
        lw=1.1, r=0.07)

    # 数值轴
    label(ax, 0.60, 4.72, "分级数值轴", fs=11, color=DEEP, weight="bold", ha="left")
    x0, x1, y0 = 1.20, 12.10, 3.55
    segs = [("0 – 40　待机", 0, 40, LIGHT, GREEN), ("40 – 70　脉冲", 40, 70, ORANGE_L, ORANGE),
            ("70 – 100　满载", 70, 100, RED_L, RED)]
    for name, a, b, fc, ec in segs:
        xa = x0 + (x1 - x0) * a / 100.0
        xb = x0 + (x1 - x0) * b / 100.0
        ax.add_patch(Rectangle((xa, y0), xb - xa, 0.62, facecolor=fc, edgecolor=ec,
                               linewidth=1.6, zorder=3))
        label(ax, (xa + xb) / 2, y0 + 0.31, name, fs=10.5, color=INK, weight="bold")
        label(ax, (xa + xb) / 2, y0 - 0.26, "%d" % a if a == 0 else "%d" % a, fs=9,
              color=GRAY)
    for v in (0, 20, 40, 60, 70, 86, 100):
        xv = x0 + (x1 - x0) * v / 100.0
        line(ax, [(xv, y0 - 0.10), (xv, y0)], color=GRAY, lw=1.0, zorder=2)
    label(ax, x1, y0 - 0.26, "100", fs=9, color=GRAY)

    for v, txt, up in ((86, "算例①　RORI = 86 → 满载", True),
                       (35, "算例②　RORI = 35 → 待机", False)):
        xv = x0 + (x1 - x0) * v / 100.0
        yy = y0 + 0.62 + 0.30 if up else y0 - 0.55
        arrow(ax, (xv, yy - 0.10 if up else yy + 0.16), (xv, y0 + 0.62 if up else y0),
              color=RED if up else GREEN, lw=1.4, ms=10, ls="--")
        label(ax, xv, yy, txt, fs=9.5, color=RED if up else GREEN, weight="bold")

    box(ax, 0.60, 1.05, 5.90, 1.55,
        "算例①　Eh = 0 mV，DO = 2.0 mg/L\n水位 50 mm，土壤 70%\n"
        "→ 0.35×0.667 + 0.35×0.75 + 0.30×0.70 + 0.5×0.45×0.70 ≈ 0.86",
        fc=WHITE, ec=RED, fs=9, lw=1.2, r=0.07)
    box(ax, 6.70, 1.05, 5.90, 1.55,
        "算例②　Eh = 200 mV，DO = 6.0 mg/L\n水量与土壤读数正常，仅两个主因子贡献\n→ 落入 0 – 40 待机区间，不下发指令",
        fc=WHITE, ec=GREEN, fs=9, lw=1.2, r=0.07)
    save(f, "x_rori_fuse.png")


@fig("x_histwriter.png", "图 7-1 HistoryWriter 队列批量落库与背压")
def x_histwriter():
    W, H = 13.6, 8.0
    f, ax = canvas(W, H)
    title(ax, W, H, "图 7-1  HistoryWriter 队列批量落库与背压",
          "回调只入队，落库线程批量写；队满时丢最旧，永不阻塞回调")

    row = [("MQTT 回调线程", "on_message", 0.60, LIGHT, GREEN),
           ("put_nowait", "入队不等待", 3.30, LIGHT, GREEN),
           ("有界队列", "maxsize = 2000", 6.00, ORANGE_L, ORANGE),
           ("落库线程", "取批 ≤ 200 条", 8.70, LIGHT, GREEN),
           ("SQLite", "批量 INSERT", 11.40, LIGHT, GREEN)]
    for name, desc, x, fc, ec in row:
        box(ax, x, 5.10, 2.30, 0.95, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=10, r=0.08)
    for i in range(4):
        x = 0.60 + i * 2.70
        arrow(ax, (x + 2.30, 5.575), (x + 2.70, 5.575), color=GREEN, lw=1.8, ms=12)

    # 队列内部示意
    for i in range(6):
        ax.add_patch(Rectangle((6.05 + i * 0.36, 5.28), 0.30, 0.32, facecolor=WHITE,
                               edgecolor=ORANGE, lw=1.0, zorder=6))
    label(ax, 7.15, 4.98, "环形缓冲：满则 popleft 丢最旧", fs=9, color=ORANGE)

    # 溢出路径
    box(ax, 5.60, 3.30, 3.10, 0.75, "队满 → 丢弃最旧一条\nput_nowait 永不阻塞", fc=RED_L,
        ec=RED, fs=9.5, lw=1.3, r=0.07, ls="--")
    arrow(ax, (7.15, 5.10), (7.15, 4.07), color=RED, lw=1.5, ms=11, ls="--")

    # 批量细节
    box(ax, 9.10, 3.20, 4.00, 1.00,
        "单事务 executemany：一次提交 200 行\n失败整批回滚，计数入日志", fc=PALE,
        ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)
    arrow(ax, (9.85, 5.10), (9.85, 4.22), color=GRAY, lw=1.2, ms=10, ls=":")

    # 红线
    box(ax, 0.60, 6.55, 12.10, 0.85,
        "红线：MQTT 回调线程内绝不允许出现 commit / 网络 IO / 大循环 —— 只允许一次 put_nowait，"
        "阻塞即丢数据、拖慢整条 MQTT 连接",
        fc=RED_L, ec=RED, fs=9.5, tc=INK, lw=1.4, r=0.07)

    box(ax, 0.60, 1.35, 12.10, 1.35,
        "背压策略：队列满时牺牲最旧的一条而不是阻塞生产者，保证实时性优先；"
        "落库线程空闲时阻塞在队列 get(timeout=1) 上，既省 CPU 又能被优雅关闭。\n"
        "统计口径：丢弃条数单独计数并写入运行日志，便于评估落库吞吐是否够用。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07, ls_spacing=1.55)
    save(f, "x_histwriter.png")


@fig("x_mqtt.png", "图 7-2 handle_mqtt_message 三种报文分支")
def x_mqtt():
    W, H = 13.0, 8.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 7-2  handle_mqtt_message 的三种报文分支",
          "华为云 M2M、自定义扁平 JSON、纯文本数值统一归一为 values 字典")

    box(ax, 0.55, 6.60, 2.60, 0.95, "on_message\n(topic, payload)", fc=LIGHT, ec=GREEN,
        fs=10, r=0.08)
    box(ax, 3.55, 6.60, 2.60, 0.95, "topic 取末段\ntopic_leaf", fc=LIGHT, ec=GREEN,
        fs=10, r=0.08)
    arrow(ax, (3.15, 7.075), (3.53, 7.075), color=GREEN, lw=1.8, ms=12)

    br = [("① 华为云 M2M", "services[].properties", 7.35),
          ("② 自定义扁平 JSON", "{water: 12, soil: 800}", 6.10),
          ("③ 纯文本数值", "\"12.5\" / \"12.5,800\"", 4.85)]
    for name, desc, y in br:
        box(ax, 6.65, y, 3.10, 0.85, "%s\n%s" % (name, desc), fc=WHITE, ec=GREEN, fs=9.5,
            lw=1.4, r=0.08)
        arrow(ax, (6.15, 7.075), (6.45, y + 0.42), color=GREEN, lw=1.4, ms=10)
    label(ax, 6.55, 7.70, "按报文形状三分支", fs=9, color=GRAY, ha="left")

    box(ax, 10.20, 5.60, 2.35, 1.35, "values 字典\n统一字段名\n缺失即跳过", fc=ORANGE_L,
        ec=ORANGE, fs=9.5, r=0.08)
    for _n, _d, y in br:
        arrow(ax, (9.77, y + 0.42), (10.18, 6.27), color=GREEN, lw=1.4, ms=10)

    consumers = [("extract_history_sample(values)", 3.55),
                 ("emit_hw_data(uid, payload)", 2.45),
                 ("_feed_insight(uid, values)", 1.35)]
    for name, y in consumers:
        box(ax, 6.90, y, 5.20, 0.72, name, fc=LIGHT, ec=GREEN, fs=9.5, lw=1.2, r=0.07)
        arrow(ax, (11.38, 5.60), (11.95, y + 0.36), color=MID, lw=1.2, ms=9)
    line(ax, [(12.05, 3.91), (12.05, 1.71)], color=MID, lw=1.2)
    for _n, y in consumers:
        line(ax, [(11.95, y + 0.36), (12.05, y + 0.36)], color=MID, lw=1.2)
    label(ax, 6.90, 3.10, "三条消费链", fs=9, color=GRAY, ha="left")

    box(ax, 0.55, 3.55, 5.25, 1.30,
        "异常兜底：JSON 解析失败 / 字段类型非法\n→ 丢弃该条报文并记 warning\n"
        "不让一条脏数据打断整个连接", fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)

    box(ax, 0.55, 0.75, 12.00, 0.72,
        "取值一律走安全转换：float(x) 失败即跳过该字段；数值范围按量程裁剪，避免异常值进入 RORI。",
        fc=PALE, ec=SOFT, fs=9.5, tc=GRAY, lw=1.1, r=0.06)
    save(f, "x_mqtt.png")


@fig("x_alertdedup.png", "图 8-1 AlertDeduper 冷却算法")
def x_alertdedup():
    W, H = 12.4, 8.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 8-1  AlertDeduper 冷却算法",
          "同一个 key 在 60 秒内只推送一次；判定用「当前时间 − 上次推送时间 ≥ 冷却窗口」")

    box(ax, 0.60, 6.10, 3.30, 1.05, "_last: dict[str, float]\nkey → 上次推送时间戳",
        fc=LIGHT, ec=GREEN, fs=9.5, r=0.08)
    box(ax, 0.60, 4.95, 3.30, 0.75, "threading.Lock 保护读写\n多线程回调安全", fc=WHITE,
        ec=GRAY, fs=9, lw=1.2, r=0.08, ls="--")
    arrow(ax, (2.25, 6.10), (2.25, 5.72), color=GRAY, lw=1.4, ms=10, ls="--")

    box(ax, 4.35, 6.10, 3.60, 1.05, "key 构成\nf\"{uid}:{rule}:{level}\"", fc=LIGHT,
        ec=GREEN, fs=9.5, r=0.08)
    arrow(ax, (4.35, 6.62), (3.92, 6.62), color=GREEN, lw=1.4, ms=10)

    box(ax, 8.35, 6.10, 3.45, 1.05, "ALERT_COOLDOWN_SECONDS\n= 60（config 常量）",
        fc=ORANGE_L, ec=ORANGE, fs=9.5, r=0.08)

    # 时间轴
    label(ax, 0.60, 4.55, "冷却窗口时间轴（同一 key）", fs=10.5, color=DEEP, weight="bold",
          ha="left")
    x0, x1, yA = 1.20, 11.50, 3.35
    span = 75.0

    def X(t):
        return x0 + (x1 - x0) * t / span

    ax.add_patch(Rectangle((x0, yA - 0.42), X(60) - x0, 0.84, facecolor=ORANGE_L,
                           edgecolor=ORANGE, lw=1.2, zorder=2, alpha=0.55))
    line(ax, [(x0, yA), (x1, yA)], color=GRAY, lw=2.2, zorder=4)
    label(ax, (x0 + X(60)) / 2, yA + 0.52, "冷却窗口 60 s：同 key 一律丢弃", fs=9.5,
          color=ORANGE, weight="bold")

    ev = [(0, "首次告警 A", "推送 + 记录 t = 0", True),
          (20, "A 再次出现", "命中冷却 → 丢弃", False),
          (59, "A 又出现", "仍丢弃", False),
          (60, "60 s 整", "允许再次推送", True)]
    for t, head, desc, up in ev:
        xv = X(t)
        ax.add_patch(Circle((xv, yA), 0.075, facecolor=GREEN if up else RED,
                            edgecolor=WHITE, lw=1.2, zorder=6))
        if up:
            line(ax, [(xv, yA + 0.10), (xv, yA + 0.30)], color=GRAY, lw=1.0, zorder=5)
            label(ax, xv, yA + 0.36, "%s\n%s" % (head, desc), fs=9, color=GREEN)
        else:
            line(ax, [(xv, yA - 0.10), (xv, yA - 0.34)], color=GRAY, lw=1.0, zorder=5)
            label(ax, xv, yA - 0.62, "%s\n%s" % (head, desc), fs=9, color=RED)
    for t in (0, 20, 40, 60):
        label(ax, X(t), yA - 1.02, "t = %d s" % t, fs=8.5, color=GRAY)

    box(ax, 0.60, 0.75, 11.20, 1.30,
        "判定式：now − _last.get(key, 0) ≥ 60 → 允许推送并更新 _last[key]；否则直接返回 False。\n"
        "边界取 ≥：恰好满 60 秒视为可推送。"
        "字典只增不减会缓慢膨胀，因此在巡检线程里顺带清理超过 10 分钟未用的 key。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07, ls_spacing=1.55)
    save(f, "x_alertdedup.png")


# @@APPEND@@'''

s = io.open(P, encoding="utf-8").read()
assert "# @@APPEND@@" in s
s = s.replace("# @@APPEND@@", NEW.strip("\n"))
io.open(P, "w", encoding="utf-8").write(s)
print("appended batch B")
