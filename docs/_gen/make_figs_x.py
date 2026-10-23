# -*- coding: utf-8 -*-
"""生成详细设计说明书缺的 15 张图（前缀 x_）。"""
from __future__ import annotations

import math

import matplotlib.pyplot as plt
import figlib as F
from figlib import GREEN, GRAY_ED, FONT
from matplotlib.patches import Rectangle


# ---------------------------------------------------------------- 2-1 分层
def x_layers():
    fig, ax = F.canvas("图 2-1 分层调用与命名约定",
                       "依赖只能自上而下，任何一层都不反向引用上层；config.py 是叶子")
    layers = [
        ("表现层", "templates/*.html · static/js/*.js", "ok"),
        ("接口层", "routes/*.py（10 个蓝图，只做校验与响应组装）", "ok"),
        ("业务层", "irrigation · alerts · planner · metrics · advice · autocontrol", "info"),
        ("数据访问层", "db.py（每张表一组 DAO，全部参数化 SQL）", "info"),
        ("存储层", "SQLite（WAL）+ 本机文件", "gray"),
    ]
    y = 22
    for name, detail, kind in layers:
        F.box(ax, 8, y, 22, 12, name, kind=kind, size=11, bold=True)
        F.box(ax, 33, y, 58, 12, detail, kind="gray", size=9.6)
        y += 15
    for i in range(len(layers) - 1):
        yy = 22 + i * 15 + 12
        F.arrow(ax, 47, yy, 47, yy + 3)

    ax.add_patch(Rectangle((8, 88), 83, 8, facecolor=F.AMBER_BG,
                           edgecolor=F.AMBER_ED, zorder=1))
    ax.text(12, 92, "集成层（iot / weather / ai / diag）与存储层平级：只被业务层调用，"
                    "外部调用全部带 timeout，异常不向请求栈抛出",
            fontsize=9.6, color="#8A5A12", ha="left", va="center", zorder=3)
    F.save(fig, "x_layers.png")


# ---------------------------------------------------------------- 2-2 线程
def x_thread():
    fig, ax = F.canvas("图 2-2 并发线程模型",
                       "一个 HTTP 线程池 + 四类后台守护线程；共享资源只有 SQLite 与 SocketIO")
    F.lane(ax, 19, 6.5, "入口线程（处理请求 / 承接上报）")
    F.box(ax, 6, 27, 26, 12, "waitress 线程池\nFARM_THREADS=8", kind="ok", size=9.6)
    F.box(ax, 36, 27, 26, 12, "MQTT 回调线程\npaho loop_start", kind="warn", size=9.6)
    F.box(ax, 66, 27, 26, 12, "SocketIO 线程\nasync_mode=threading", kind="ok", size=9.6)

    ax.text(6, 44.5,
            "① 回调线程只做「解析 + 入队 + 登记」，落库交给后台；② 请求线程负责读写配置与下发指令；"
            "③ 推送可由任意线程发起。",
            fontsize=9.4, color="#5A6B60", ha="left", va="center")

    F.lane(ax, 50, 6.5, "后台守护线程（随进程退出）")
    workers = [
        (6, "HistoryWriter\n批量落库 200 条 / 1 s"),
        (28, "LogWriter\n批量落库 20 条 / 1 s"),
        (50, "心跳巡检\n每 5 s 扫一次"),
        (72, "推送重试\n0 / 0.5 / 1.0 s"),
    ]
    for x, t in workers:
        F.box(ax, x, 58, 20, 12, t, kind="info", size=9.2)

    F.lane(ax, 76, 6.5, "共享资源")
    F.box(ax, 6, 84, 26, 11, "SQLite（WAL）\nqueue / _DB_LOCK 串行写", kind="gray", size=9.4)
    F.box(ax, 36, 84, 26, 11, "内存队列\nmaxsize 2000 / 1000", kind="gray", size=9.4)
    F.box(ax, 66, 84, 26, 11, "socketio.emit\n任意线程可安全调用", kind="gray", size=9.4)
    F.save(fig, "x_thread.png")


