# -*- coding: utf-8 -*-
"""修 x_plan_ttl 的 TTL 视觉与校验链宽度（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()

old = '''    # TTL 计时弧
    ax.add_patch(Arc((3.375, 5.675), 3.60, 2.20, theta1=250, theta2=350, color=RED,
                     lw=1.6, ls="--", zorder=5))
    label(ax, 4.85, 4.05, "600 s 倒计时", fs=9.5, color=RED, weight="bold")
    arrow(ax, (4.30, 4.20), (6.95, 4.70), color=RED, lw=1.4, ms=11, ls="--")
'''
new = '''    # TTL 徽章与超时标注
    box(ax, 1.35, 6.32, 2.05, 0.42, "TTL = 600 s", fc=RED_L, ec=RED, fs=9.5, r=0.05)
    arrow(ax, (2.375, 6.32), (2.375, 6.17), color=RED, lw=1.3, ms=10, ls="--")
    label(ax, 6.55, 4.58, "600 s 超时", fs=9, color=RED, weight="bold")
'''
assert old in s
s = s.replace(old, new)

s = s.replace('''        x = 0.55 + i * 3.10
        box(ax, x, 1.55, 2.85, 0.85''', '''        x = 0.55 + i * 3.05
        box(ax, x, 1.55, 2.80, 0.85''')
s = s.replace('''            arrow(ax, (x + 2.85, 1.975), (x + 3.05, 1.975), color=GREEN, lw=1.3, ms=10)''',
              '''            arrow(ax, (x + 2.80, 1.975), (x + 3.00, 1.975), color=GREEN, lw=1.3, ms=10)''')
io.open(P, "w", encoding="utf-8").write(s)
print("ok")
