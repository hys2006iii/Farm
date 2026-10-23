# -*- coding: utf-8 -*-
"""生成概要设计说明书缺的 4 张图：g_autocontrol / g_hitl / g_alert / g_er。"""
from __future__ import annotations

import figlib as F
from matplotlib.patches import Rectangle


def g_autocontrol():
    fig, ax = F.canvas("图 5-5 自动调控决策与滞回去抖",
                       "判定链只看阈值与滞回带，动作闸门保证 60 秒内不重复下发")
    y, h, w = 20, 11, 14
    xs = [4, 20, 36, 52, 68, 84]
    texts = [
        ("读当前状态\nwater_mm·soil_pct", "ok"),
        ("计算 RORI\ncompute_rori()", "ok"),
        ("取动态阈值\neffLower/effUpper", "ok"),
        ("滞回比较\n越过带宽才动作", "warn"),
        ("动作闸门\n≥60 s 且状态翻转", "warn"),
        ("下发指令\nsend_command", "ok"),
    ]
    for x, (text, kind) in zip(xs, texts):
        F.box(ax, x, y, w, h, text, kind=kind, size=9.2)
    for i in range(len(xs) - 1):
        F.arrow(ax, xs[i] + w, y + h / 2, xs[i + 1], y + h / 2)

    F.lane(ax, 40, 6.5, "滞回带去抖示意（横轴为土壤湿润度 %RH）")
    base = 62
    ax.plot([10, 90], [base, base], color=F.GRAY_ED, lw=2.0)
    for xv, label in ((32, "effLower"), (64, "effUpper")):
        ax.plot([xv, xv], [base - 3.2, base + 3.2], color=F.GREEN, lw=1.8)
        ax.text(xv, base + 5.0, label, fontsize=9.8, color=F.GREEN, ha="center")
        ax.add_patch(Rectangle((xv - 5, base - 2.4), 10, 4.8,
                               facecolor=F.AMBER_BG, edgecolor=F.AMBER_ED,
                               alpha=0.9, zorder=1))
    F.arrow(ax, 25, base - 11, 22, base - 3.0, kind="warn")
    ax.text(23, base - 12.5, "低于 下限−带宽 → 开泵补灌", fontsize=9.2,
            color="#8A5A12", ha="center")
    F.arrow(ax, 71, base - 11, 70, base - 3.0, kind="warn")
    ax.text(71, base - 12.5, "高于 上限+带宽 → 停泵排水", fontsize=9.2,
            color="#8A5A12", ha="center")
    ax.text(50, base + 12.5, "带宽内保持上一状态，不因读数抖动反复切换",
            fontsize=9.8, color="#5A6B60", ha="center")

    F.panel(ax, 6, 78, 88, 11,
            "为什么需要闸门与滞回：传感器每秒上报，若每次都用瞬时值判定并把结果直接下发，"
            "泵会在阈值附近被反复开关，既伤机械也污染用水量统计。\n"
            "滞回带过滤掉读数抖动，60 秒最小间隔过滤掉缓慢漂移，二者叠加后动作次数下降一个数量级。",
            size=9.8)
    F.save(fig, "g_autocontrol.png")


def g_hitl():
    fig, ax = F.canvas("图 5-6 AI 预案闭环人机协同时序",
                       "AI 只出建议、不直接动作；确认、拒绝、过期三条出口都以人工为起点")
    people = [
        (11, "用户"),
        (31, "前端\ninsight.js"),
        (52, "服务端\nplanner.py"),
        (73, "AI 接口\n或规则引擎"),
        (92, "设备\nMQTT"),
    ]
    top = 21
    for x, name in people:
        F.box(ax, x - 7, top, 14, 9, name, kind="ok", size=9.2, bold=True)
        ax.plot([x, x], [top + 9, 92], color=F.GRAY_ED, lw=1.0,
                linestyle=(0, (4, 3)), zorder=0)

    msgs = [
        (36, 11, 31, "点「生成预案」", "ok"),
        (41, 31, 52, "POST /api/plan/propose", "info"),
        (46, 52, 73, "build_context → 拼提示词", "ok"),
        (51, 73, 52, "返回 JSON（失败则规则回退）", "warn"),
        (56, 52, 31, "预案 + reasoning（pending）", "ok"),
        (63, 11, 31, "人工点「确认」或「拒绝」", "warn"),
        (69, 31, 52, "POST /api/plan/confirm", "info"),
        (75, 52, 52, "校验归属 / pending / TTL 600 s", "warn"),
        (81, 52, 92, "逐条下发 on / off", "ok"),
        (87, 52, 31, "status = confirmed", "ok"),
    ]
    for yy, x1, x2, text, kind in msgs:
        if x1 == x2:
            ax.add_patch(Rectangle((x1 - 12, yy - 2.2), 24, 4.4,
                                   facecolor=F.AMBER_BG, edgecolor=F.AMBER_ED,
                                   zorder=2))
            ax.text(x1, yy, text, fontsize=9.0, color="#8A5A12",
                    ha="center", va="center", zorder=3)
            continue
        F.arrow(ax, x1, yy, x2, yy, kind=kind)
        mid = (x1 + x2) / 2
        ax.text(mid, yy - 1.6, text, fontsize=9.0, color="#3C4741",
                ha="center", va="bottom", zorder=3)

    ax.text(6, 95.5, "拒绝 → status=rejected；超过 600 秒未处理 → status=expired，"
                     "陈旧决策不得执行（基于当时的墒情与雨情，时过境迁可能有害）",
            fontsize=9.4, color="#8A5A12", ha="left")
    F.save(fig, "g_hitl.png")


