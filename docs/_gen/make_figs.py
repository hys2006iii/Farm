# -*- coding: utf-8 -*-
"""青禾智灌智慧灌溉管理平台 —— 设计说明书示意图批量生成脚本。

用法::

    python docs/_gen/make_figs.py            # 生成全部 27 张
    python docs/_gen/make_figs.py g_arch     # 只生成名字包含 g_arch 的图

只使用 matplotlib（本机无 graphviz dot），结构图全部用 FancyBboxPatch +
FancyArrowPatch 手工布局，坐标单位 = 英寸（画布铺满 figure），便于字号与尺寸对齐。
每张图宽度 ≥ 1600 px（dpi=200，figsize 宽 ≥ 8 in），白底，可重复运行且幂等
（先写临时文件再 os.replace 原子覆盖）。
"""
from __future__ import annotations

import os
import re
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    Arc,
    Circle,
    Ellipse,
    FancyArrowPatch,
    FancyBboxPatch,
    Polygon,
    Rectangle,
)
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402

# ---------------------------------------------------------------- 字体与画布
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figs")

FONT_CANDIDATES = ["Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "SimSun"]
FONT = None
for _name in FONT_CANDIDATES:
    try:
        _path = fm.findfont(_name, fallback_to_default=False)
    except Exception:
        continue
    if _path and os.path.exists(_path):
        FONT = _name
        break
if FONT is None:  # 理论上不会发生，兜底避免整脚本崩掉
    FONT = "sans-serif"

plt.rcParams["font.sans-serif"] = [FONT, "DejaVu Sans"]
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["savefig.facecolor"] = "white"
plt.rcParams["figure.dpi"] = 200
plt.rcParams["savefig.dpi"] = 200

DPI = 200

# 字体字形覆盖表：用于检测会渲染成“方框”的字符
try:
    from matplotlib.ft2font import FT2Font

    _CMAP = set(FT2Font(fm.findfont(FONT)).get_charmap().keys())
except Exception:  # pragma: no cover
    _CMAP = set(range(32, 0x2FFF))

# ---------------------------------------------------------------- 配色
DEEP = "#174D32"      # 深绿（主标题 / 深色底）
GREEN = "#1F6B45"     # 主绿（边框 / 箭头）
MID = "#2F7A52"       # 中间绿
LIGHT = "#E7F3EB"     # 浅绿底
PALE = "#F5FAF6"      # 更浅底
SOFT = "#D8E8DD"      # 浅绿描边
GRAY = "#6B7A72"      # 次级灰
GRAY_L = "#EEF2EF"    # 浅灰底
ORANGE = "#C77A2B"    # 强调橙
ORANGE_L = "#FBF0E2"  # 浅橙底
RED = "#B5322F"       # 警示红
RED_L = "#F8E6E5"     # 浅红底
WHITE = "#FFFFFF"
INK = "#22302A"       # 正文近黑

# ---------------------------------------------------------------- 基础绘图件
ORDER = []


def fig(name: str, caption: str):
    """注册一张图：文件名 / 图题，按定义顺序生成。"""

    def deco(fn):
        ORDER.append((name, caption, fn))
        return fn

    return deco


def canvas(w: float, h: float):
    """建一块 w×h 英寸的白底画布，坐标 1 单位 = 1 英寸。"""
    f = plt.figure(figsize=(w, h), facecolor="white")
    ax = f.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0.0, w)
    ax.set_ylim(0.0, h)
    ax.set_axis_off()
    ax.set_facecolor("white")
    return f, ax


def box(ax, x, y, w, h, text="", fc=LIGHT, ec=GREEN, fs=11, tc=INK, lw=1.6,
        r=0.10, ha="center", va="center", weight="normal", ls="-", z=3,
        alpha=1.0, ls_spacing=1.45, pad=0.0):
    """圆角矩形 + 居中（或对齐）文字。返回 patch。"""
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle="round,pad=%s,rounding_size=%s" % (pad, r),
                       linewidth=lw, edgecolor=ec, facecolor=fc,
                       linestyle=ls, zorder=z, alpha=alpha,
                       joinstyle="round", mutation_aspect=1.0)
    ax.add_patch(p)
    if text:
        tx = x + w / 2.0 if ha == "center" else (x + 0.14 if ha == "left" else x + w - 0.14)
        _check_fit(text, fs, w, h, "box")
        ax.text(tx, y + h / 2.0, text, ha=ha, va=va, fontsize=fs, color=tc,
                weight=weight, zorder=z + 1, linespacing=ls_spacing)
    return p


def plain(ax, x, y, w, h, text="", fc=WHITE, ec=GRAY, fs=11, tc=INK, lw=1.4,
          ha="center", va="center", weight="normal", ls="-", z=3, alpha=1.0,
          ls_spacing=1.45):
    """直角矩形（表格 / 面板用）。"""
    ax.add_patch(Rectangle((x, y), w, h, linewidth=lw, edgecolor=ec, facecolor=fc,
                           linestyle=ls, zorder=z, alpha=alpha))
    if text:
        tx = x + w / 2.0 if ha == "center" else (x + 0.12 if ha == "left" else x + w - 0.12)
        _check_fit(text, fs, w, h, "plain")
        ax.text(tx, y + h / 2.0, text, ha=ha, va=va, fontsize=fs, color=tc,
                weight=weight, zorder=z + 1, linespacing=ls_spacing)


def arrow(ax, p1, p2, color=GREEN, lw=1.8, style="-|>", rad=0.0, ls="-",
          ms=13, z=4, shrinkA=1.0, shrinkB=1.0, alpha=1.0):
    a = FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=ms, color=color,
                        linewidth=lw, linestyle=ls, zorder=z, alpha=alpha,
                        connectionstyle="arc3,rad=%s" % rad,
                        shrinkA=shrinkA, shrinkB=shrinkB)
    ax.add_patch(a)
    return a


def line(ax, pts, color=GREEN, lw=1.6, ls="-", z=2, alpha=1.0):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=z, alpha=alpha,
            solid_capstyle="round")


def label(ax, x, y, text, fs=10, color=GRAY, ha="center", va="center",
          weight="normal", z=6, rot=0, ls_spacing=1.4, bbox=None):
    kw = {}
    if bbox is not None:
        kw["bbox"] = bbox
    return ax.text(x, y, text, fontsize=fs, color=color, ha=ha, va=va,
                   weight=weight, zorder=z, rotation=rot,
                   linespacing=ls_spacing, **kw)


def diamond(ax, cx, cy, w, h, text="", fc=ORANGE_L, ec=ORANGE, fs=10.5, tc=INK, lw=1.6, z=3):
    pts = [(cx, cy + h / 2.0), (cx + w / 2.0, cy), (cx, cy - h / 2.0), (cx - w / 2.0, cy)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=fc, edgecolor=ec, lw=lw, zorder=z))
    if text:
        ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color=tc,
                zorder=z + 1, linespacing=1.35)
    return pts


def title(ax, W, H, text, sub=None, fs=17, y=None):
    y = H - 0.42 if y is None else y
    ax.text(W / 2.0, y, text, ha="center", va="center", fontsize=fs,
            color=DEEP, weight="bold", zorder=9)
    if sub:
        ax.text(W / 2.0, y - 0.36, sub, ha="center", va="center", fontsize=11,
                color=GRAY, zorder=9)
    # 标题下细线
    ax.plot([0.55, W - 0.55], [y - (0.58 if sub else 0.30)] * 2,
            color=SOFT, lw=1.4, zorder=8)


