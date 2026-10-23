# -*- coding: utf-8 -*-
"""重写 g_er（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("g_er.png", "图 6-1 数据库实体关系")
def g_er():
    W, H = 13.6, 8.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 6-1  数据库实体关系",
          "12 张业务表：users 与 farms 为两张父表，其余表按 user_id / farm_id 挂接")

    def entity(x, y, w, h, name, cn, fields, accent=DEEP):
        box(ax, x, y, w, h, "", fc=WHITE, ec=accent, lw=1.4, r=0.08)
        box(ax, x, y + h - 0.34, w, 0.34, "", fc=accent, ec=accent, lw=1.2, r=0.08)
        ax.text(x + 0.12, y + h - 0.17, "%s  %s" % (name, cn), ha="left", va="center",
                fontsize=9.5, color=WHITE, weight="bold", zorder=6)
        for i, (mark, txt) in enumerate(fields):
            yy = y + h - 0.34 - 0.12 - i * 0.145
            col = ORANGE if mark == "PK" else (MID if mark == "FK" else GRAY)
            ax.text(x + 0.12, yy, mark, ha="left", va="center", fontsize=9,
                    color=col, weight="bold", zorder=6)
            ax.text(x + 0.52, yy, txt, ha="left", va="center", fontsize=9,
                    color=INK, zorder=6)

    c2, c3, c4 = 3.95, 7.45, 10.75
    r1, r2, r3, r4 = 5.95, 4.35, 2.75, 1.15
    hh = 1.15

    entity(0.55, r1, 2.85, hh, "users", "用户",
           [("PK", "id INTEGER"), ("", "username TEXT"), ("", "password_hash"),
            ("", "salt / role")])
    entity(c2, r1, 3.10, hh, "farms", "地块",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "name / area / location")])
    entity(c2, r2, 3.10, hh, "alerts", "告警",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "level / message / pushed")])
    entity(c2, r3, 3.10, hh, "logs", "运行日志",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "action / detail")])
    entity(c2, r4, 3.10, hh, "plans", "AI 预案",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "status / expire_at")])

    entity(c3, r1, 3.10, hh, "sensor_history", "历史数据",
           [("PK", "id"), ("FK", "farm_id → farms.id"),
            ("", "ts / water / soil / do / eh")])
    entity(c3, r2, 3.10, hh, "thresh_settings", "阈值",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "humi_up / humi_down")])
    entity(c3, r3, 3.10, hh, "device_status", "设备状态",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "online / last_seen")])
    entity(c3, r4, 3.10, hh, "pump_runtime", "泵累计",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "date / seconds")])

    entity(c4, r1, 2.55, hh, "configs", "配置",
           [("PK", "key"), ("FK", "user_id → users.id"), ("", "value")])
    entity(c4, r2, 2.55, hh, "auto_control", "自动调控",
           [("PK", "id"), ("FK", "user_id → users.id"), ("", "mode / last_fire")])
    entity(c4, r3, 2.55, hh, "geo_cache", "逆地理缓存",
           [("PK", "id"), ("", "lat / lon / addr"), ("", "updated_at")])

    # users 到四张子表：一条竖向导轨 + 四条短箭头
    line(ax, [(3.42, 6.53), (3.42, 1.73)], color=ORANGE, lw=1.5)
    for y in (6.53, 4.93, 3.33, 1.73):
        arrow(ax, (3.42, y), (3.93, y), color=ORANGE, lw=1.5, ms=11)
        label(ax, 3.68, y + 0.17, "1 : N", fs=9, color=ORANGE)
    arrow(ax, (7.07, 6.53), (7.43, 6.53), color=ORANGE, lw=1.5, ms=11)
    label(ax, 7.25, 6.70, "1 : N", fs=9, color=ORANGE)

    # 字段约定
    box(ax, 0.55, 1.15, 2.80, 4.45, "", fc=GRAY_L, ec=GRAY, lw=1.2, r=0.08)
    label(ax, 0.72, 5.30, "字段约定", fs=10.5, color=DEEP, weight="bold", ha="left")
    notes = ["主键统一 INTEGER", "  PRIMARY KEY 自增",
             "时间存 UTC 秒级时间戳", "金额 / 水量用 REAL", "布尔用 0 / 1 整数",
             "索引：(user_id, created_at)", "索引：(farm_id, ts)",
             "SQL 一律参数化占位"]
    for i, t in enumerate(notes):
        label(ax, 0.72, 4.95 - i * 0.40, t, fs=9, color=INK, ha="left")

    # 图例
    box(ax, 10.75, r4, 2.55, hh, "", fc=GRAY_L, ec=GRAY, lw=1.2, r=0.08)
    label(ax, 10.90, r4 + 0.92, "图例", fs=10, color=DEEP, weight="bold", ha="left")
    label(ax, 10.90, r4 + 0.62, "PK 主键 · FK 外键", fs=9, color=INK, ha="left")
    label(ax, 10.90, r4 + 0.36, "→ 一对多（1 : N）", fs=9, color=ORANGE, ha="left")
    label(ax, 10.90, r4 + 0.12, "SQLite 单文件 + WAL", fs=9, color=GRAY, ha="left")

    label(ax, 6.80, 0.55,
          "外键在 SQLite 中默认不强制，由 db.py DAO 层保证：删除用户按 user_id 级联清理，"
          "sensor_history 按 farm_id 归档", fs=9, color=GRAY)
    save(f, "g_er.png")


'''
s = io.open(P, encoding="utf-8").read()
a = s.index('@fig("g_er.png"')
b = s.index('# @@APPEND@@')
io.open(P, "w", encoding="utf-8").write(s[:a] + NEW + s[b:])
print("patched g_er")
