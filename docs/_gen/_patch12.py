# -*- coding: utf-8 -*-
"""修 x_realtime 表格与 x_ai_fallback 文案（一次性补丁）。"""
import io

P = r"D:\AI\Farm\docs\_gen\make_figs.py"
s = io.open(P, encoding="utf-8").read()
pairs = [
    ('"type = device_status：在线 / 心跳 / 最后上报"', '"type = device_status：在线状态"'),
    ('"超时 / 非 200 / 非 JSON / 内网域名被 SSRF 拦截"',
     '"超时 / 非 200 / 非 JSON\\n内网域名被 SSRF 拦截"'),
]
for a, b in pairs:
    assert a in s, a[:30]
    s = s.replace(a, b)
io.open(P, "w", encoding="utf-8").write(s)
print("ok")
