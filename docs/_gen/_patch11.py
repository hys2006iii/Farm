# -*- coding: utf-8 -*-
"""插入详细设计说明书第 9~12 张图（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("x_realtime.png", "图 9-1 SocketIO 房间模型与事件契约")
def x_realtime():
    W, H = 12.6, 8.8
    f, ax = canvas(W, H)
    title(ax, W, H, "图 9-1  SocketIO 房间模型与事件契约",
          "每个用户一个房间 room=str(uid)，下行只投递到本房间，房间之间天然隔离")

    # 事件契约表
    cols = [0.60, 2.70, 3.90, 6.30, 12.00]
    rows = [6.10, 6.45, 6.80, 7.15]
    plain(ax, 0.60, 6.10, 11.40, 1.05, "", fc=WHITE, ec=GRAY, lw=1.2)
    plain(ax, 0.60, 7.15, 11.40, 0.38, "", fc=DEEP, ec=DEEP, lw=1.2)
    for y in rows:
        line(ax, [(0.60, y), (12.00, y)], color=SOFT, lw=1.0)
    for x in cols[1:-1]:
        line(ax, [(x, 6.10), (x, 7.53)], color=SOFT, lw=1.0)
    heads = ["事件名", "方向", "载荷", "房间 / 说明"]
    for i, h in enumerate(heads):
        ax.text(cols[i] + 0.14, 7.34, h, ha="left", va="center", fontsize=9.5,
                color=WHITE, weight="bold", zorder=6)
    data = [("hw_data", "下行", "type = data：四路读数 + RORI + 泵态", "room = str(uid)"),
            ("hw_data", "下行", "type = device_status：在线 / 心跳 / 最后上报", "room = str(uid)"),
            ("send_command", "上行", "{ device, action }：手动控泵", "由浏览器发往服务端")]
    for i, r in enumerate(data):
        y = 6.62 - i * 0.35
        for j, cell in enumerate(r):
            ax.text(cols[j] + 0.14, y, cell, ha="left", va="center", fontsize=9,
                    color=INK if j != 1 else (GREEN if cell == "下行" else ORANGE),
                    zorder=6)

    # 服务端链路
    box(ax, 0.60, 4.62, 3.50, 0.80, "emit_hw_data(uid, payload)\n只做序列化与选房", fc=LIGHT,
        ec=GREEN, fs=9.5, r=0.07)
    box(ax, 0.60, 3.55, 3.50, 0.80, "socketio.emit('hw_data',\npayload, room=str(uid))",
        fc=ORANGE_L, ec=ORANGE, fs=9.5, r=0.07)
    arrow(ax, (2.35, 4.62), (2.35, 4.37), color=GREEN, lw=1.6, ms=11)

    # 两个房间
    for i, (x, uid, pages) in enumerate([(4.55, "1", ["tab 1 · 控制台", "tab 2 · 手机"]),
                                        (8.60, "2", ["tab 1 · 控制台"])]):
        box(ax, x, 2.95, 3.45, 2.85, "", fc=PALE, ec=GREEN, lw=1.5, r=0.09, ls="--")
        label(ax, x + 1.72, 5.52, "room = \"%s\"（用户 %s）" % (uid, uid), fs=10,
              color=DEEP, weight="bold")
        for j, p in enumerate(pages):
            box(ax, x + 0.22, 4.60 - j * 0.95, 3.00, 0.72, p, fc=WHITE, ec=GRAY, fs=9.5,
                lw=1.2, r=0.06)
        label(ax, x + 1.72, 3.28, "只收本房间事件", fs=9, color=GRAY)

    arrow(ax, (4.12, 3.95), (4.52, 3.95), color=GREEN, lw=1.7, ms=12)
    arrow(ax, (2.60, 3.55), (2.60, 3.10), color=GRAY, lw=1.2, ms=10, ls=":")
    line(ax, [(2.60, 3.10), (8.35, 3.10)], color=GRAY, lw=1.2, ls=":")
    arrow(ax, (8.35, 3.10), (8.35, 2.93), color=GRAY, lw=1.2, ms=10, ls=":")

    # 隔离边界
    line(ax, [(8.35, 2.95), (8.35, 5.80)], color=RED, lw=1.6, ls="--")
    label(ax, 8.35, 5.95, "跨房间隔离边界", fs=9, color=RED, weight="bold")

    box(ax, 0.60, 0.80, 11.40, 1.30,
        "隔离要点：房间号直接取 uid，服务端从不做全站广播；同一用户开多个标签页共享一个房间，"
        "事件按 socket.io 连接广播给该房间内的所有页面。\n"
        "上行 send_command 必须重新鉴权并校验动作白名单，不得因为在下行房间里就默认可信。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07, ls_spacing=1.55)
    save(f, "x_realtime.png")


@fig("x_ai_fallback.png", "图 10-1 外部调用超时降级链路")
def x_ai_fallback():
    W, H = 13.2, 8.8
    f, ax = canvas(W, H)
    title(ax, W, H, "图 10-1  外部调用超时降级链路",
          "四类外部依赖各自有超时与兜底返回值，异常一律不出请求栈")

    cols = [(0.55, 2.25), (2.95, 1.05), (4.15, 2.55), (6.90, 3.35), (10.40, 2.25)]
    heads = ["外部服务", "超时", "失败形态", "兜底返回", "调用方感受"]
    for (x, w), h in zip(cols, heads):
        box(ax, x, 6.95, w, 0.50, h, fc=DEEP, ec=DEEP, fs=10, tc=WHITE, weight="bold",
            r=0.05)

    rows = [
        ("和风天气", "8 s", "连接超时 / 非 200 / 字段缺失",
         "{'code': 'ERR', 'error': '...'}", "前端提示天气暂不可用", 6.25),
        ("DeepSeek", "20 s", "超时 / 非 200 / 非 JSON / 内网域名被 SSRF 拦截",
         "_wrap() 成 {'choices':[{'message':\n{'content': ...}}]}", "AI 面板给出兜底话术", 4.95),
        ("钉钉 Webhook", "3 s", "连接超时 / 返回 errcode ≠ 0", "sent = false，接口仍返回 200",
         "告警已落库，仅推送失败", 3.65),
        ("Photon 逆地理", "6 s", "超时 / 无匹配地址", "返回 \"经度,纬度\" 文本兜底",
         "地图仍可显示坐标", 2.35),
    ]
    for name, to, fail, fallback, feel, y in rows:
        box(ax, cols[0][0], y, cols[0][1], 1.05, name, fc=LIGHT, ec=GREEN, fs=10, r=0.07)
        box(ax, cols[1][0], y + 0.28, cols[1][1], 0.50, to, fc=ORANGE_L, ec=ORANGE, fs=10,
            weight="bold", r=0.06)
        box(ax, cols[2][0], y, cols[2][1], 1.05, fail, fc=WHITE, ec=GRAY, fs=8.8, lw=1.2,
            r=0.07)
        box(ax, cols[3][0], y, cols[3][1], 1.05, fallback, fc=ORANGE_L, ec=ORANGE, fs=8.8,
            lw=1.2, r=0.07)
        box(ax, cols[4][0], y, cols[4][1], 1.05, feel, fc=PALE, ec=SOFT, fs=8.8, tc=INK,
            lw=1.1, r=0.07)
        arrow(ax, (cols[1][0] + cols[1][1], y + 0.52), (cols[2][0], y + 0.52), color=GRAY,
              lw=1.2, ms=9)
        arrow(ax, (cols[2][0] + cols[2][1], y + 0.52), (cols[3][0], y + 0.52),
              color=RED, lw=1.3, ms=9, ls="--")
        arrow(ax, (cols[3][0] + cols[3][1], y + 0.52), (cols[4][0], y + 0.52),
              color=GREEN, lw=1.3, ms=9)

    box(ax, 0.55, 0.95, 12.10, 1.05,
        "共同原则：所有外部调用显式传 timeout，用 try/except 包住，异常只返回结构化兜底值并记 warning；"
        "调用方永远拿到「形状正确」的数据，不需要在外层再判空。\n"
        "这与 AGENTS.md 的硬性规则一致：外部网络调用的异常不得向上抛到请求栈。",
        fc=RED_L, ec=RED, fs=9.5, tc=INK, lw=1.2, r=0.07, ls_spacing=1.55)
    save(f, "x_ai_fallback.png")


@fig("x_http_pipeline.png", "图 11-1 HTTP 请求处理流水线")
def x_http_pipeline():
    W, H = 11.4, 9.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 11-1  HTTP 请求处理流水线",
          "校验与鉴权失败在进入业务层之前短路，统一返回结构化响应")

    cx, cw = 2.60, 4.30
    steps = [("① 浏览器请求", "fetch / 表单提交，带 credentials"),
             ("② Flask 路由", "蓝图 api_* 命中，取入参"),
             ("③ 鉴权", "Session 或 JWT，二选一"),
             ("④ validators 校验", "类型 / 范围 / 长度"),
             ("⑤ 业务层", "纯函数与状态机"),
             ("⑥ DAO", "参数化 SQL 读写"),
             ("⑦ 响应组装", "jsonify 统一形状")]
    ys = [8.30, 7.45, 6.60, 5.75, 4.90, 4.05, 3.20]
    for (name, desc), y in zip(steps, ys):
        box(ax, cx, y, cw, 0.62, "%s\n%s" % (name, desc), fc=LIGHT, ec=GREEN, fs=9.5,
            r=0.07)
    for i in range(6):
        arrow(ax, (cx + cw / 2, ys[i]), (cx + cw / 2, ys[i + 1] + 0.62), color=GREEN,
              lw=1.5, ms=11)

    # 短路分支
    box(ax, 7.40, 6.55, 3.45, 0.70, "401 / 403\n未登录或权限不足", fc=RED_L, ec=RED,
        fs=9.5, lw=1.3, r=0.07)
    arrow(ax, (cx + cw, 6.91), (7.38, 6.91), color=RED, lw=1.4, ms=11, ls="--")
    box(ax, 7.40, 5.70, 3.45, 0.70, "400 / 422\n入参非法，附中文原因", fc=RED_L, ec=RED,
        fs=9.5, lw=1.3, r=0.07)
    arrow(ax, (cx + cw, 6.06), (7.38, 6.06), color=RED, lw=1.4, ms=11, ls="--")
    label(ax, 9.10, 6.50, "短路：不进入业务层", fs=9, color=RED)

    # 统一响应
    box(ax, 1.60, 1.35, 3.30, 1.10, "{'status': 'success',\n'data': {...}}", fc=LIGHT,
        ec=GREEN, fs=9.5, r=0.08)
    box(ax, 5.30, 1.35, 3.30, 1.10, "{'error': '中文原因'}", fc=RED_L, ec=RED, fs=9.5,
        lw=1.3, r=0.08)
    arrow(ax, (6.40, 3.20), (3.25, 2.47), color=GREEN, lw=1.4, ms=11, rad=-0.15)
    label(ax, 4.75, 2.85, "统一响应形状", fs=9.5, color=DEEP, weight="bold")

    box(ax, 0.55, 0.45, 10.30, 0.62,
        "约定：任何分支都返回 JSON，不返回 HTML 错误页；状态码与 body 语义必须一致。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.06)
    save(f, "x_http_pipeline.png")


@fig("x_plan_ttl.png", "图 12-1 决策预案状态机与 600 秒 TTL")
def x_plan_ttl():
    W, H = 12.6, 8.8
    f, ax = canvas(W, H)
    title(ax, W, H, "图 12-1  决策预案状态机与 600 秒 TTL",
          "pending 是唯一可操作的中间态，四个终态均不可再跃迁")

    box(ax, 1.10, 5.20, 2.55, 0.95, "pending\nAI 生成，等待人工确认", fc=ORANGE_L, ec=ORANGE,
        fs=9.5, weight="bold", r=0.09)
    states = [
        ("confirmed", "人工确认并逐条下发成功", 6.90, LIGHT, GREEN),
        ("rejected", "人工拒绝，不下发任何指令", 5.60, WHITE, GRAY),
        ("expired", "超过 600 s 未处理，自动过期", 4.30, RED_L, RED),
        ("failed", "下发失败且重试耗尽", 3.00, GRAY_L, GRAY),
    ]
    for name, desc, y, fc, ec in states:
        box(ax, 7.60, y, 2.60, 0.80, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=9.5,
            lw=1.4, r=0.08)
        arrow(ax, (3.65, 5.675), (7.58, y + 0.40), color=GREEN if name == "confirmed" else GRAY,
              lw=1.4, ms=10, rad=0.06)

    # TTL 计时弧
    ax.add_patch(Arc((3.375, 5.675), 3.60, 2.20, theta1=250, theta2=350, color=RED,
                     lw=1.6, ls="--", zorder=5))
    label(ax, 4.85, 4.05, "600 s 倒计时", fs=9.5, color=RED, weight="bold")
    arrow(ax, (4.30, 4.20), (6.95, 4.70), color=RED, lw=1.4, ms=11, ls="--")

    # 确认校验链
    label(ax, 0.55, 2.55, "confirm 的校验链（任一不通过即返回错误）", fs=10.5, color=DEEP,
          weight="bold", ha="left")
    checks = [("① 归属", "plan.user_id == 当前 uid"), ("② 状态", "status 必须为 pending"),
              ("③ TTL", "now < expire_at，否则置 expired"),
              ("④ 白名单", "ALLOWED_DEVICES / ALLOWED_ACTIONS")]
    for i, (name, desc) in enumerate(checks):
        x = 0.55 + i * 3.10
        box(ax, x, 1.55, 2.85, 0.85, "%s\n%s" % (name, desc), fc=WHITE, ec=GREEN, fs=9,
            lw=1.2, r=0.07)
        if i < 3:
            arrow(ax, (x + 2.85, 1.975), (x + 3.05, 1.975), color=GREEN, lw=1.3, ms=10)

    box(ax, 0.55, 0.45, 11.90, 0.75,
        "终态语义：confirmed / rejected / expired / failed 都不可再跃迁，重复 confirm 只返回当前状态；"
        "过期判定在读取与确认两处各做一次。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "x_plan_ttl.png")


# @@APPEND@@'''

s = io.open(P, encoding="utf-8").read()
assert "# @@APPEND@@" in s
s = s.replace("# @@APPEND@@", NEW.strip("\n"))
io.open(P, "w", encoding="utf-8").write(s)
print("appended batch C")