# ---------------------------------------------------------------- 4-1 迁移
def x_migration():
    fig, ax = F.canvas("图 4-1 幂等迁移流程",
                       "建表用 IF NOT EXISTS，扩列用 PRAGMA 探测后 ALTER，重复执行无副作用")
    steps = [
        "init_db()\n加 _init_lock",
        "_initialized\n已为真？",
        "CREATE TABLE\nIF NOT EXISTS ×12",
        "PRAGMA table_info\n读取现有列",
        "缺列？",
        "ALTER TABLE\nADD COLUMN",
        "登记 _CONFIG_ / _HISTORY_\n/ _FARM_ MIGRATIONS",
        "置 _initialized=True\n并返回",
    ]
    kinds = ["ok", "warn", "ok", "info", "warn", "info", "ok", "ok"]
    y0, gap, hh = 19, 9.2, 8
    for i, (text, kind) in enumerate(zip(steps, kinds)):
        F.box(ax, 34, y0 + i * gap, 34, hh, text, kind=kind, size=9.2)
    for i in range(len(steps) - 1):
        F.arrow(ax, 51, y0 + i * gap + hh, 51, y0 + (i + 1) * gap)
    ax.text(70, y0 + gap + hh / 2, "是 → 立即返回\n（进程内只建一次）", fontsize=9.0,
            color="#8A5A12", ha="left", va="center")
    ax.text(70, y0 + 4 * gap + hh / 2, "否 → 跳过\n（列已存在）", fontsize=9.0,
            color="#8A5A12", ha="left", va="center")
    F.panel(ax, 70, 66, 24, 14, "为什么不用\nalembic：\n零依赖、\n单文件部署", size=9.2)
    F.save(fig, "x_migration.png")