def note(ax, x, y, w, text, fs=9.5, fc=PALE, ec=SOFT, tc=GRAY, h=None, ha="left"):
    """画一条说明条（自适应高度）。"""
    n_lines = text.count("\n") + 1
    hh = h if h is not None else 0.24 * n_lines + 0.20
    box(ax, x, y, w, hh, text, fc=fc, ec=ec, fs=fs, tc=tc, lw=1.1, r=0.07, ha=ha)
    return hh


# ---------------------------------------------------------------- 自检
def _text_items(f, renderer):
    dpi = f.dpi
    items = []
    for ax in f.axes:
        cands = list(ax.texts)
        cands.append(ax.title)
        cands.append(ax.xaxis.label)
        cands.append(ax.yaxis.label)
        if ax.axison:  # 隐藏坐标轴的画布没有刻度标签被真正绘制
            try:
                cands.extend(list(ax.get_xticklabels()))
                cands.extend(list(ax.get_yticklabels()))
            except Exception:
                pass
        for t in cands:
            try:
                s = t.get_text()
            except Exception:
                continue
            if not s or not s.strip():
                continue
            try:
                bb = t.get_window_extent(renderer=renderer)
            except Exception:
                continue
            items.append((s, bb.x0 / dpi, bb.y0 / dpi, bb.x1 / dpi, bb.y1 / dpi))
    return items


def _missing_glyphs(txt):
    """返回该字符串里字体画不出来（会变成方框）的字符。"""
    plain = re.sub(r"\$[^$]*\$", "", txt)
    return sorted({ch for ch in plain if ord(ch) > 127 and ord(ch) not in _CMAP})


_OVERFLOW = []


def _est_text(s, fs):
    """估算多行文本的 (宽, 高)，单位英寸；只用字体度量，不需要 renderer。"""
    wmax, hsum = 0.0, 0.0
    for lineno in s.split("\n"):
        try:
            tp = TextPath((0, 0), lineno, size=fs, prop=FontProperties(family=FONT))
            w = tp.get_extents().width / 72.0
        except Exception:
            w = len(lineno) * fs / 72.0 * 0.9
        wmax = max(wmax, w)
        hsum += fs * 1.2 / 72.0
    return wmax, hsum


def _check_fit(s, fs, w, h, tag=""):
    """记录文字是否超出它所在的框。"""
    tw, th = _est_text(s, fs)
    if tw > w - 0.08:
        _OVERFLOW.append("[文字过宽 %.2f > %.2f] %s %r" % (tw, w - 0.08, tag, s[:30]))
    if th > h - 0.05:
        _OVERFLOW.append("[文字过高 %.2f > %.2f] %s %r" % (th, h - 0.05, tag, s[:30]))


def audit(f, name):
    """粗检：文字是否超出画布、是否有文字互相压叠、是否有缺字形。"""
    f.canvas.draw()
    try:
        renderer = f.canvas.get_renderer()
    except Exception:
        return
    items = _text_items(f, renderer)
    W, H = f.get_size_inches()
    n_bad = 0
    for s, _x0, _y0, _x1, _y1 in items:
        miss = _missing_glyphs(s)
        if miss:
            n_bad += 1
            print("  [缺字形→方框] %s: %r 缺 %r" % (name, s[:26], "".join(miss)))
    for s, x0, y0, x1, y1 in items:
        if x0 < -0.03 or y0 < -0.03 or x1 > W + 0.03 or y1 > H + 0.03:
            n_bad += 1
            print("  [超出画布] %s: %r  x[%.2f,%.2f] y[%.2f,%.2f] 画布 %.1fx%.1f"
                  % (name, s[:26], x0, x1, y0, y1, W, H))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s1, a1, b1, c1, d1 = items[i]
            s2, a2, b2, c2, d2 = items[j]
            ox = min(c1, c2) - max(a1, a2)
            oy = min(d1, d2) - max(b1, b2)
            if ox > 0.05 and oy > 0.05:
                n_bad += 1
                print("  [文字重叠] %s: %r <-> %r  %.2fx%.2f in"
                      % (name, s1[:22], s2[:22], ox, oy))
    for msg in _OVERFLOW:
        n_bad += 1
        print("  [框内溢出] %s: %s" % (name, msg))
    _OVERFLOW.clear()
    if n_bad == 0:
        print("    · 排版自检通过（%d 个文本对象，无越界/无重叠/无缺字形）" % len(items))
    else:
        print("    ! 排版自检发现 %d 处问题，需调整" % n_bad)
    return n_bad


def save(f, name):
    audit(f, name)
    path = os.path.join(OUT_DIR, name)
    tmp = path + ".tmp.png"
    f.savefig(tmp, dpi=DPI, facecolor="white")
    plt.close(f)
    os.replace(tmp, path)
    kb = os.path.getsize(path) / 1024.0
    print("  -> %s  (%.1f KB)" % (name, kb))


# ================================================================ 概要设计 12 张
@fig("g_arch.png", "图 2-1 系统六层逻辑架构")
def g_arch():
    W, H = 12.0, 8.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 2-1  系统六层逻辑架构", "严格单向依赖：只允许上层调用下层，下层不得反向引用上层")

    layers = [
        ("表现层", "templates/index.html · login.html ｜ static/js · static/css ｜ Socket.IO 客户端",
         LIGHT, GREEN, DEEP),
        ("接口层", "routes/api_*.py 蓝图 ｜ @login_required 鉴权 ｜ 统一响应 {status|error}",
         LIGHT, GREEN, DEEP),
        ("业务层", "irrigation（RORI·动态阈值·自动调控）｜ planner ｜ alerts ｜ weather ｜ ai",
         ORANGE_L, ORANGE, INK),
        ("数据访问层", "db.py DAO：get_* / save_* / insert_* ｜ 参数化 SQL（占位 ?）｜ 连接上下文管理",
         LIGHT, GREEN, DEEP),
        ("存储层", "SQLite3 单文件 · journal_mode=WAL · 12 张业务表 + 索引",
         GRAY_L, GRAY, INK),
        ("集成层", "华为云 IoTDA（MQTT）｜ 和风天气 ｜ DeepSeek ｜ 钉钉 Webhook ｜ Photon",
         LIGHT, GREEN, DEEP),
    ]
    top, lh, gap = 7.20, 0.92, 0.17
    for i, (name, desc, fc, ec, tc) in enumerate(layers):
        y = top - (i + 1) * lh - i * gap
        box(ax, 0.45, y, 1.25, lh, name, fc=ec, ec=ec, fs=11, tc=WHITE, weight="bold", r=0.09)
        box(ax, 1.80, y, 9.15, lh, desc, fc=fc, ec=ec, fs=10.5, tc=tc, r=0.09)

    # 右侧“依赖只向下”大箭头
    arrow(ax, (11.42, 7.32), (11.42, 0.72), color=DEEP, lw=2.6, style="-|>", ms=26)
    label(ax, 11.80, 4.02, "依赖只向下", fs=11.5, color=DEEP, weight="bold", rot=90)
    label(ax, 11.42, 7.52, "调用方向", fs=9.5, color=GRAY)
    label(ax, 11.42, 0.50, "不得回流", fs=9.5, color=GRAY)

    label(ax, 6.0, 0.38,
          "跨层直连（如 routes 内联 SQL）视为违规；集成层只被业务层调用，不反向引用业务层",
          fs=9.5, color=GRAY)
    save(f, "g_arch.png")


