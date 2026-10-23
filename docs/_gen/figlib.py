# -*- coding: utf-8 -*-
"""图元工具：统一配色的方框、箭头、分区与落盘。

坐标统一用 0..100 的抽象画布（x 向右、y 向下），便于按版面直觉摆放。
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIGDIR = os.path.join(HERE, "figs")

# 配色：纸感底 + 墨绿主色 + 琥珀强调
INK = "#1F2A24"
GREEN = "#2E5B3E"
GREEN_BG = "#E8F0E9"
GREEN_ED = "#7FA98C"
AMBER_BG = "#FBF0DD"
AMBER_ED = "#C8923C"
GRAY_BG = "#F4F5F3"
GRAY_ED = "#B9BFB8"
BLUE_BG = "#E7EEF5"
BLUE_ED = "#6E8FAD"

FONT = "Microsoft YaHei"


def _font_ok() -> bool:
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    return FONT in names


def canvas(title: str, subtitle: str = "", w: float = 13.2, h: float = 8.8):
    """新建画布，画好标题与副标题，返回 (fig, ax)。"""
    plt.rcParams["font.sans-serif"] = ([FONT] if _font_ok() else []) + [
        "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(100, 0)          # y 轴翻转：向下为正，摆版面更直观
    ax.axis("off")
    ax.text(6, 7.6, title, fontsize=20, color=GREEN, weight="bold",
            ha="left", va="center")
    if subtitle:
        ax.text(6, 12.2, subtitle, fontsize=11, color="#5A6B60",
                ha="left", va="center")
    ax.plot([6, 94], [15.4, 15.4], color=GREEN_ED, lw=1.0, alpha=0.8)
    return fig, ax


_KIND = {
    "ok": (GREEN_BG, GREEN_ED, GREEN),
    "warn": (AMBER_BG, AMBER_ED, "#8A5A12"),
    "info": (BLUE_BG, BLUE_ED, "#2C4A66"),
    "gray": (GRAY_BG, GRAY_ED, "#3C4741"),
}


def box(ax, x, y, w, h, text, kind="ok", size=11, bold=False, radius=1.4):
    """画一个圆角方框，文本居中。x/y 为左上角。"""
    bg, ed, fg = _KIND.get(kind, _KIND["ok"])
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle="round,pad=0,rounding_size=%s" % radius,
                       linewidth=1.4, facecolor=bg, edgecolor=ed, zorder=2)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, fontsize=size, color=fg,
            ha="center", va="center", zorder=3,
            weight="bold" if bold else "normal", linespacing=1.5)
    return (x, y, w, h)


def arrow(ax, x1, y1, x2, y2, kind="ok", label="", rad=0.0, size=9.5, lw=1.5):
    """从 (x1,y1) 画箭头到 (x2,y2)，可在中点标注文字。"""
    _, ed, fg = _KIND.get(kind, _KIND["ok"])
    color = GREEN if kind == "ok" else (AMBER_ED if kind == "warn" else "#6D7A72")
    a = FancyArrowPatch((x1, y1), (x2, y2),
                        arrowstyle="-|>", mutation_scale=14,
                        linewidth=lw, color=color,
                        connectionstyle="arc3,rad=%s" % rad,
                        shrinkA=1, shrinkB=1, zorder=2)
    ax.add_patch(a)
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 1.0, label, fontsize=size,
                color=fg, ha="center", va="bottom", zorder=4)


def panel(ax, x, y, w, h, text, kind="gray", size=10.5):
    """浅底说明块（不带箭头语义）。"""
    bg, ed, fg = _KIND.get(kind, _KIND["gray"])
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.2",
                       linewidth=1.0, facecolor=bg, edgecolor=ed,
                       alpha=0.95, zorder=1)
    ax.add_patch(p)
    ax.text(x + 1.6, y + h / 2, text, fontsize=size, color=fg,
            ha="left", va="center", linespacing=1.7, zorder=3)


def lane(ax, y, h, text, x=6, w=88):
    """泳道标题条。"""
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0,rounding_size=1.0",
                                linewidth=0, facecolor="#F1F4F0", zorder=0))
    ax.text(x + 1.4, y + h / 2, text, fontsize=11, color=GREEN,
            weight="bold", ha="left", va="center", zorder=1)


def footnote(ax, text, y=92.5):
    panel(ax, 6, y - 3.6, 88, 8.0, text, kind="gray", size=10.5)


def save(fig, name: str) -> str:
    os.makedirs(FIGDIR, exist_ok=True)
    path = os.path.join(FIGDIR, name)
    fig.savefig(path, dpi=200, bbox_inches="tight",
                facecolor="white", pad_inches=0.25)
    plt.close(fig)
    print("[fig] %-22s %6.1f KB" % (name, os.path.getsize(path) / 1024))
    return path