def g_alert():
    fig, ax = F.canvas("图 5-7 告警产生、去重与推送",
                       "判定是纯函数、去重放内存、落库与推送在后台，三条路径互不阻塞回调线程")
    y, h, w = 22, 12, 13
    xs = [4, 20, 36, 52, 68, 83]
    texts = [
        ("遥测读数\n水位/湿度/RORI", "ok"),
        ("evaluate_alerts()\n五条规则 → code", "ok"),
        ("AlertDeduper\n同类 60 s 冷却", "warn"),
        ("push_alert()\n落库 alerts 表", "ok"),
        ("Webhook 推送\n0/0.5/1.0 s 重试", "warn"),
        ("前端 alertList\n+ 钉钉群", "info"),
    ]
    for x, (text, kind) in zip(xs, texts):
        F.box(ax, x, y, w, h, text, kind=kind, size=9.2)
    for i in range(len(xs) - 1):
        F.arrow(ax, xs[i] + w, y + h / 2, xs[i + 1] - 1, y + h / 2)

    F.lane(ax, 46, 6.5, "三条支路各自独立，都不在 MQTT 回调线程里做磁盘或网络 IO")
    F.panel(ax, 4, 57, 28, 13,
            "判定：纯函数\n不碰库、不发网络\n入参可任意组合测试", size=9.6)
    F.panel(ax, 36, 57, 28, 13,
            "去重：内存字典 + 锁\n60 s 滑动窗口\n持续异常时仍会再报", size=9.6)
    F.panel(ax, 68, 57, 28, 13,
            "推送：后台线程\n失败只影响外部通道\n站内仍返回 HTTP 200", size=9.6)
    for xc in (18, 50, 82):
        F.arrow(ax, xc, y + h + 1, xc, 56, kind="warn")

    F.panel(ax, 4, 80, 92, 12,
            "失败降级：webhook 不通时返回 status=skipped、sent=false，用户已在页面看到告警，不再弹失败框。\n"
            "钉钉关键词【青禾智灌系统】缺失会被平台静默拒绝（errcode 310000），故固定写进 config.ALERT_KEY_PREFIX。",
            size=9.6)
    F.save(fig, "g_alert.png")


def g_er():
    fig, ax = F.canvas("图 6-1 数据库实体关系",
                       "12 张表按三个域归组，全部以 user_id 隔离；地块是第二层隔离维度")
    F.lane(ax, 19, 6.5, "账号与配置域（账号级，一个用户一行）")
    F.box(ax, 5, 29, 20, 12, "users\nid · username\npassword_hash", kind="ok", size=8.8)
    F.box(ax, 30, 29, 24, 12, "configs\nfarm_name · lat/lon · active_farm_id\niot_* · weather_key · ai_key",
          kind="ok", size=8.4)
    F.box(ax, 59, 29, 17, 12, "farms\nid · user_id · name\nlat · lon · polygon",
          kind="ok", size=8.4)
    F.box(ax, 81, 29, 15, 12, "thresh_settings\nhumi/water\n上下限", kind="ok", size=8.4)
    F.arrow(ax, 25, 35, 30, 35)
    F.arrow(ax, 54, 35, 59, 35)
    F.arrow(ax, 76, 35, 81, 35)

    F.lane(ax, 49, 6.5, "数据域（按 farm_id 再做一层隔离）")
    F.box(ax, 5, 59, 27, 12, "sensor_history\nfarm_id · ts · water_adc\nsoil_adc · do_mgl · eh_mv",
          kind="info", size=8.4)
    F.box(ax, 38, 59, 20, 12, "geo_cache\nkey(经纬度)\nname · ts", kind="info", size=8.4)
    F.box(ax, 64, 59, 32, 12, "pump_runtime\n(user_id, device, day) PK\nseconds 累加",
          kind="info", size=8.4)
    F.arrow(ax, 15, 41, 15, 59)
    F.arrow(ax, 70, 41, 70, 59)

    F.lane(ax, 78, 6.5, "运行状态域（含服务端自动调控与预案）")
    row = [
        (5, "alerts\nlevel · code\nacked"),
        (22, "logs\nlevel · source\nmessage"),
        (39, "device_status\nlast_seen_ts\nonline"),
        (56, "plans\nstatus · context\nproposal"),
        (73, "auto_control\nenabled\nlast_action_ts"),
        (87, "全表带\nuser_id\n隔离键"),
    ]
    for x, text in row:
        kind = "gray" if x != 90 else "warn"
        F.box(ax, x, 87, 12, 10, text, kind=kind, size=8.2)

    ax.text(5, 99.5,
            "隔离规则：查询一律带 user_id；sensor_history 额外带 farm_id，条件为 "
            "AND (farm_id = ? OR farm_id = 0)，其中 farm_id = 0 兼容多地块上线前的历史数据。",
            fontsize=9.0, color="#5A6B60", ha="left")
    F.save(fig, "g_er.png")


if __name__ == "__main__":
    g_autocontrol()
    g_hitl()
    g_alert()
    g_er()