# ---------------------------------------------------------------- 5-1 归一化
def x_rori_norm():
    plt.rcParams["font.sans-serif"] = [FONT, "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 6.2), dpi=200)
    fig.patch.set_facecolor("white")
    fig.suptitle("图 5-1 四路风险因子归一化曲线", fontsize=19, color=GREEN,
                 weight="bold", x=0.055, ha="left", y=0.975)
    fig.text(0.055, 0.915, "左：氧化还原电位与溶解氧的线性递减；右：水位与土壤的分段风险，"
                           "超过死区才开始计风险", fontsize=10.5, color="#5A6B60", ha="left")

    eh = [x * 10 - 200 for x in range(0, 61)]
    s_eh = [min(1.0, max(0.0, (300 - v) / 450.0)) for v in eh]
    ax = axes[0]
    ax.plot(eh, s_eh, color=GREEN, lw=2.4, label="S_Eh = clamp((300−Eh)/450)")
    do = [x * 0.2 for x in range(0, 51)]
    s_do = [min(1.0, max(0.0, (8.0 - v) / 8.0)) for v in do]
    ax2 = ax.twiny()
    ax2.plot(do, s_do, color=F.AMBER_ED, lw=2.0, linestyle="--",
             label="S_DO = clamp((8−DO)/8)")
    ax.set_xlabel("氧化还原电位 Eh（mV）", fontsize=10.5)
    ax2.set_xlabel("溶解氧 DO（mg/L）", fontsize=10.5)
    ax.set_ylabel("归一化风险 0~1", fontsize=10.5)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", fontsize=9, frameon=False)
    ax2.legend(loc="upper right", fontsize=9, frameon=False)
    ax.set_title("Eh 与 DO 的归一化", fontsize=12, color="#3C4741")

    ax = axes[1]
    water = [x * 5 for x in range(0, 41)]
    r_w = [max(0.0, (v - 5) / 100.0) for v in water]
    soil = [2000 - x * 25 for x in range(0, 41)]
    r_s = [max(0.0, (2000 - v) / 2000.0) for v in soil]
    ax.plot(water, r_w, color=GREEN, lw=2.4, label="Risk_water = (W−5)/100")
    ax3 = ax.twiny()
    ax3.plot([v / 4095 * 100 for v in soil], r_s, color=F.AMBER_ED, lw=2.0,
             linestyle="--", label="Risk_soil = (2000−A2)/2000")
    ax.set_xlabel("渠道水位（mm）", fontsize=10.5)
    ax3.set_xlabel("土壤 ADC 占满量程比例", fontsize=10.5)
    ax.set_ylabel("归一化风险 0~1", fontsize=10.5)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", fontsize=9, frameon=False)
    ax3.legend(loc="upper left", fontsize=9, frameon=False)
    ax.set_title("水位与土壤的归一化", fontsize=12, color="#3C4741")

    fig.tight_layout(rect=[0.04, 0.02, 0.98, 0.88])
    F.save(fig, "x_rori_norm.png")


# ---------------------------------------------------------------- 5-2 融合
def x_rori_fuse():
    fig, ax = F.canvas("图 5-2 RORI 融合与分级数值轴",
                       "四项加权 + 耦合惩罚，乘以 100 向下取整；40 与 70 是两个分级断点")
    F.box(ax, 6, 22, 20, 11, "S_Eh\n权重 0.35", kind="ok", size=9.6)
    F.box(ax, 6, 36, 20, 11, "S_DO\n权重 0.35", kind="ok", size=9.6)
    F.box(ax, 6, 50, 20, 11, "max(水,土)\n权重 0.30", kind="info", size=9.6)
    F.box(ax, 30, 36, 22, 12, "P_risk = Σω·风险\n+ 0.5·水×土耦合", kind="warn", size=9.8)
    F.box(ax, 56, 36, 16, 12, "RORI\nP×100 取整", kind="ok", size=9.8)
    for y0 in (27.5, 41.5, 55.5):
        F.arrow(ax, 26, y0, 30, 42)
    F.arrow(ax, 52, 42, 56, 42)

    base = 74
    ax.plot([8, 92], [base, base], color=GRAY_ED, lw=2.4)
    zones = [(8, 32, "待机 <40", F.GREEN_BG, GREEN),
             (32, 60, "脉冲 40–70", F.AMBER_BG, "#8A5A12"),
             (60, 92, "满载 ≥70", "#F6E3E1", "#9B3B2E")]
    for x1, x2, label, bg, fg in zones:
        ax.add_patch(Rectangle((x1, base - 2.6), x2 - x1, 5.2, facecolor=bg,
                               edgecolor=fg, zorder=1))
        ax.text((x1 + x2) / 2, base + 5.4, label, fontsize=10.5, color=fg,
                ha="center", weight="bold")
    for xv, lab in ((8, "0"), (32, "40"), (60, "70"), (92, "100")):
        ax.plot([xv, xv], [base - 4, base + 3], color="#6D7A72", lw=1.2)
        ax.text(xv, base + 3.6, lab, fontsize=9.5, color="#3C4741", ha="center")

    F.panel(ax, 8, 86, 84, 11,
            "算例：Eh=120 mV、DO=6.0 mg/L、水位 45 mm、土壤 ADC 2200 → "
            "S_Eh=0.40、S_DO=0.25、max(水,土)=0.40 → P_risk≈0.759 → RORI=75（重度厌氧）。\n"
            "同级实测值由 compute_rori(1500, 2200, 6.0, 120) 给出：75.89，测试用例以 ±0.05 容差锁定。",
            size=9.6)
    F.save(fig, "x_rori_fuse.png")


# ---------------------------------------------------------------- 7-1 队列
def x_histwriter():
    fig, ax = F.canvas("图 7-1 HistoryWriter 队列批量落库与背压",
                       "回调线程只入队；队列满则丢弃最旧，用丢数据换连接稳定")
    F.box(ax, 6, 24, 20, 12, "MQTT 回调线程\nenqueue()", kind="warn", size=9.6)
    F.box(ax, 32, 20, 34, 20, "queue.Queue(maxsize=2000)\nO(1) put_nowait", kind="ok", size=9.8)
    F.box(ax, 74, 24, 20, 12, "落库线程\nflush_once()", kind="ok", size=9.6)
    F.arrow(ax, 26, 30, 32, 30)
    F.arrow(ax, 66, 30, 74, 30)
    ax.text(70, 66.5, "满 → 丢最旧一条\ndropped += 1", fontsize=9.4, color="#8A5A12",
            ha="center")
    F.arrow(ax, 49, 40, 49, 62, kind="warn")
    F.arrow(ax, 44, 62, 44, 41, kind="warn")

    F.lane(ax, 50, 6.5, "落库线程一拍做的事")
    F.box(ax, 8, 60, 24, 12, "drain()\n最多 200 条", kind="info", size=9.6)
    F.box(ax, 38, 60, 26, 12, "按 uid 解析 farm_id\n（各查一次并缓存）", kind="info", size=9.4)
    F.box(ax, 70, 60, 24, 12, "分组批量 INSERT\n一次事务", kind="ok", size=9.6)
    F.arrow(ax, 32, 66, 38, 66)
    F.arrow(ax, 64, 66, 70, 66)

    F.panel(ax, 8, 78, 86, 13,
            "为什么丢弃而不是阻塞：调用 enqueue() 的是 paho 的网络回调线程，它还负责收发心跳包；"
            "一旦被 put() 阻塞，broker 心跳超时，连接会被断开。\n"
            "代价是断电最多丢一个 flush 周期的采样（1 秒 / 200 条），"
            "对秒级农业监测无实质影响；丢弃计数落在 dropped 上，可观测、可告警。",
            size=9.6)
    F.save(fig, "x_histwriter.png")


# ---------------------------------------------------------------- 7-2 三分支
def x_mqtt():
    fig, ax = F.canvas("图 7-2 handle_mqtt_message 三种报文分支",
                       "解析失败也不抛异常：读不出来的分支会把原文挂到 Topic 末段名下")
    F.box(ax, 6, 26, 24, 12, "MQTT 报文\n(topic, content)", kind="ok", size=9.8)
    F.box(ax, 36, 26, 20, 12, "json.loads()\n失败即 None", kind="warn", size=9.6)
    F.arrow(ax, 30, 32, 36, 32)

    branches = [
        (66, 20, "① 华为云物模型\nservices[].properties\n→ 摊平全部 service", "ok"),
        (66, 40, "② 自定义 Topic JSON\n仅收 int/float/str/bool\n嵌套对象跳过", "info"),
        (66, 60, "③ 纯文本\n整段当作 topic_leaf 的值\ntopic_leaf = topic.split('/')[-1]", "warn"),
    ]
    F.arrow(ax, 46, 30, 62, 26)
    F.arrow(ax, 56, 34, 62, 46)
    F.arrow(ax, 56, 36, 62, 66)
    for x, y, t, kind in branches:
        F.box(ax, x, y, 30, 14, t, kind=kind, size=9.4)

    F.box(ax, 6, 62, 24, 14, "统一产出\n(topic_leaf,\nvalues, messages)", kind="gray", size=9.4)
    for x, y, t, kind in branches:
        F.arrow(ax, x, y + 7, 30, 69, kind="gray")
    F.panel(ax, 6, 82, 90, 10,
            "落库只用 values 里的 waterlevel 与 humidity 两键，缺任一个就跳过本条；"
            "do 与 eh 是可选感知量，缺失存 NULL，兼容只报两路的旧固件。", size=9.6)
    F.save(fig, "x_mqtt.png")


# ---------------------------------------------------------------- 8-1 冷却
def x_alertdedup():
    fig, ax = F.canvas("图 8-1 AlertDeduper 冷却算法状态",
                       "同一 key 在 60 秒窗口内只放行一次；放行即刷新时间戳，异常持续时会周期复报")
    x0, x1, y = 10, 92, 40
    ax.plot([x0, x1], [y, y], color=GRAY_ED, lw=2.4)
    marks = [(10, "0 s", "放行"), (22, "20 s", "拦下"), (34, "40 s", "拦下"),
             (46, "60 s", "放行"), (58, "80 s", "拦下"), (76, "120 s", "放行")]
    for xv, t, kind in marks:
        ok = kind == "放行"
        color = GREEN if ok else F.AMBER_ED
        ax.plot([xv, xv], [y - 4, y + 4], color=color, lw=2.2)
        ax.text(xv, y - 6, t, fontsize=9.5, color="#3C4741", ha="center")
        ax.text(xv, y + 7, kind, fontsize=10, color=color, ha="center", weight="bold")
    for a, b in ((10, 46), (46, 76)):
        ax.add_patch(Rectangle((a, y - 1.6), b - a, 3.2, facecolor=F.GREEN_BG,
                               edgecolor="none", alpha=0.8, zorder=0))
    ax.text(28, y + 13, "放行→放行间隔恒为 60 s", fontsize=9.6, color=GREEN, ha="center")
    ax.text(28, y - 13, "窗口内的重复判定被静默拦下，不落库、不推送",
            fontsize=9.6, color="#5A6B60", ha="center")
    F.panel(ax, 8, 62, 84, 22,
            "为什么用滑动窗口而不是“只报一次”：告警持续存在 20 分钟时，用户需要被持续提醒，"
            "而不是收到一次后永久静默。\n"
            "放行时刷新 last，因此下一次放行是“首次放行 + 60 s”，不会因为判定每 10 秒跑一次就提前放行。\n"
            "状态放内存：60 秒窗口无需持久化，若每次判定都写库，防刷屏机制本身会变成数据库压力源。",
            size=9.6)
    F.save(fig, "x_alertdedup.png")


# ---------------------------------------------------------------- 9-1 实时
def x_realtime():
    fig, ax = F.canvas("图 9-1 SocketIO 房间模型与事件契约",
                       "房间名就是 str(uid)：推送只落在本账号房间，多地块多账号都不串台")
    F.box(ax, 6, 22, 20, 12, "浏览器 A\nsession user_id=1", kind="ok", size=9.2)
    F.box(ax, 6, 42, 20, 12, "浏览器 B\nsession user_id=2", kind="ok", size=9.2)
    F.box(ax, 6, 62, 20, 12, "未登录连接\nreturn False", kind="warn", size=9.2)
    F.box(ax, 34, 32, 28, 14, "SocketIO 房间\nroom='1' / room='2'", kind="info", size=9.8)
    F.box(ax, 70, 22, 24, 12, "iot client #1\n华为云 MQTT", kind="ok", size=9.2)
    F.box(ax, 70, 42, 24, 12, "iot client #2\n华为云 MQTT", kind="ok", size=9.2)
    F.box(ax, 70, 62, 24, 12, "设备 / ESP32-E\n数据转发 Topic", kind="gray", size=9.2)
    F.arrow(ax, 26, 28, 34, 34)
    F.arrow(ax, 26, 48, 34, 44)
    F.arrow(ax, 62, 38, 70, 28)
    F.arrow(ax, 62, 40, 70, 48)
    F.arrow(ax, 82, 54, 82, 62, kind="gray")
    ax.text(52, 55, "emit 只发本房间", fontsize=9.2, color="#5A6B60", ha="center")

    F.lane(ax, 78, 6.5, "事件契约")
    F.box(ax, 6, 87, 26, 9, "connect\n握手读 session", kind="ok", size=9.0)
    F.box(ax, 36, 87, 28, 9, "hw_data（下行）\ntype=data / device_status", kind="info", size=9.0)
    F.box(ax, 68, 87, 26, 9, "send_command（上行）\ndevice + action", kind="warn", size=9.0)
    F.save(fig, "x_realtime.png")


# ---------------------------------------------------------------- 10-1 AI 回退
def x_ai_fallback():
    fig, ax = F.canvas("图 10-1 AI 问答与预案的四类降级",
                       "任何一步失败都返回可用结果而不是异常：错误文本被包成与成功同构的响应")
    F.box(ax, 6, 22, 22, 11, "用户提问 / 生成预案", kind="ok", size=9.6)
    checks = [
        (22, "配置了 Key？", "否 → 返回 NO_KEY_TIP\n仍附带实时快照"),
        (38, "请求成功？", "否 → 包装成\nchoices[0].message"),
        (54, "返回是 JSON？", "否 → 剥围栏后\n再取最外层 {}"),
        (70, "含合法 actions？", "否 → _rule_plan\n(ai_used=False)"),
    ]
    for y, q, hint in checks:
        F.box(ax, 34, y, 26, 11, q, kind="warn", size=9.6)
        ax.text(62, y + 5.5, hint, fontsize=9.0, color="#8A5A12", ha="left", va="center")
    F.arrow(ax, 28, 27, 34, 27)
    for i in range(len(checks) - 1):
        F.arrow(ax, 47, 22 + i * 16 + 11, 47, 22 + (i + 1) * 16)
    F.box(ax, 34, 86, 26, 10, "确认后下发（人工点击）", kind="ok", size=9.6)
    F.arrow(ax, 47, 81, 47, 86)

    F.panel(ax, 62, 86, 30, 10,
            "AI 失败不报错，\n而是给保守规则预案", size=9.4)
    F.save(fig, "x_ai_fallback.png")


# ---------------------------------------------------------------- 11-1 管道
def x_http_pipeline():
    fig, ax = F.canvas("图 11-1 HTTP 请求处理管道",
                       "鉴权 → 校验 → 业务 → 响应；非法输入在第二道就被 4xx 拦住，不进入业务层")
    stages = [
        (6, "请求进入\nwaitress", "gray"),
        (22, "会话 / JWT\n鉴权", "warn"),
        (38, "validators\n类型·范围·长度", "warn"),
        (54, "路由函数\n只做编排", "ok"),
        (70, "DAO 参数化 SQL\n或纯函数算法", "info"),
        (85.5, "jsonify\n统一响应", "ok"),
    ]
    y = 26
    for x, text, kind in stages:
        F.box(ax, x, y, 13, 13, text, kind=kind, size=9.0)
    for i in range(len(stages) - 1):
        F.arrow(ax, stages[i][0] + 13, y + 6.5, stages[i + 1][0], y + 6.5)

    ax.annotate("", xy=(38, 50), xytext=(38, 40),
                arrowprops=dict(arrowstyle="-|>", color="#9B3B2E", lw=1.6))
    ax.text(39.5, 46, "非法 → 4xx\n不进入业务层", fontsize=9.2, color="#9B3B2E",
            ha="left", va="center")

    F.panel(ax, 6, 58, 42, 16,
            "status 语义\n成功 200 / 参数错 400 / 未登录 401\n无权限 403 / 不存在 404 / 限流 429\n上游失败 502", size=9.4)
    F.panel(ax, 52, 58, 42, 16,
            "异常约定\n外部调用异常一律在模块内吞掉\n并转成错误字典；\n任何未捕获异常都由 500 兜底", size=9.4)

    F.panel(ax, 6, 80, 88, 13,
            "MIDDLEWARE：after_request 统一挂 CSP 与安全响应头；MAX_CONTENT_LENGTH = 512 KB，"
            "超限直接 413；数据库连接一律 with closing(get_db())，不泄漏。\n"
            "这条管道的价值在于“校验前置”：把非法入参造成 500 这类故障从架构层面消除。", size=9.6)
    F.save(fig, "x_http_pipeline.png")


# ---------------------------------------------------------------- 12-1 状态机
def x_plan_ttl():
    fig, ax = F.canvas("图 12-1 决策预案状态机与 600 秒 TTL",
                       "pending 是唯一非终态；四条出口全部终止，不存在可复活的中间态")
    F.box(ax, 38, 22, 26, 12, "pending\n已生成待确认", kind="warn", size=10.5, bold=True)
    outs = [
        (6, 52, "confirmed\n已确认并下发", "ok", "用户点确认\n归属 + pending 校验"),
        (36, 52, "rejected\n人工拒绝", "gray", "用户点拒绝"),
        (66, 52, "expired\n超 600 s", "warn", "定时清理 / 访问时判定"),
        (66, 74, "failed\n下发失败", "gray", "设备未连接"),
    ]
    for x, y, t, kind, hint in outs:
        F.box(ax, x, y, 26, 12, t, kind=kind, size=10.2)
    F.arrow(ax, 44, 34, 24, 52, label="")
    F.arrow(ax, 50, 34, 50, 52)
    F.arrow(ax, 58, 34, 78, 52)
    F.arrow(ax, 78, 64, 78, 74, kind="warn")
    ax.text(8, 68, "出口一：用户点确认\n→ 逐条下发", fontsize=9.2, color="#3C4741")
    ax.text(34, 68, "出口二：用户拒绝\n（可附原因）", fontsize=9.2, color="#3C4741")
    ax.text(66, 44, "出口三：超时\n→ 作废", fontsize=9.2, color="#8A5A12")

    F.panel(ax, 6, 88, 86, 9,
            "TTL 的意义：预案基于某一时刻的墒情与雨情生成；十分钟内可能已经下过雨，"
            "执行陈旧决策反而有害。作废比静默执行安全。", size=9.6)
    F.save(fig, "x_plan_ttl.png")


# ---------------------------------------------------------------- 13-1 tick
def x_tick():
    fig, ax = F.canvas("图 13-1 前端统一 tick 调度与批量 DOM 更新",
                       "一个 500 ms 主循环 + 累加器分频，替代原先分散的多个 setInterval")
    F.box(ax, 6, 22, 24, 12, "setInterval 500 ms\nstartTicker()", kind="ok", size=9.6)
    F.box(ax, 36, 22, 28, 12, "acc[name] += dt\ndt 由 Date.now() 差算", kind="warn", size=9.4)
    F.box(ax, 70, 22, 24, 12, "到达 every？\n→ 执行并清零", kind="ok", size=9.6)
    F.arrow(ax, 30, 28, 36, 28)
    F.arrow(ax, 64, 28, 70, 28)

    F.lane(ax, 42, 6.5, "分频任务表")
    tasks = [
        (6, "dom\n500 ms\n批量刷写"),
        (22, "clock\n1000 ms\n顶栏时间"),
        (38, "chart\n2000 ms\n脏标记重绘"),
        (54, "heartbeat\n5000 ms\n看门狗"),
        (70, "persist\n30000 ms\n趋势落盘"),
        (85.5, "try/catch\n逐任务兜底", ),
    ]
    for x, t in tasks:
        F.box(ax, x, 50, 13, 14, t, kind="info", size=8.8)
    F.arrow(ax, 82, 34, 91.5, 49, kind="gray")

    F.box(ax, 6, 70, 38, 14,
          "pending 队列\nfields · pumps · flags · sliders", kind="warn", size=9.4)
    F.box(ax, 50, 70, 44, 14,
          "flushDom() 一次写完\n写前比较 __qhText / __qhStyle_* / __qhCls_*", kind="ok", size=9.4)
    F.arrow(ax, 44, 77, 50, 77)
    F.panel(ax, 6, 87, 88, 10,
            "值没变就完全跳过写入：传感器每秒上报，但多数字段并未变化；"
            "滑块正在被拖动时也不会被后台刷新抢走。", size=9.6)
    F.save(fig, "x_tick.png")


# ---------------------------------------------------------------- 14-1 界面
def x_ui_panel():
    fig, ax = F.canvas("图 14-1 监控台界面分区与挂载点",
                       "内容按“总览 → 分区 → 明细”组织，主屏三列；窄屏按同一 DOM 顺序折行")
    F.box(ax, 4, 20, 92, 7,
          "顶栏：青禾智灌　田间监控台　地块下拉　日期时钟　知识库/智能洞察/AI 助手/系统设置　"
          "华为云·传感器状态点", kind="ok", size=9.4)
    F.box(ax, 4, 29, 92, 6, "概览带：今日建议 · 未来 6 日累计雨 · 近 7 日灌溉用水 · 未确认告警",
          kind="warn", size=9.4)
    F.box(ax, 4, 37, 30, 26,
          "左列\n田间小气候\n田间实时数据（4 读数 + 2 泵）\nRORI 风险与三档图例",
          kind="info", size=9.2)
    F.box(ax, 36, 37, 28, 26, "中列\n未来七日雨情与灌溉建议\n告警记录",
          kind="info", size=9.2)
    F.box(ax, 66, 37, 30, 26, "右列\n调控与阈值（手动调控 / 预设 / 阈值）\n运行日志",
          kind="info", size=9.2)
    F.box(ax, 4, 65, 92, 10, "实时趋势：水位 / 湿度 / RORI 三图联动，2 s 节流重绘",
          kind="ok", size=9.4)
    F.box(ax, 4, 77, 92, 9,
          "浮层：系统设置 · AI 助手 · 智能洞察（告警/日志/设备/AI 预案/节水减碳）· 站内弹窗 · Toast",
          kind="gray", size=9.4)
    F.panel(ax, 4, 89, 92, 8,
            "挂载点举例：waterDisplay、soilDisplay、roriDisplay、alertList、logList、"
            "waterChart、configModal —— 前后端与测试共同依赖这张契约。", size=9.4)
    F.save(fig, "x_ui_panel.png")


# ---------------------------------------------------------------- 16-1 测试
def x_test_layers():
    fig, ax = F.canvas("图 16-1 测试分层",
                       "越往下越多、越快、越便宜；越往上越少、越慢、越接近真实使用")
    rows = [
        (46, "端到端浏览器断言", "tools/visual_check.py · 17 条结构断言", "warn", 8),
        (44, "前端逻辑测试（Node）", "tests/js/*.test.mjs · 9 个文件 · 算法同构/转义/去重/面积", "info", 14),
        (33, "接口与集成测试", "tests/test_*_routes.py 等 · 鉴权、校验、状态机、地块隔离", "ok", 20),
        (22, "算法与纯函数单元测试", "pytest 955 个用例 · RORI/阈值/心跳/指标/状态机", "ok", 26),
    ]
    y = 24
    for w, name, detail, kind, _ in rows:
        x = 50 - w / 2
        F.box(ax, x, y, w, 13, name, kind=kind, size=10.5, bold=True)
        ax.text(50, y + 17.5, detail, fontsize=9.2, color="#5A6B60", ha="center")
        y += 21
    ax.text(50, 21, "测试金字塔（自上而下收敛）", fontsize=9.6, color=GREEN,
            ha="center", va="bottom")
    F.panel(ax, 6, 88, 88, 9,
            "验收红线：pytest 0 failed / 0 error；禁止 pytest.skip 与注释断言让用例“变绿”——"
            "一条被跳过的用例与一条不存在的用例差别，只是报告里多一行 s。", size=9.6)
    F.save(fig, "x_test_layers.png")


if __name__ == "__main__":
    for fn in (x_layers, x_thread, x_migration, x_rori_norm, x_rori_fuse,
               x_histwriter, x_mqtt, x_alertdedup, x_realtime, x_ai_fallback,
               x_http_pipeline, x_plan_ttl, x_tick, x_ui_panel, x_test_layers):
        fn()
