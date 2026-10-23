# -*- coding: utf-8 -*-
"""把 x_rori_norm 的公式移入子图标题（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()

old = '''        a.text(0.03, 0.94, note, transform=a.transAxes, fontsize=8.5, color=GRAY,
               va="top", ha="left")
'''
assert old in s, "note block not found"
s = s.replace(old, "")

s = s.replace('        a.set_title(xt, fontsize=10.5, color=DEEP, pad=7)',
              '        a.set_title(xt, fontsize=10, color=DEEP, pad=8, linespacing=1.5)')

pairs = [
    ('"① S_Eh：氧化还原电位（mV）"',
     '"① S_Eh：氧化还原电位（mV）\\nS_Eh = clamp(0, 1, (300 − Eh) / 450)"'),
    ('"② S_DO：溶解氧（mg/L）"',
     '"② S_DO：溶解氧（mg/L）\\nS_DO = clamp(0, 1, (8.0 − DO) / 8.0)"'),
    ('"③ Risk_water：积水深度（mm）"',
     '"③ Risk_water：积水深度（mm）\\nRisk_water = max(0, (Water − 5) / 100)"'),
    ('"④ Risk_soil：土壤 ADC 读数"',
     '"④ Risk_soil：土壤 ADC 读数\\nRisk_soil = (2000 − Soil_A2) / 2000"'),
]
for a, b in pairs:
    assert a in s, a
    s = s.replace(a, b)

# 标注点偏移，避免压在曲线上
s = s.replace('(-150, 1.0, "Eh ≤ -150 饱和为 1", 30, -0.22, "left")',
              '(-150, 1.0, "Eh ≤ -150 饱和为 1", 40, -0.34, "left")')
s = s.replace('(0, 1.0, "DO = 0 饱和为 1", 0.5, -0.25, "left")',
              '(0, 1.0, "DO = 0 饱和为 1", 0.6, -0.36, "left")')
s = s.replace('(0, 1.0, "ADC = 0 饱和为 1", 120, -0.25, "left")',
              '(0, 1.0, "ADC = 0 饱和为 1", 150, -0.36, "left")')

io.open(P, "w", encoding="utf-8").write(s)
print("patched x_rori_norm")