@fig("g_creative.png", "图 2-2 四阶段闭环协同调控架构")
def g_creative():
    W, H = 10.6, 8.6
    f, ax = canvas(W, H)
    title(ax, W, H, "图 2-2  四阶段闭环协同调控架构", "感知 → 决策 → 调控 → 评估，评估结果反哺下一轮决策")

    cx, cy = 5.30, 3.95
    bw, bh = 3.50, 1.30

    def stage(x, y, num, name, desc, fc, ec):
        box(ax, x, y, bw, bh, "%s\n%s" % (name, desc), fc=fc, ec=ec,
            fs=10.5, tc=INK, r=0.12, lw=1.8)
        ax.add_patch(Circle((x + 0.26, y + bh - 0.24), 0.17, facecolor=ec,
                            edgecolor=WHITE, lw=1.4, zorder=6))
        ax.text(x + 0.26, y + bh - 0.24, num, ha="center", va="center",
                fontsize=9.5, color=WHITE, weight="bold", zorder=7)

    # 上：感知
    stage(cx - bw / 2, cy + 1.85, "①", "感知",
          "MQTT 上报 · 心跳巡检\nADC 换算：水位 / 土壤 / DO / Eh", LIGHT, GREEN)
    # 右：决策
    stage(cx + 1.60, cy - bh / 2, "②", "决策",
          "RORI 风险分级\nP6d 降雨前馈 · 动态阈值", LIGHT, GREEN)
    # 下：调控
    stage(cx - bw / 2, cy - 1.85 - bh + 0.80 - 0.80, "③", "调控",
          "自动-手动切换\n气泵 / 水泵 · 滞回去抖", ORANGE_L, ORANGE)
    # 左：评估
    stage(cx - 1.60 - bw, cy - bh / 2, "④", "评估",
          "节水减碳核算\nAI 预案 · 运行日志", LIGHT, GREEN)

    # 闭环弧形箭头（顺时针）
    a1 = dict(color=MID, lw=2.0, ms=18, rad=-0.30)
    arrow(ax, (7.05, 6.35), (8.65, 4.60), **a1)
    arrow(ax, (8.65, 3.30), (7.05, 1.75), **a1)
    arrow(ax, (3.55, 1.75), (1.95, 3.30), **a1)
    arrow(ax, (1.95, 4.60), (3.55, 6.35), **a1)



    # 中心
    ax.add_patch(Circle((cx, cy), 1.00, facecolor=PALE, edgecolor=MID, lw=1.6,
                        linestyle=(0, (5, 3)), zorder=3))
    ax.text(cx, cy + 0.16, "四阶段", ha="center", va="center", fontsize=13,
            color=DEEP, weight="bold", zorder=4)
    ax.text(cx, cy - 0.20, "闭环协同", ha="center", va="center", fontsize=13,
            color=DEEP, weight="bold", zorder=4)
    label(ax, cx, cy - 0.55, "调控", fs=10, color=MID, z=4)

    label(ax, 5.3, 0.52,
          "顺时针闭合：数据上行 → 策略下发 → 执行反馈 → 效果评估 → 回到感知",
          fs=10, color=MID)
    label(ax, 5.3, 0.22,
          "闭环含义：④ 评估产出的节水率 / 减碳量 / 告警复盘结论写回配置，调整 ② 的阈值参数",
          fs=9.5, color=GRAY)
    save(f, "g_creative.png")


@fig("g_edgecloud.png", "图 2-3 边云协同与边缘自治保底机制")
def g_edgecloud():
    W, H = 12.2, 8.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 2-3  边云协同与边缘自治保底机制", "三层判断：L1 云端策略 / L2 边端红线强控 / L3 断网本地保底")

    # 两大框
    box(ax, 0.45, 1.05, 4.55, 5.55, "", fc=PALE, ec=GREEN, lw=2.0, r=0.14)
    box(ax, 7.20, 1.05, 4.55, 5.55, "", fc=PALE, ec=GREEN, lw=2.0, r=0.14)
    label(ax, 2.72, 6.36, "边缘端  ESP32-E", fs=13, color=DEEP, weight="bold")
    label(ax, 9.47, 6.36, "云平台  Flask + SocketIO", fs=13, color=DEEP, weight="bold")

    left = [
        ("传感器采集：水位 / 土壤含水率 / DO / Eh（ADC 12 bit）", LIGHT, GREEN, "-", INK),
        ("执行器：气泵 A·B / 水泵 / 电磁阀（GPIO 驱动）", LIGHT, GREEN, "-", INK),
        ("L2 边端红线强控：Eh ≤ −100 mV 或 DO ≤ 1.5 mg/L", RED_L, RED, "--", RED),
        ("L2 说明：越线立即本地强控，不等云端（设计中）", WHITE, RED, "--", RED),
        ("L3 断网本地保底：NVS 缓存阈值继续自治", ORANGE_L, ORANGE, "-", INK),
        ("网络恢复后批量补传未确认报文", LIGHT, GREEN, "-", INK),
    ]
    right = [
        ("L1 云端策略：RORI 分级 + P6d 动态阈值 + 滞回", LIGHT, GREEN, "-", INK),
        ("MQTT 客户端 → parse_mqtt_payload → ingest", LIGHT, GREEN, "-", INK),
        ("HistoryWriter 队列 → SQLite WAL → 历史统计", LIGHT, GREEN, "-", INK),
        ("evaluate_alerts → 冷却去重 → 钉钉推送", LIGHT, GREEN, "-", INK),
        ("SocketIO 实时推送 → 前端 tick 批量渲染", LIGHT, GREEN, "-", INK),
        ("心跳 / 在线状态 / 泵累计时长上报", LIGHT, GREEN, "-", INK),
    ]
    ys = [5.50, 4.72, 3.94, 3.16, 2.38, 1.60]
    for (t, fc, ec, ls, tc), y in zip(left, ys):
        box(ax, 0.72, y, 4.00, 0.62, t, fc=fc, ec=ec, ls=ls, fs=9.5, tc=tc, lw=1.3, r=0.07)
    for (t, fc, ec, ls, tc), y in zip(right, ys):
        box(ax, 7.47, y, 4.00, 0.62, t, fc=fc, ec=ec, ls=ls, fs=9.5, tc=tc, lw=1.3, r=0.07)

    # 中间 MQTT 链路
    arrow(ax, (5.06, 4.95), (7.14, 4.95), color=MID, lw=2.0, style="-|>", ms=16)
    arrow(ax, (7.14, 3.60), (5.06, 3.60), color=ORANGE, lw=2.0, style="-|>", ms=16)
    label(ax, 6.10, 5.22, "上报（遥测 / 心跳）", fs=9.5, color=MID)
    label(ax, 6.10, 3.33, "下发（调控指令）", fs=9.5, color=ORANGE)
    label(ax, 6.10, 4.28, "MQTT\n华为云 IoTDA\nQoS 1", fs=9.5, color=DEEP,
          weight="bold", bbox=dict(boxstyle="round,pad=0.28", fc=WHITE, ec=SOFT, lw=1.0))

    # 断网自治说明
    box(ax, 0.45, 0.22, 11.30, 0.62,
        "断网自治：云端不可达 → 边端按 NVS 缓存的 L1 阈值继续执行，L2 红线强控始终在本地生效；"
        "联网后补传数据，并以云端最新策略覆盖本地缓存",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.2, r=0.08)
    label(ax, 11.62, 2.35, "虚线红框\n= 设计中能力", fs=9, color=RED, ha="center")
    save(f, "g_edgecloud.png")


