# -*- coding: utf-8 -*-
"""重写 x_rori_fuse（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
NEW = r'''@fig("x_rori_fuse.png", "图 5-2 RORI 融合与分级数值轴")
def x_rori_fuse():
    W, H = 13.0, 9.4
    f, ax = canvas(W, H)
    title(ax, W, H, "图 5-2  RORI 融合与分级数值轴",
          "四路归一化值加权融合后取整，落到 0–100 的三段区间")

    ins = [("S_Eh", "= 0.35", 7.55), ("S_DO", "= 0.35", 6.95),
           ("R_water", "= 0.30", 6.35), ("R_soil", "先取大", 5.75)]
    om = [r"$\omega_1$", r"$\omega_2$", r"$\omega_3$", r"$\mathrm{max}$"]
    for (name, wtxt, y), sym in zip(ins, om):
        box(ax, 0.60, y, 2.10, 0.48, name, fc=LIGHT, ec=GREEN, fs=10, r=0.06)
        ax.text(3.02, y + 0.30, sym, ha="left", va="center", fontsize=9.5,
                color=ORANGE, zorder=6)
        ax.text(3.62, y + 0.30, wtxt, ha="left", va="center", fontsize=9,
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

    box(ax, 4.72, 4.20, 5.55, 0.85,
        "R_water 与 R_soil 先取较大值再乘 ω₃；两者同时偏高时另加 γ·R_water·R_soil 惩罚项",
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


'''
s = io.open(P, encoding="utf-8").read()
a = s.index('@fig("x_rori_fuse.png"')
b = s.index('@fig("x_histwriter.png"')
io.open(P, "w", encoding="utf-8").write(s[:a] + NEW + s[b:])
print("rewrote x_rori_fuse")
