# -*- coding: utf-8 -*-
"""x_rori_fuse 细节调整（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()

pairs = [
    ('''    ins = [("S_Eh", "= 0.35", 7.55), ("S_DO", "= 0.35", 6.95),
           ("R_water", "= 0.30", 6.35), ("R_soil", "先取大", 5.75)]
    om = [r"$\\omega_1$", r"$\\omega_2$", r"$\\omega_3$", r"$\\mathrm{max}$"]
    for (name, wtxt, y), sym in zip(ins, om):
        box(ax, 0.60, y, 2.10, 0.48, name, fc=LIGHT, ec=GREEN, fs=10, r=0.06)
        ax.text(3.02, y + 0.30, sym, ha="left", va="center", fontsize=9.5,
                color=ORANGE, zorder=6)
        ax.text(3.62, y + 0.30, wtxt, ha="left", va="center", fontsize=9,
                color=ORANGE, zorder=6)''',
     '''    ins = [("S_Eh", r"$\\omega_1$ = 0.35", 7.55), ("S_DO", r"$\\omega_2$ = 0.35", 6.95),
           ("R_water", r"$\\omega_3$ = 0.30", 6.35), ("R_soil", "与 R_water 取大", 5.75)]
    for name, wtxt, y in ins:
        box(ax, 0.60, y, 2.10, 0.48, name, fc=LIGHT, ec=GREEN, fs=10, r=0.06)
        ax.text(3.02, y + 0.30, wtxt, ha="left", va="center", fontsize=9.5,
                color=ORANGE, zorder=6)'''),
    ('box(ax, 4.72, 4.20, 5.55, 0.85,', 'box(ax, 4.72, 4.42, 5.55, 0.80,'),
]
for a, b in pairs:
    assert a in s, a[:40]
    s = s.replace(a, b)
io.open(P, "w", encoding="utf-8").write(s)
print("ok")