@fig("g_deploy.png", "图 3-1 运行环境与部署拓扑")
def g_deploy():
    W, H = 12.4, 8.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 3-1  运行环境与部署拓扑", "单进程 waitress 8 线程 + SQLite WAL，外部服务全部设超时")

    # 访问链路
    box(ax, 0.50, 5.85, 2.10, 0.95, "浏览器 / 手机\nChrome · Safari", fc=LIGHT, ec=GREEN, fs=10)
    box(ax, 3.25, 5.85, 2.45, 0.95, "校园网反向代理\nHTTPS :443 → :5000", fc=LIGHT, ec=GREEN, fs=10)
    box(ax, 6.40, 5.62, 2.20, 1.40, "waitress 8 线程\nFlask + SocketIO\n:5000", fc=LIGHT, ec=DEEP,
        fs=10, lw=2.0)
    arrow(ax, (2.60, 6.32), (3.25, 6.32), color=GREEN, lw=1.8)
    arrow(ax, (5.70, 6.32), (6.40, 6.32), color=GREEN, lw=1.8)
    label(ax, 2.92, 6.52, "HTTPS", fs=9, color=GRAY)
    label(ax, 6.05, 6.52, "HTTP", fs=9, color=GRAY)

    # SQLite
    box(ax, 5.40, 2.60, 3.30, 0.95, "SQLite 单文件（WAL）\nqinghe.db · 12 张表", fc=GRAY_L,
        ec=GRAY, fs=10)
    arrow(ax, (7.95, 5.62), (7.95, 3.55), color=GREEN, lw=1.8)
    label(ax, 8.28, 4.55, "读写\n事务", fs=9, color=GRAY)

    # 设备链路
    box(ax, 0.50, 2.60, 2.20, 0.95, "ESP32-E\n现场控制器", fc=ORANGE_L, ec=ORANGE, fs=10)
    box(ax, 3.05, 2.60, 2.20, 0.95, "华为云 IoTDA\nMQTT Broker", fc=LIGHT, ec=GREEN, fs=10)
    box(ax, 5.60, 1.10, 2.20, 0.95, "paho-mqtt 客户端\n每用户一条连接", fc=LIGHT, ec=GREEN, fs=10)
    arrow(ax, (2.70, 3.08), (3.05, 3.08), color=GRAY, lw=1.8, style="<|-|>", ms=11)
    arrow(ax, (5.25, 3.05), (5.60, 2.60), color=GRAY, lw=1.8, style="<|-|>", ms=11, rad=-0.12)
    arrow(ax, (6.70, 2.05), (6.70, 5.62), color=MID, lw=1.8, style="-|>", ms=14)
    label(ax, 6.32, 4.30, "遥测入队", fs=9, color=MID, rot=90)
    label(ax, 4.10, 3.28, "MQTT / TLS", fs=9, color=GRAY)

    # 右侧外部服务
    box(ax, 8.90, 2.85, 3.10, 4.05, "", fc=PALE, ec=GREEN, lw=1.6, r=0.12)
    label(ax, 10.45, 6.62, "外部服务与超时", fs=11.5, color=DEEP, weight="bold")
    ext = [("和风天气 API", "timeout = 8 s", LIGHT, GREEN),
           ("DeepSeek Chat", "timeout = 20 s", LIGHT, GREEN),
           ("钉钉 Webhook", "timeout = 3 s", LIGHT, GREEN),
           ("Photon 逆地理", "timeout = 6 s", LIGHT, GREEN)]
    y = 5.75
    for name, tmo, fc, ec in ext:
        box(ax, 9.10, y, 2.70, 0.62, "%s\n%s" % (name, tmo), fc=fc, ec=ec, fs=9.5, r=0.07)
        y -= 0.78
    label(ax, 10.45, 3.12, "全部异常内部消化，不抛到请求栈", fs=9, color=GRAY)

    # 部署要点
    box(ax, 8.90, 0.95, 3.10, 1.60,
        "部署要点\n· FARM_DEBUG=0（生产）\n· 密钥一律取自环境变量\n· WAL 支持多读单写\n· MQTT 与 Web 同宿主进程",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.2, r=0.08)
    label(ax, 5.00, 0.55, "校园内网部署：设备 → 华为云 IoTDA → 平台，浏览器经反向代理访问平台",
          fs=9.5, color=GRAY)
    save(f, "g_deploy.png")


@fig("g_module_dep.png", "图 4-1 模块依赖关系")
def g_module_dep():
    W, H = 12.2, 9.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 4-1  模块依赖关系", "config 是最底层叶子，任何模块只依赖同层或更下层模块")

    bands = [
        (7.10, 1.05, "装配层", "调用方", LIGHT, GREEN,
         [("routes/*.py", "HTTP 蓝图：api_auth · api_config\napi_plans · api_export", 1.95, 4.00),
          ("realtime", "SocketIO 房间推送\n依赖 iot + heartbeat", 6.35, 4.00)]),
        (5.35, 1.25, "编排层", "聚合", LIGHT, GREEN,
         [("alert_center", "db + alerts", 1.95, 0.00), ("logbook", "db", 3.64, 0.0),
          ("heartbeat", "iot + db", 5.33, 0.0), ("planner", "db + irrigation", 7.02, 0.0),
          ("metrics", "db", 8.71, 0.0), ("autocontrol", "irrigation + db", 10.40, 0.0)]),
        (3.60, 1.25, "服务层", "领域", LIGHT, GREEN,
         [("auth", "config + db", 1.95, 0.0), ("iot", "config + db", 3.95, 0.0),
          ("weather", "config", 5.95, 0.0), ("ai", "config + db", 7.95, 0.0),
          ("irrigation", "config + db", 9.95, 0.0)]),
        (2.25, 0.95, "数据访问层", "DAO", GRAY_L, GRAY,
         [("db.py", "get_* / save_* / insert_*，参数化 SQL", 1.95, 5.20)]),
        (0.80, 0.95, "配置层", "叶子", ORANGE_L, ORANGE,
         [("config.py", "只 import os，常量全大写", 1.95, 4.20)]),
    ]

    for y, h, name, tag, fc, ec, chips in bands:
        box(ax, 0.45, y, 11.50, h, "", fc=PALE, ec=SOFT, lw=1.3, r=0.10, ls="--")
        box(ax, 0.45, y, 1.35, h, "%s\n%s" % (name, tag), fc=ec, ec=ec, fs=9.5,
            tc=WHITE, weight="bold", r=0.08)
        for cname, cdep, cx, cw in chips:
            w = cw if cw else (1.85 if name == "服务层" else 1.55)
            box(ax, cx, y + 0.20, w, h - 0.40, "%s\n%s" % (cname, cdep), fc=fc, ec=ec,
                fs=9, tc=INK, lw=1.2, r=0.07, ls_spacing=1.35)

    for x in (3.10, 6.20, 9.20):
        arrow(ax, (x, 7.08), (x, 6.62), color=MID, lw=1.6, ms=13)
        arrow(ax, (x, 5.33), (x, 4.87), color=MID, lw=1.6, ms=13)
        arrow(ax, (x, 3.58), (x, 3.22), color=MID, lw=1.6, ms=13)
    arrow(ax, (3.10, 2.23), (3.10, 1.77), color=MID, lw=1.6, ms=13)

    label(ax, 6.10, 0.38,
          "箭头表示 import 依赖（自上而下）：跨层直连（如 routes 里直接写 SQL）与反向依赖（如 config import db）均不允许",
          fs=9.5, color=GRAY)
    save(f, "g_module_dep.png")


