# -*- coding: utf-8 -*-
"""JWT 伪造复核（用全新用户避开限流）。"""
import datetime
import io
import random
import sys

import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = 'http://127.0.0.1:5099'
u = 'jwt_%d' % random.randint(100000, 999999)
requests.post(f'{BASE}/api/register', json={'username': u, 'password': 'Passw0rd!'})

r = requests.post(f'{BASE}/api/app_login', json={'username': u, 'password': 'Passw0rd!'})
print('app_login 状态码 =', r.status_code, '| body =', r.text[:200])
token = r.json().get('token') if r.status_code == 200 else None
print('token =', (token[:40] + '…') if token else None)

if token:
    # 1) 伪造签名
    parts = token.split('.')
    bad = parts[0] + '.' + parts[1] + '.' + ('A' * len(parts[2]))
    rr = requests.post(f'{BASE}/api/app_send_command',
                       json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer ' + bad})
    print(f'[篡改签名] -> [{rr.status_code}] {rr.text[:150]}')

    # 2) 用硬编码兜底密钥自签（FARM_SECRET_KEY 未设置 → config 用 FALLBACK）
    import jwt as pyjwt
    forged = pyjwt.encode(
        {'user_id': 1, 'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)},
        'smart_irrigation_secret_2026', algorithm='HS256')
    if isinstance(forged, bytes):
        forged = forged.decode()
    rr2 = requests.post(f'{BASE}/api/app_send_command',
                        json={'device': 'water_pump', 'action': 'on'},
                        headers={'Authorization': 'Bearer ' + forged})
    print(f'[兜底密钥自签 user_id=1] -> [{rr2.status_code}] {rr2.text[:150]}')

    # 3) 真 token + 非法 device / action
    for body, desc in [({'device': 'evil', 'action': 'on'}, '非法 device'),
                       ({'device': 'water_pump', 'action': 'explode'}, '非法 action'),
                       ({}, '缺字段')]:
        rr3 = requests.post(f'{BASE}/api/app_send_command', json=body,
                            headers={'Authorization': 'Bearer ' + token})
        print(f'[真 token + {desc}] -> [{rr3.status_code}] {rr3.text[:150]}')

    # 4) 无 token / 空 Bearer / 格式错
    for hdr, desc in [({}, '无 Authorization'),
                      ({'Authorization': 'Bearer '}, '空 Bearer'),
                      ({'Authorization': 'Basic abc'}, 'Basic 方案')]:
        rr4 = requests.post(f'{BASE}/api/app_send_command',
                            json={'device': 'water_pump', 'action': 'on'}, headers=hdr)
        print(f'[{desc}] -> [{rr4.status_code}] {rr4.text[:120]}')
