# -*- coding: utf-8 -*-
"""调整 x_rori_norm 四个子图的位置与高度（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()
s = s.replace("panel([0.86 / W, 5.28 / H, 5.30 / W, 2.92 / H]",
              "panel([0.86 / W, 5.38 / H, 5.30 / W, 2.82 / H]")
s = s.replace("panel([7.20 / W, 5.28 / H, 5.30 / W, 2.92 / H]",
              "panel([7.20 / W, 5.38 / H, 5.30 / W, 2.82 / H]")
s = s.replace("panel([0.86 / W, 1.62 / H, 5.30 / W, 2.92 / H]",
              "panel([0.86 / W, 1.58 / H, 5.30 / W, 2.74 / H]")
s = s.replace("panel([7.20 / W, 1.62 / H, 5.30 / W, 2.92 / H]",
              "panel([7.20 / W, 1.58 / H, 5.30 / W, 2.74 / H]")
io.open(P, "w", encoding="utf-8").write(s)
print("ok")