@fig("g_dataflow.png", "图 5-1 数据流转架构")
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
        box(ax, x, 5.95, 1.65, 0.77, "%s\n%s" % (t1, t2), fc=fc, ec=ec, fs=9, lw=1.3, r=0.07)
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
        box(ax, x, 4.22, 1.55, 0.76, "%s\n%s" % (t1, t2), fc=LIGHT, ec=GREEN, fs=9,
            lw=1.3, r=0.07)
        if i < 3:
            arrow(ax, (x + 1.55, 4.60), (x + 1.72, 4.60), color=GREEN, lw=1.5, ms=11)

    rowC = [("_feed_insight", "联动入口"),
            ("告警评估", "evaluate_alerts"),
            ("心跳 / 泵统计", "在线状态 · 累计时长"),
            ("自动调控判定", "可回写下行指令")]
    for i, (t1, t2) in enumerate(rowC):
        x = 1.70 + i * 1.72
        box(ax, x, 2.67, 1.55, 0.76, "%s\n%s" % (t1, t2), fc=ORANGE_L, ec=ORANGE, fs=9,
            lw=1.3, r=0.07)
        if i < 3:
            arrow(ax, (x + 1.55, 3.05), (x + 1.72, 3.05), color=ORANGE, lw=1.5, ms=11)

    box(ax, 8.75, 4.22, 3.95, 0.76,
        "推送不阻塞回调：emit 只做序列化与入队\n不碰磁盘，回调线程 < 5 ms 返回",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)
    box(ax, 8.75, 2.67, 3.95, 0.76,
        "联动副作用不回写采集链路\n避免 采集 → 联动 → 采集 的环路放大",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)

    box(ax, 1.70, 0.95, 11.00, 0.90,
        "并行语义：主链负责持久化，批量写入且可背压丢弃最旧；推送支链负责实时呈现，按房间广播；\n"
        "联动支链负责告警、心跳与自动调控。三条路径都不在 MQTT 回调线程内做磁盘 IO。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.08, ls_spacing=1.6)
    save(f, "g_dataflow.png")


@fig("g_controlflow.png", "图 5-2 调控流程")
def g_controlflow():
    W, H = 12.0, 9.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-2  调控流程", "RORI 分级决定动作强度，P6d 修正阈值，滞回判定避免抖动")

    box(ax, 4.05, 7.55, 3.90, 0.50, "读取四路读数：水位 / 土壤 / DO / Eh",
        fc=LIGHT, ec=GREEN, fs=10.5)
    box(ax, 4.05, 6.70, 3.90, 0.55, "计算 RORI = floor(P_risk × 100)",
        fc=LIGHT, ec=GREEN, fs=10.5)
    diamond(ax, 6.00, 5.90, 3.00, 1.00, "RORI 分级", fc=ORANGE_L, ec=ORANGE, fs=11)

    br = [(0.50, "待机", "RORI < 40", "仅监测，不下发指令", LIGHT, GREEN),
          (4.60, "脉冲灌溉", "40 ≤ RORI < 70", "间歇启泵，短时多次", LIGHT, GREEN),
          (8.70, "满载灌溉", "RORI ≥ 70", "气泵 + 水泵同时运行", ORANGE_L, ORANGE)]
    for x, name, cond, act, fc, ec in br:
        box(ax, x, 4.20, 2.80, 0.80, "%s\n%s\n%s" % (name, cond, act), fc=fc, ec=ec,
            fs=9.5, lw=1.4, r=0.08, ls_spacing=1.35)

    arrow(ax, (6.00, 7.55), (6.00, 7.27), color=GREEN, lw=1.8)
    arrow(ax, (6.00, 6.70), (6.00, 6.42), color=GREEN, lw=1.8)
    # 三分支
    line(ax, [(4.50, 5.90), (1.90, 5.90)], color=GREEN, lw=1.6)
    arrow(ax, (1.90, 5.90), (1.90, 5.02), color=GREEN, lw=1.6)
    arrow(ax, (6.00, 5.40), (6.00, 5.02), color=GREEN, lw=1.6)
    line(ax, [(7.50, 5.90), (10.10, 5.90)], color=GREEN, lw=1.6)
    arrow(ax, (10.10, 5.90), (10.10, 5.02), color=GREEN, lw=1.6)
    # 汇合
    line(ax, [(1.90, 4.20), (1.90, 3.95), (5.90, 3.95)], color=GREEN, lw=1.6)
    line(ax, [(10.10, 4.20), (10.10, 3.95), (6.10, 3.95)], color=GREEN, lw=1.6)
    arrow(ax, (6.00, 4.20), (6.00, 3.82), color=GREEN, lw=1.8)

    box(ax, 3.80, 3.15, 4.40, 0.65, "应用 P6d 动态阈值（humi_down 随降雨前馈下移）",
        fc=LIGHT, ec=GREEN, fs=9.5)
    box(ax, 3.80, 2.30, 4.40, 0.60, "滞回判定：超阈开启，回落 3 个单位才关闭",
        fc=ORANGE_L, ec=ORANGE, fs=9.5)
    box(ax, 3.80, 1.45, 4.40, 0.60, "下发气泵 / 水泵指令（含最小间隔闸门）",
        fc=LIGHT, ec=GREEN, fs=9.5)
    box(ax, 4.80, 0.75, 2.40, 0.42, "结束 / 写运行日志", fc=WHITE, ec=GREEN, fs=9.5, r=0.20)

    arrow(ax, (6.00, 3.15), (6.00, 2.92), color=GREEN, lw=1.8)
    arrow(ax, (6.00, 2.30), (6.00, 2.07), color=ORANGE, lw=1.8)
    arrow(ax, (6.00, 1.45), (6.00, 1.19), color=GREEN, lw=1.8)
    label(ax, 6.32, 4.02, "三路汇合", fs=9, color=GRAY, ha="left")

    box(ax, 0.50, 1.35, 2.95, 1.70,
        "P6d 前馈\n未来 6 日雨量越大，\n湿度下限抬升幅度越大，\n相当于提前蓄墒少灌",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.08, ls_spacing=1.5)
    box(ax, 8.65, 1.35, 2.85, 1.70,
        "滞回区间\n动作开启后不随单点\n抖动立即回落；\n越过阈值 ±3 才回到待机",
        fc=PALE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.08, ls_spacing=1.5)
    save(f, "g_controlflow.png")


@fig("g_rori.png", "图 5-3 RORI 风险指数计算流程")
def g_rori():
    W, H = 12.4, 9.2
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-3  RORI 风险指数计算流程",
          "四路读数归一化 → 加权融合 + 叠加惩罚 → 取整分级")

    rows = [
        ("Eh 氧化还原电位 (mV)", r"$S_{Eh}=\mathrm{clamp}(0,1,(300-Eh)/450)$"),
        ("DO 溶解氧 (mg/L)", r"$S_{DO}=\mathrm{clamp}(0,1,(8.0-DO)/8.0)$"),
        ("Water 积水深 (mm)", r"$R_{water}=\max(0,(Water-5)/100)$"),
        ("Soil_A2 土壤 ADC", r"$R_{soil}=(2000-Soil_{A2})/2000$"),
    ]
    ys = [7.30, 6.55, 5.80, 5.05]
    for (t, _f), y in zip(rows, ys):
        box(ax, 0.45, y, 2.30, 0.55, t, fc=LIGHT, ec=GREEN, fs=9.5, r=0.07)
        arrow(ax, (2.75, y + 0.275), (3.03, y + 0.275), color=GREEN, lw=1.5, ms=11)
    for (t, fx), y in zip(rows, ys):
        box(ax, 3.05, y, 2.75, 0.55, "", fc=ORANGE_L, ec=ORANGE, r=0.07)
        ax.text(4.425, y + 0.275, fx, ha="center", va="center", fontsize=9.5,
                color=INK, zorder=5)
        arrow(ax, (5.80, y + 0.275), (6.18, y + 0.275), color=ORANGE, lw=1.5, ms=11)

    label(ax, 1.60, 7.98, "四路输入", fs=9.5, color=GRAY)
    label(ax, 4.42, 7.98, "归一化到 [0,1]", fs=9.5, color=GRAY)

    # 融合
    box(ax, 6.20, 4.60, 4.35, 3.40, "", fc=PALE, ec=GREEN, lw=1.8, r=0.10)
    label(ax, 8.375, 7.72, "加权融合 P_risk", fs=12, color=DEEP, weight="bold")
    ax.text(8.375, 7.30, r"$P_{risk}=\omega_1 S_{Eh}+\omega_2 S_{DO}$",
            ha="center", va="center", fontsize=11, color=INK, zorder=5)
    ax.text(8.375, 6.92, r"$+\ \omega_3\max(R_{water},R_{soil})+\gamma\,R_{water}R_{soil}$",
            ha="center", va="center", fontsize=11, color=INK, zorder=5)
    box(ax, 6.45, 5.38, 3.85, 0.66, "", fc=WHITE, ec=SOFT, lw=1.0, r=0.06)
    ax.text(8.375, 6.36, r"$\omega_1=\omega_2=0.35\qquad \omega_3=0.30\qquad \gamma=0.5$",
            ha="center", va="center", fontsize=11, color=ORANGE, zorder=5)
    label(ax, 8.375, 5.86, "前两项为主因子，第三项取水量 / 土壤的较大值", fs=9, color=GRAY)
    label(ax, 8.375, 5.57, "第四项为水旱叠加惩罚，两者同时偏高时放大风险", fs=9, color=GRAY)

    box(ax, 6.20, 3.55, 4.35, 0.65, "", fc=LIGHT, ec=GREEN, lw=1.6, r=0.08)
    ax.text(8.375, 3.875, r"$RORI=\lfloor P_{risk}\times 100\rfloor$  → 0–100 整数",
            ha="center", va="center", fontsize=11.5, color=DEEP, zorder=5)
    arrow(ax, (8.375, 4.60), (8.375, 4.22), color=GREEN, lw=1.8)

    tiers = [("0 – 40　待机", "仅监测，不下发指令", 0.55, 3.60, LIGHT, GREEN),
             ("40 – 70　脉冲", "间歇启泵，短时多次", 4.45, 3.60, LIGHT, GREEN),
             ("70 – 100　满载", "气泵 + 水泵同时运行", 8.35, 3.60, ORANGE_L, ORANGE)]
    for name, desc, x, w, fc, ec in tiers:
        box(ax, x, 1.15, w, 0.70, "%s\n%s" % (name, desc), fc=fc, ec=ec, fs=10, r=0.08)
    label(ax, 6.20, 2.42, "三档分级", fs=9.5, color=GRAY)
    line(ax, [(8.375, 3.55), (8.375, 2.20)], color=GREEN, lw=1.6)
    line(ax, [(2.35, 2.20), (10.15, 2.20)], color=GREEN, lw=1.6)
    for x in (2.35, 6.25, 10.15):
        arrow(ax, (x, 2.20), (x, 1.87), color=GREEN, lw=1.6, ms=12)
    ax.add_patch(Circle((8.375, 2.20), 0.045, facecolor=GREEN, edgecolor=GREEN, zorder=6))

    label(ax, 6.20, 0.62,
          "权重来自试验标定：Eh 与 DO 各占 0.35，水量 / 土壤取二者较大值再叠加 0.5 的惩罚项",
          fs=9.5, color=GRAY)
    save(f, "g_rori.png")


