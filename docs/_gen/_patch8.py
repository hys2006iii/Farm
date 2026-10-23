# -*- coding: utf-8 -*-
"""修 x_rori_fuse 的缺字形与 x_mqtt 的分支位置（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()

pairs = [
    ('("S_Eh", "ω₁ = 0.35", 7.55)', '("S_Eh", "$\\\\omega_1$ = 0.35", 7.55)'),
    ('("S_DO", "ω₂ = 0.35", 6.95)', '("S_DO", "$\\\\omega_2$ = 0.35", 6.95)'),
    ('("R_water", "ω₃ · max 取大", 6.35)', '("R_water", "$\\\\omega_3$ · 与 R_soil 取大", 6.35)'),
    ('"RORI = ⌊P_risk × 100⌋"', 'r"RORI = $\\lfloor P_{risk} \\times 100 \\rfloor$"'),
    ('("① 华为云 M2M", "services[].properties", 7.35)',
     '("① 华为云 M2M", "services[].properties", 6.95)'),
    ('("② 自定义扁平 JSON", "{water: 12, soil: 800}", 6.10)',
     '("② 自定义扁平 JSON", "{water: 12, soil: 800}", 5.75)'),
    ('("③ 纯文本数值", "\\"12.5\\" / \\"12.5,800\\"", 4.85)',
     '("③ 纯文本数值", "\\"12.5\\" / \\"12.5,800\\"", 4.55)'),
    ('''    label(ax, 6.55, 7.70, "按报文形状三分支", fs=9, color=GRAY, ha="left")\n''', ''),
]
for a, b in pairs:
    assert a in s, a[:40]
    s = s.replace(a, b)

io.open(P, "w", encoding="utf-8").write(s)
print("patched")
