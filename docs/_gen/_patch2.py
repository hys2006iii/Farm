# -*- coding: utf-8 -*-
"""把一批图函数插入 make_figs.py 的 @@APPEND@@ 之前（一次性工具）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''
@fig("g_autocontrol.png", "图 5-5 自动调控模式流程")
def g_autocontrol():
    W, H = 12.6, 7.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-5  自动调控模式流程",
          "服务端回路与前端回路互斥，同一时刻只允许一条生效")

    label(ax, 0.55, 6.02, "① 服务端自动调控回路（auto_control，默认关闭）", fs=10.5,
          color=DEEP, weight="bold", ha="left")
    laneA = [("未启用", "默认关闭，不下发", 0.55, 2.10, LIGHT, GREEN),
             ("启用中", "置 mode = auto", 2.90, 2.10, LIGHT, GREEN),
             ("判定", "RORI 分级 + 动态阈值 + 滞回", 5.25, 2.60, ORANGE_L, ORANGE),
             ("下发", "气泵 / 水泵 + 写日志", 8.10, 2.10, LIGHT, GREEN),
             ("闸门", "最小间隔 60 s", 10.45, 1.95, GRAY_L, GRAY)]
    for name, desc, x, w, fc, ec in laneA:
        box(ax, x, 4.90, w, 0.70, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=9.5, r=0.07)
    for x2, x1 in ((2.88, 2.67), (5.23, 5.02), (8.08, 7.87), (10.43, 10.22)):
        arrow(ax, (x1, 5.25), (x2, 5.25), color=GREEN, lw=1.6, ms=12)

    # 闸门回环
    line(ax, [(11.42, 4.90), (11.42, 4.05), (6.55, 4.05)], color=GRAY, lw=1.6)
    arrow(ax, (6.55, 4.05), (6.55, 4.88), color=GRAY, lw=1.6)
    label(ax, 9.05, 4.15, "间隔未到 → 维持现状，不重复下发", fs=9, color=GRAY, ha="left")

    # 互斥闸
    box(ax, 0.90, 3.02, 10.80, 0.62,
        "互斥：mode = auto 时前端 tick 不再控泵；mode = frontend 时服务端只读不下发",
        fc=RED_L, ec=RED, fs=9.5, tc=INK, lw=1.3, r=0.07, ls="--")
    label(ax, 11.85, 3.33, "二选一", fs=9.5, color=RED, weight="bold")

    label(ax, 0.55, 2.55, "② 前端 autoControl 回路（浏览器内定时器）", fs=10.5,
          color=DEEP, weight="bold", ha="left")
    laneB = [("前端开关", "用户勾选 autoControl", 0.55, 2.60, WHITE, GRAY),
             ("定时循环", "每 tick 判定一次", 3.40, 2.60, WHITE, GRAY),
             ("直接下发", "控泵指令出浏览器", 6.25, 2.60, WHITE, GRAY),
             ("服务端退为只读", "仅记录，不下发", 9.10, 2.85, WHITE, GRAY)]
    for name, desc, x, w, fc, ec in laneB:
        box(ax, x, 1.55, w, 0.70, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=9.5, r=0.07)
    for x2, x1 in ((3.38, 3.17), (6.23, 6.02), (9.08, 8.87)):
        arrow(ax, (x1, 1.90), (x2, 1.90), color=GRAY, lw=1.6, ms=12)

    box(ax, 0.55, 0.55, 11.65, 0.72,
        "默认关闭：新建账号 auto_control.mode = off，必须显式启用；两条回路都受 60 s 最小间隔与滞回约束，"
        "避免临界读数反复启停。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "g_autocontrol.png")


@fig("g_hitl.png", "图 5-6 人机协同预案闭环")
def g_hitl():
    W, H = 10.4, 11.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-6  人机协同预案闭环",
          "AI 只给建议，人工确认后才下发；预案 600 秒未确认即过期")

    cx, cw = 2.55, 4.30
    steps = [("用户提问", "现场情况 + 自然语言诉求", LIGHT, GREEN),
             ("build_context", "15 项现场快照（读数 / 阈值 / 泵态）", LIGHT, GREEN),
             ("AI 生成预案", "DeepSeek 20 s 超时，失败走规则回退", ORANGE_L, ORANGE),
             ("预案落库", "status = pending，写 TTL 到期时间", LIGHT, GREEN),
             ("人工确认 / 拒绝", "在预案面板逐条勾选", LIGHT, GREEN),
             ("白名单过滤", "只保留 ALLOWED_DEVICES / ACTIONS", LIGHT, GREEN),
             ("逐条下发指令", "调用 MQTT 下行，失败记日志", LIGHT, GREEN),
             ("confirmed", "全部下发完成的终态", GRAY_L, DEEP)]
    ys = [9.60, 8.55, 7.50, 6.45, 5.40, 4.35, 3.30, 2.25]
    for (name, desc, fc, ec), y in zip(steps, ys):
        box(ax, cx, y, cw, 0.62, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=9.5, r=0.08)
    for i in range(len(ys) - 1):
        arrow(ax, (cx + cw / 2, ys[i]), (cx + cw / 2, ys[i + 1] + 0.62),
              color=GREEN, lw=1.7, ms=13)

    # 右侧旁路与终态
    side = [(7.50, "规则回退", "AI 超时 / 非 200 / 非 JSON 时\n用阈值规则直接生成预案", ORANGE),
            (6.45, "expired", "pending 超过 600 s 未确认\n自动置为 expired 终态", RED),
            (5.40, "rejected", "人工拒绝 → rejected 终态\n不下发任何指令", RED),
            (4.35, "过滤记录", "越权条目写日志后丢弃\n不进入下发队列", GRAY)]
    for y, name, desc, ec in side:
        box(ax, 7.35, y, 2.75, 0.62, "%s\n%s" % (name, desc), fc=WHITE, ec=ec, fs=9,
            lw=1.2, r=0.07, ls="--")
        arrow(ax, (cx + cw, y + 0.31), (7.33, y + 0.31), color=ec, lw=1.3, ms=10,
              ls="--")

    # 左侧阶段括注
    line(ax, [(1.85, 10.22), (1.85, 6.45)], color=SOFT, lw=1.4, ls="--")
    label(ax, 1.55, 8.35, "机器环节", fs=9.5, color=GRAY, rot=90)
    line(ax, [(1.85, 6.02), (1.85, 2.25)], color=SOFT, lw=1.4, ls="--")
    label(ax, 1.55, 4.10, "人机协同", fs=9.5, color=GRAY, rot=90)

    # TTL 时间轴
    box(ax, 0.55, 0.75, 9.55, 1.05, "", fc=PALE, ec=SOFT, lw=1.2, r=0.08)
    label(ax, 0.80, 1.55, "预案 TTL 时间轴", fs=10, color=DEEP, weight="bold", ha="left")
    line(ax, [(1.30, 1.15), (9.70, 1.15)], color=GRAY, lw=2.0)
    for x, txt in ((1.30, "0 s 生成"), (5.50, "300 s 提醒"), (9.70, "600 s 过期")):
        ax.add_patch(Circle((x, 1.15), 0.055, facecolor=GREEN, edgecolor=GREEN, zorder=6))
        label(ax, x, 0.92, txt, fs=9, color=GRAY)
    save(f, "g_hitl.png")


@fig("g_alert.png", "图 5-7 告警产生、去重与推送")
def g_alert():
    W, H = 12.4, 7.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-7  告警产生、去重与推送",
          "判定与去重同步完成，推送异步重试且不影响主流程")

    chain = [("四路读数入库", "ingest_telemetry", LIGHT, GREEN),
             ("evaluate_alerts", "5 条规则逐条判定", LIGHT, GREEN),
             ("AlertDeduper", "冷却 60 s 判定", ORANGE_L, ORANGE),
             ("push_alert 落库", "alerts 表，pushed 置位", LIGHT, GREEN),
             ("_push_with_retry", "最多 3 次", LIGHT, GREEN),
             ("钉钉 Webhook", "群机器人推送", LIGHT, GREEN)]
    for i, (t1, t2, fc, ec) in enumerate(chain):
        x = 0.55 + i * 2.00
        box(ax, x, 5.75, 1.85, 0.70, "%s\n%s" % (t1, t2), fc=fc, ec=ec, fs=9.5, r=0.07)
        if i < 5:
            arrow(ax, (x + 1.85, 6.10), (x + 2.00, 6.10), color=GREEN, lw=1.6, ms=12)

    box(ax, 4.10, 4.45, 3.65, 0.70, "冷却命中 → 丢弃\n不落库、不推送、只计数", fc=RED_L,
        ec=RED, fs=9.5, r=0.07, ls="--")
    arrow(ax, (4.55 + 1.85 / 2, 5.75), (4.55 + 1.85 / 2, 5.17), color=RED, lw=1.5,
          ms=12, ls="--")
    label(ax, 6.05, 5.42, "同一 key 在 60 s 内重复", fs=9, color=RED, ha="left")

    box(ax, 0.55, 2.30, 4.40, 1.85, "", fc=LIGHT, ec=GREEN, lw=1.3, r=0.08)
    label(ax, 0.80, 3.90, "5 条告警规则", fs=10, color=DEEP, weight="bold", ha="left")
    rules = ["DO 溶解氧 < 3.0 mg/L", "Eh 氧化还原电位 < -100 mV",
             "水位 > 阈值上限", "土壤含水率 < 动态下限", "设备心跳超时（离线）"]
    for i, r in enumerate(rules):
        label(ax, 0.95, 3.55 - i * 0.30, "· " + r, fs=9, color=INK, ha="left")

    box(ax, 5.35, 2.30, 6.50, 1.85, "", fc=PALE, ec=GREEN, lw=1.3, r=0.08)
    label(ax, 5.60, 3.90, "推送重试时间轴（成功即止）", fs=10, color=DEEP, weight="bold",
          ha="left")
    line(ax, [(5.95, 3.05), (11.45, 3.05)], color=GRAY, lw=1.8)
    for x, txt in ((5.95, "第 1 次\nt = 0 s"), (8.05, "第 2 次\nt = 0.5 s"), (10.15, "第 3 次\nt = 1.0 s")):
        ax.add_patch(Circle((x, 3.05), 0.06, facecolor=ORANGE, edgecolor=ORANGE, zorder=6))
        label(ax, x, 2.62, txt, fs=9, color=GRAY)
    label(ax, 11.55, 3.05, "仍失败 → 记日志\n接口仍返回 200", fs=9, color=GRAY, ha="left")

    box(ax, 0.55, 0.80, 11.30, 1.00,
        "设计要点：evaluate_alerts 只做纯判定，AlertDeduper 用 {key: 时间戳} 字典 + 锁保证线程安全；"
        "落库与推送分离，推送在独立重试逻辑里完成，绝不让 webhook 超时拖住请求线程。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "g_alert.png")


@fig("g_er.png", "图 6-1 数据库实体关系")
def g_er():
    W, H = 13.6, 9.8
    f, ax = canvas(W, H)
    title(ax, W, H, "图 6-1  数据库实体关系", "12 张业务表：users 与 farms 为两张父表，其余表按 uid / farm_id 挂接")

    def entity(x, y, w, h, name, cn, fields, accent=DEEP):
        box(ax, x, y, w, h, "", fc=WHITE, ec=accent, lw=1.4, r=0.08)
        box(ax, x, y + h - 0.34, w, 0.34, "", fc=accent, ec=accent, lw=1.2, r=0.08)
        ax.text(x + 0.12, y + h - 0.17, "%s  %s" % (name, cn), ha="left", va="center",
                fontsize=9.5, color=WHITE, weight="bold", zorder=6)
        for i, (mark, txt) in enumerate(fields):
            yy = y + h - 0.34 - 0.11 - i * 0.155
            col = ORANGE if mark == "PK" else (MID if mark == "FK" else GRAY)
            ax.text(x + 0.12, yy, mark, ha="left", va="center", fontsize=8.5,
                    color=col, weight="bold", zorder=6)
            ax.text(x + 0.52, yy, txt, ha="left", va="center", fontsize=8.5,
                    color=INK, zorder=6)

    users_f = [("PK", "id INTEGER"), ("", "username TEXT"), ("", "password_hash"),
               ("", "salt / role"), ("", "created_at")]
    entity(0.55, 1.75, 2.90, 6.80, "users", "用户", users_f)

    col2 = 3.95
    entity(col2, 7.25, 3.10, 1.30, "farms", "地块",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "name / area")])
    entity(col2, 5.55, 3.10, 1.30, "alerts", "告警",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "level / message")])
    entity(col2, 3.85, 3.10, 1.30, "logs", "运行日志",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "action / detail")])
    entity(col2, 2.15, 3.10, 1.30, "plans", "AI 预案",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "status / expire_at")])

    col3 = 7.45
    entity(col3, 7.25, 3.10, 1.30, "sensor_history", "历史数据",
           [("PK", "id"), ("FK", "farm_id → farms.id"), ("", "ts / water / soil / do / eh")])
    entity(col3, 5.55, 3.10, 1.30, "thresh_settings", "阈值",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "humi_up / humi_down")])
    entity(col3, 3.85, 3.10, 1.30, "device_status", "设备状态",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "online / last_seen")])
    entity(col3, 2.15, 3.10, 1.30, "pump_runtime", "泵累计",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "date / seconds")])

    col4 = 10.75
    entity(col4, 7.25, 2.55, 1.30, "configs", "配置",
           [("PK", "key"), ("FK", "user_id → users.id"), ("", "value")])
    entity(col4, 5.55, 2.55, 1.30, "auto_control", "自动调控",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "mode / last_fire")])
    entity(col4, 3.85, 2.55, 1.30, "geo_cache", "逆地理缓存",
           [("PK", "id"), ("", "lat / lon / addr"), ("", "updated_at")])

    # 1 : N 关系线
    rel = [(7.90, "users 1 : N farms"), (6.20, "users 1 : N alerts"),
           (4.50, "users 1 : N logs"), (2.80, "users 1 : N plans")]
    for y, txt in rel:
        arrow(ax, (3.47, y), (3.93, y), color=ORANGE, lw=1.5, ms=11)
        label(ax, 3.70, y + 0.20, txt, fs=8.5, color=ORANGE)
    arrow(ax, (7.07, 7.90), (7.43, 7.90), color=ORANGE, lw=1.5, ms=11)
    label(ax, 7.25, 8.10, "farms 1 : N sensor_history", fs=8.5, color=ORANGE)

    # 图例
    box(ax, 10.75, 1.60, 2.55, 1.85, "", fc=GRAY_L, ec=GRAY, lw=1.2, r=0.08)
    label(ax, 10.88, 3.20, "图例", fs=10, color=DEEP, weight="bold", ha="left")
    label(ax, 10.88, 2.92, "PK 主键 · FK 外键", fs=9, color=INK, ha="left")
    label(ax, 10.88, 2.66, "→ 一对多（1 : N）", fs=9, color=ORANGE, ha="left")
    label(ax, 10.88, 2.40, "SQLite 单文件 + WAL", fs=9, color=GRAY, ha="left")
    label(ax, 10.88, 2.14, "外键靠应用层保证", fs=9, color=GRAY, ha="left")

    label(ax, 6.80, 1.20,
          "其余表与 users 的关系在字段上以 FK 标注；删除用户时按 uid 级联清理，sensor_history 按 farm_id 归档",
          fs=9, color=GRAY)
    save(f, "g_er.png")


# @@APPEND@@'''

s = io.open(P, encoding="utf-8").read()
assert "# @@APPEND@@" in s
s = s.replace("# @@APPEND@@", NEW.strip("\n"))
io.open(P, "w", encoding="utf-8").write(s)
print("appended")
