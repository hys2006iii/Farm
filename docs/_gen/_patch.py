# -*- coding: utf-8 -*-
"""一次性补丁：替换 g_dataflow 函数体（跑完即删）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()
a = s.index('@fig("g_dataflow.png"')
b = s.index('@fig("g_controlflow.png"')

new = '''@fig("g_dataflow.png", "图 5-1 数据流转架构")
def g_dataflow():
    W, H = 13.2, 7.9
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-1  数据流转架构", "一条主链落库，两条支链并行推送与联动，三者互不阻塞")

    label(ax, 0.88, 6.33, "主链", fs=10, color=DEEP, weight="bold")
    rowA = [("传感器 4 路读数", "水位 / 土壤 / DO / Eh"),
            ("MQTT 报文", "topic 取末段 topic_leaf"),
            ("parse_mqtt_payload", "三种报文归一为 values"),
            ("ingest_telemetry", "(uid, values)"),
            ("HistoryWriter", "队列 maxsize=2000"),
            ("批量 INSERT", "SQLite（WAL）")]
    for i, (t1, t2) in enumerate(rowA):
        x = 1.70 + i * 1.87
        fc, ec = (ORANGE_L, ORANGE) if i == 3 else (LIGHT, GREEN)
        box(ax, x, 5.95, 1.65, 0.77, "%s\\n%s" % (t1, t2), fc=fc, ec=ec, fs=9, lw=1.3, r=0.07)
        if i < 5:
            arrow(ax, (x + 1.65, 6.335), (x + 1.87, 6.335), color=GREEN, lw=1.5, ms=11)

    # 分支走廊：从 ingest_telemetry 下方引出，绕到左侧贯通两条支链
    line(ax, [(8.135, 5.95), (8.135, 5.55), (1.45, 5.55), (1.45, 3.05)], color=MID, lw=1.6)
    ax.add_patch(Circle((1.45, 4.60), 0.045, facecolor=MID, edgecolor=MID, zorder=6))
    arrow(ax, (1.45, 4.60), (1.68, 4.60), color=MID, lw=1.6, ms=12)
    arrow(ax, (1.45, 3.05), (1.68, 3.05), color=MID, lw=1.6, ms=12)

    label(ax, 0.88, 4.60, "推送", fs=10, color=DEEP, weight="bold")
    label(ax, 0.88, 3.05, "联动", fs=10, color=DEEP, weight="bold")

    rowB = [("emit_hw_data", "(uid, payload)"),
            ("socketio.emit", "'hw_data'"),
            ("房间隔离", "room=str(uid)"),
            ("前端 tick", "批量写 DOM")]
    for i, (t1, t2) in enumerate(rowB):
        x = 1.70 + i * 1.72
        box(ax, x, 4.22, 1.55, 0.76, "%s\\n%s" % (t1, t2), fc=LIGHT, ec=GREEN, fs=9,
            lw=1.3, r=0.07)
        if i < 3:
            arrow(ax, (x + 1.55, 4.60), (x + 1.72, 4.60), color=GREEN, lw=1.5, ms=11)

    rowC = [("_feed_insight", "联动入口"),
            ("告警评估", "evaluate_alerts"),
            ("心跳 / 泵统计", "在线状态 · 累计时长"),
            ("自动调控判定", "可回写下行指令")]
    for i, (t1, t2) in enumerate(rowC):
        x = 1.70 + i * 1.72
        box(ax, x, 2.67, 1.55, 0.76, "%s\\n%s" % (t1, t2), fc=ORANGE_L, ec=ORANGE, fs=9,
            lw=1.3, r=0.07)
        if i < 3:
            arrow(ax, (x + 1.55, 3.05), (x + 1.72, 3.05), color=ORANGE, lw=1.5, ms=11)

    box(ax, 8.75, 4.22, 3.95, 0.76,
        "推送不阻塞回调：emit 只做序列化与入队\\n不碰磁盘，回调线程 < 5 ms 返回",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)
    box(ax, 8.75, 2.67, 3.95, 0.76,
        "联动副作用不回写采集链路\\n避免 采集 → 联动 → 采集 的环路放大",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)

    box(ax, 1.70, 0.95, 11.00, 0.90,
        "并行语义：主链负责持久化，批量写入且可背压丢弃最旧；推送支链负责实时呈现，按房间广播；\\n"
        "联动支链负责告警、心跳与自动调控。三条路径都不在 MQTT 回调线程内做磁盘 IO。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.08, ls_spacing=1.6)
    save(f, "g_dataflow.png")


'''
io.open(P, "w", encoding="utf-8").write(s[:a] + new + s[b:])
print("patched g_dataflow")