@fig("g_p6d.png", "图 5-4 六日降雨前馈动态阈值")
def g_p6d():
    W, H = 12.6, 8.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-4  六日降雨前馈动态阈值",
          "未来 6 日雨量 → 衰减加权 P6d → 分段 α → 湿度上下限动态修正")

    box(ax, 0.45, 0.75, 3.40, 6.20, "", fc=PALE, ec=GREEN, lw=1.5, r=0.10)
    label(ax, 2.15, 6.62, "未来 6 日降雨预测 (mm)", fs=10.5, color=DEEP, weight="bold")

    rain = [0.0, 0.5, 3.0, 12.0, 25.0, 40.0]
    ax2 = f.add_axes([0.75 / W, 1.20 / H, 2.85 / W, 5.05 / H])
    xs = np.arange(1, 7)
    ax2.bar(xs, rain, width=0.62, color=[LIGHT, LIGHT, LIGHT, MID, MID, DEEP],
            edgecolor=GREEN, linewidth=1.0, zorder=3)
    for xi, ri in zip(xs, rain):
        ax2.text(xi, ri + 1.2, ("%g" % ri), ha="center", va="bottom", fontsize=8.5,
                 color=GRAY)
    ax2.set_xlim(0.4, 6.6)
    ax2.set_ylim(0, 48)
    ax2.set_xticks(xs)
    ax2.set_xticklabels(["D1", "D2", "D3", "D4", "D5", "D6"], fontsize=8.5, color=GRAY)
    ax2.set_yticks([0, 20, 40])
    ax2.tick_params(axis="y", labelsize=8.5, colors=GRAY, length=3)
    ax2.tick_params(axis="x", length=3, colors=GRAY)
    for s in ("top", "right"):
        ax2.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax2.spines[s].set_color(SOFT)
    ax2.set_facecolor(WHITE)
    ax2.grid(axis="y", color=SOFT, lw=0.8, ls=":", zorder=0)

    arrow(ax, (3.90, 6.32), (4.40, 6.32), color=GREEN, lw=1.8)

    weights = [r"$\omega_1{=}1.0$", r"$\omega_2{=}0.9$", r"$\omega_3{=}0.7$",
               r"$\omega_4{=}0.5$", r"$\omega_5{=}0.4$", r"$\omega_6{=}0.3$"]
    for i, wtxt in enumerate(weights):
        x = 4.45 + i * 1.22
        box(ax, x, 6.05, 1.12, 0.55, "", fc=LIGHT, ec=GREEN, r=0.07)
        ax.text(x + 0.56, 6.325, wtxt, ha="center", va="center", fontsize=10,
                color=INK, zorder=5)
    label(ax, 8.06, 6.78, "衰减加权：越远的预报权重越低", fs=9.5, color=GRAY)

    box(ax, 4.45, 4.95, 3.30, 0.65, "", fc=ORANGE_L, ec=ORANGE, r=0.07)
    ax.text(6.10, 5.40, "加权累积降雨量 P6d (mm)", ha="center", va="center",
            fontsize=9.5, color=INK, zorder=5)
    ax.text(6.10, 5.13, r"$P6d=\sum_{i=1}^{6}\omega_i\,Rain_i$", ha="center",
            va="center", fontsize=10, color=INK, zorder=5)
    arrow(ax, (6.10, 6.02), (6.10, 5.63), color=GREEN, lw=1.6)

    alphas = [("P6d ≤ 10", "α = 0.95"), ("10 < P6d ≤ 50", "α = 0.75"), ("P6d > 50", "α = 0.45")]
    for i, (cond, a) in enumerate(alphas):
        x = 8.10 + i * 1.25
        box(ax, x, 4.95, 1.15, 0.65, "%s\n%s" % (cond, a), fc=LIGHT, ec=GREEN, fs=9, r=0.07)
    arrow(ax, (7.78, 5.275), (8.06, 5.275), color=ORANGE, lw=1.6)
    label(ax, 10.00, 5.75, "α 随雨量增大而变小，避免极端预报把阈值压得过低", fs=9, color=GRAY)

    box(ax, 4.45, 3.30, 5.15, 1.20, "", fc=PALE, ec=GREEN, lw=1.5, r=0.08)
    label(ax, 7.02, 4.28, "动态阈值修正", fs=10.5, color=DEEP, weight="bold")
    ax.text(7.02, 3.92, r"$H_{down}=\max(45,\ H_{down}^{base}-\alpha\frac{P6d}{200}\times 100)$",
            ha="center", va="center", fontsize=10, color=INK, zorder=5)
    ax.text(7.02, 3.54, r"$H_{up}=\min(95,\ H_{up}^{base}+\alpha\frac{P6d}{200}\times 100)$",
            ha="center", va="center", fontsize=10, color=INK, zorder=5)
    line(ax, [(8.68, 4.92), (8.68, 4.52)], color=GREEN, lw=1.6)
    arrow(ax, (8.68, 4.52), (8.68, 4.42), color=GREEN, lw=1.6)

    box(ax, 9.85, 3.30, 2.00, 1.20, "输出动态阈值\n下限 → 灌溉触发\n上限 → 停灌判据",
        fc=LIGHT, ec=GREEN, fs=9.5, r=0.07, ls_spacing=1.45)
    arrow(ax, (9.62, 3.90), (9.83, 3.90), color=GREEN, lw=1.5, ms=11)

    box(ax, 4.45, 2.15, 7.40, 0.72,
        "前馈含义：雨越多 → α·P6d 越大 → 湿度下限越低，等同提前蓄墒；下限不低于 45%，避免过干死苗。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    box(ax, 4.45, 0.75, 7.40, 0.62,
        "当日无雨（P6d = 0）时动态阈值退化为用户配置的静态上下限，α 分段不参与计算",
        fc=WHITE, ec=SOFT, fs=9.5, tc=GRAY, lw=1.1, r=0.07)
    save(f, "g_p6d.png")


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
    label(ax, 11.55, 3.35, "3 次都失败 → 只记日志\n接口仍返回 200", fs=9, color=GRAY,
          ha="right")

    box(ax, 0.55, 0.80, 11.30, 1.00,
        "设计要点：evaluate_alerts 只做纯判定，AlertDeduper 用 {key: 时间戳} 字典 + 锁保证线程安全；"
        "落库与推送分离，推送在独立重试逻辑里完成，绝不让 webhook 超时拖住请求线程。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "g_alert.png")


@fig("g_er.png", "图 6-1 数据库实体关系")
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


@fig("x_layers.png", "图 2-1 分层调用与命名约定")
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
         "_CONFIG_MIGRATIONS 8 列\n"
         "_HISTORY_MIGRATIONS do_mgl / eh_mv / farm_id\n"
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
        a.set_title(xt, fontsize=10, color=DEEP, pad=8, linespacing=1.5)
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
        return a

    eh = np.linspace(-300, 320, 400)
    s_eh = np.clip((300.0 - eh) / 450.0, 0, 1)
    panel([0.86 / W, 5.38 / H, 5.30 / W, 2.82 / H], "① S_Eh：氧化还原电位（mV）\nS_Eh = clamp(0, 1, (300 − Eh) / 450)",
          "S_Eh", "Eh (mV)", "归一化风险",
          eh, s_eh, [(-150, 1.0, "Eh ≤ -150 饱和为 1", 40, -0.34, "left"),
                     (300, 0.0, "Eh ≥ 300 归零", -10, 0.28, "right")],
          "S_Eh = clamp(0, 1, (300 − Eh) / 450)")

    do = np.linspace(0, 10, 400)
    s_do = np.clip((8.0 - do) / 8.0, 0, 1)
    panel([7.20 / W, 5.38 / H, 5.30 / W, 2.82 / H], "② S_DO：溶解氧（mg/L）\nS_DO = clamp(0, 1, (8.0 − DO) / 8.0)",
          "S_DO", "DO (mg/L)", "归一化风险",
          do, s_do, [(0, 1.0, "DO = 0 饱和为 1", 0.6, -0.36, "left"),
                     (8, 0.0, "DO ≥ 8 归零", -0.4, 0.30, "right")],
          "S_DO = clamp(0, 1, (8.0 − DO) / 8.0)", color=MID)

    wat = np.linspace(0, 100, 400)
    r_w = np.maximum(0.0, (wat - 5.0) / 100.0)
    panel([0.86 / W, 1.58 / H, 5.30 / W, 2.74 / H], "③ Risk_water：积水深度（mm）\nRisk_water = max(0, (Water − 5) / 100)",
          "Risk_water", "Water (mm)", "归一化风险",
          wat, r_w, [(5, 0.0, "5 mm 以下按 0 计", 6, 0.30, "left"),
                     (100, 0.95, "100 mm → 0.95", -6, -0.28, "right")],
          "Risk_water = max(0, (Water − 5) / 100)", color=ORANGE)

    soil = np.linspace(0, 3000, 400)
    r_s = np.clip((2000.0 - soil) / 2000.0, 0, 1)
    panel([7.20 / W, 1.58 / H, 5.30 / W, 2.74 / H], "④ Risk_soil：土壤 ADC 读数\nRisk_soil = (2000 − Soil_A2) / 2000",
          "Risk_soil", "Soil_A2 (ADC)", "归一化风险",
          soil, r_s, [(0, 1.0, "ADC = 0 饱和为 1", 150, -0.36, "left"),
                      (2000, 0.0, "ADC ≥ 2000 归零", 80, 0.32, "left")],
          "Risk_soil = (2000 − Soil_A2) / 2000", color=DEEP)

    box(ax, 0.86, 0.45, 11.64, 0.55,
        "四路曲线共用同一套权重；饱和段的意义是极端读数不再线性放大风险，避免单个探头异常拉满 RORI。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.06)
    save(f, "x_rori_norm.png")


@fig("x_rori_fuse.png", "图 5-2 RORI 融合与分级数值轴")
def x_rori_fuse():
    W, H = 13.0, 9.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-2  RORI 融合与分级数值轴",
          "四路归一化值加权融合后取整，落到 0–100 的三段区间")

    ins = [("S_Eh", r"$\omega_1$ = 0.35", 7.55), ("S_DO", r"$\omega_2$ = 0.35", 6.95),
           ("R_water", r"$\omega_3$ = 0.30", 6.35), ("R_soil", "与 R_water 取大", 5.75)]
    for name, wtxt, y in ins:
        box(ax, 0.60, y, 2.10, 0.48, name, fc=LIGHT, ec=GREEN, fs=10, r=0.06)
        ax.text(3.02, y + 0.30, wtxt, ha="left", va="center", fontsize=9.5,
                color=ORANGE, zorder=6)
        arrow(ax, (2.70, y + 0.10), (4.24, y + 0.10), color=GREEN, lw=1.4, ms=10,
              shrinkA=0.5, shrinkB=0.5)

    line(ax, [(4.26, 7.65), (4.26, 5.85)], color=GREEN, lw=1.6)
    arrow(ax, (4.26, 7.10), (4.70, 7.10), color=GREEN, lw=1.8, ms=11)

    box(ax, 4.72, 6.55, 2.55, 1.10, "加权融合\nP_risk", fc=ORANGE_L, ec=ORANGE, fs=10.5,
        weight="bold", r=0.08)
    box(ax, 4.72, 5.35, 2.55, 0.95, "叠加惩罚\nγ · R_water · R_soil", fc=WHITE, ec=ORANGE,
        fs=9.5, r=0.08, ls="--")
    arrow(ax, (5.99, 5.83), (5.99, 6.53), color=ORANGE, lw=1.5, ms=11)

    arrow(ax, (7.27, 7.10), (7.70, 7.10), color=GREEN, lw=1.8, ms=12)
    box(ax, 7.72, 6.60, 2.60, 1.00, r"RORI = $\lfloor P_{risk} \times 100 \rfloor$",
        fc=LIGHT, ec=GREEN, fs=10.5, weight="bold", r=0.08)
    arrow(ax, (10.32, 7.10), (10.72, 7.10), color=GREEN, lw=1.8, ms=12)
    box(ax, 10.74, 6.60, 1.80, 1.00, "0 – 100\n整数", fc=GRAY_L, ec=GRAY, fs=10, r=0.08)

    box(ax, 4.72, 4.42, 5.55, 0.80,
        "R_water 与 R_soil 先取较大值再乘 ω3；两者同时偏高时另加 γ·R_water·R_soil 惩罚项",
        fc=WHITE, ec=SOFT, fs=9, tc=GRAY, lw=1.1, r=0.07)
    box(ax, 10.40, 5.10, 2.20, 1.15,
        "γ = 0.5\n水旱叠加惩罚\n仅在两者同高时生效", fc=WHITE, ec=SOFT, fs=9, tc=GRAY,
        lw=1.1, r=0.07)

    # 数值轴
    label(ax, 0.60, 4.55, "分级数值轴", fs=11, color=DEEP, weight="bold", ha="left")
    x0, x1, y0 = 1.20, 12.10, 3.20
    segs = [("0 – 40　待机", 0, 40, LIGHT, GREEN), ("40 – 70　脉冲", 40, 70, ORANGE_L, ORANGE),
            ("70 – 100　满载", 70, 100, RED_L, RED)]
    for name, a, b, fc, ec in segs:
        xa = x0 + (x1 - x0) * a / 100.0
        xb = x0 + (x1 - x0) * b / 100.0
        ax.add_patch(Rectangle((xa, y0), xb - xa, 0.62, facecolor=fc, edgecolor=ec,
                               linewidth=1.6, zorder=3))
        label(ax, (xa + xb) / 2, y0 + 0.31, name, fs=10.5, color=INK, weight="bold")
    for v in (0, 20, 40, 60, 70, 86, 100):
        xv = x0 + (x1 - x0) * v / 100.0
        line(ax, [(xv, y0 - 0.12), (xv, y0)], color=GRAY, lw=1.0, z=2)
    for v in (0, 40, 70, 100):
        label(ax, x0 + (x1 - x0) * v / 100.0, y0 - 0.28, "%d" % v, fs=9, color=GRAY)

    for v, txt, up in ((86, "算例①　RORI = 86 → 满载", True),
                       (35, "算例②　RORI = 35 → 待机", False)):
        xv = x0 + (x1 - x0) * v / 100.0
        yy = y0 + 0.62 + 0.38 if up else y0 - 0.62
        arrow(ax, (xv, yy - 0.12 if up else yy + 0.14), (xv, y0 + 0.64 if up else y0 - 0.14),
              color=RED if up else GREEN, lw=1.4, ms=10, ls="--")
        label(ax, xv, yy, txt, fs=9.5, color=RED if up else GREEN, weight="bold")

    box(ax, 0.60, 0.85, 5.90, 1.55,
        "算例①　Eh = 0 mV，DO = 2.0 mg/L\n水位 50 mm，土壤 70%\n"
        "→ 0.35×0.667 + 0.35×0.75 + 0.30×0.70 + 0.5×0.45×0.70 ≈ 0.86",
        fc=WHITE, ec=RED, fs=9, lw=1.2, r=0.07)
    box(ax, 6.70, 0.85, 5.90, 1.55,
        "算例②　Eh = 200 mV，DO = 6.0 mg/L\n水量与土壤读数正常，仅两个主因子贡献\n"
        "→ 落入 0 – 40 待机区间，不下发指令",
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

    br = [("① 华为云 M2M", "services[].properties", 6.95),
          ("② 自定义扁平 JSON", "{water: 12, soil: 800}", 5.75),
          ("③ 纯文本数值", "\"12.5\" / \"12.5,800\"", 4.55)]
    for name, desc, y in br:
        box(ax, 6.65, y, 3.10, 0.85, "%s\n%s" % (name, desc), fc=WHITE, ec=GREEN, fs=9.5,
            lw=1.4, r=0.08)
        arrow(ax, (6.15, 7.075), (6.45, y + 0.42), color=GREEN, lw=1.4, ms=10)

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
    line(ax, [(x0, yA), (x1, yA)], color=GRAY, lw=2.2, z=4)
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
            line(ax, [(xv, yA + 0.10), (xv, yA + 0.30)], color=GRAY, lw=1.0, z=5)
            label(ax, xv, yA + 0.36, "%s\n%s" % (head, desc), fs=9, color=GREEN)
        else:
            line(ax, [(xv, yA - 0.10), (xv, yA - 0.34)], color=GRAY, lw=1.0, z=5)
            label(ax, xv, yA - 0.62, "%s\n%s" % (head, desc), fs=9, color=RED)
    for t in (0, 20, 40, 60):
        label(ax, X(t), yA - 1.02, "t = %d s" % t, fs=8.5, color=GRAY)

    box(ax, 0.60, 0.75, 11.20, 1.30,
        "判定式：now − _last.get(key, 0) ≥ 60 → 允许推送并更新 _last[key]；否则直接返回 False。\n"
        "边界取 ≥：恰好满 60 秒视为可推送。"
        "字典只增不减会缓慢膨胀，因此在巡检线程里顺带清理超过 10 分钟未用的 key。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07, ls_spacing=1.55)
    save(f, "x_alertdedup.png")


@fig("x_realtime.png", "图 9-1 SocketIO 房间模型与事件契约")
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
            ("hw_data", "下行", "type = device_status：在线状态", "room = str(uid)"),
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
        ("DeepSeek", "20 s", "超时 / 非 200 / 非 JSON\n内网域名被 SSRF 拦截",
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

    # TTL 徽章与超时标注
    box(ax, 1.35, 6.32, 2.05, 0.42, "TTL = 600 s", fc=RED_L, ec=RED, fs=9.5, r=0.05)
    arrow(ax, (2.375, 6.32), (2.375, 6.17), color=RED, lw=1.3, ms=10, ls="--")
    label(ax, 6.55, 4.58, "600 s 超时", fs=9, color=RED, weight="bold")

    # 确认校验链
    label(ax, 0.55, 2.55, "confirm 的校验链（任一不通过即返回错误）", fs=10.5, color=DEEP,
          weight="bold", ha="left")
    checks = [("① 归属", "plan.user_id == 当前 uid"), ("② 状态", "status 必须为 pending"),
              ("③ TTL", "now < expire_at，否则置 expired"),
              ("④ 白名单", "ALLOWED_DEVICES / ALLOWED_ACTIONS")]
    for i, (name, desc) in enumerate(checks):
        x = 0.55 + i * 3.05
        box(ax, x, 1.55, 2.80, 0.85, "%s\n%s" % (name, desc), fc=WHITE, ec=GREEN, fs=9,
            lw=1.2, r=0.07)
        if i < 3:
            arrow(ax, (x + 2.80, 1.975), (x + 3.00, 1.975), color=GREEN, lw=1.3, ms=10)

    box(ax, 0.55, 0.45, 11.90, 0.75,
        "终态语义：confirmed / rejected / expired / failed 都不可再跃迁，重复 confirm 只返回当前状态；"
        "过期判定在读取与确认两处各做一次。",
        fc=GRAY_L, ec=GRAY, fs=9.5, tc=INK, lw=1.1, r=0.07)
    save(f, "x_plan_ttl.png")


@fig("x_tick.png", "图 13-1 前端统一 tick 调度与批量 DOM 更新")
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


# @@APPEND@@
