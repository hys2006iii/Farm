# -*- coding: utf-8 -*-
"""定向复现：非字符串 JSON 字段导致的 500（当前 HEAD 复核）。"""
import io
import json
import sys

import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = 'http://127.0.0.1:5099'
CASES = [
    ('/api/register', 'POST', {'username': 12345, 'password': 'Passw0rd!'}, 'username 传 int'),
    ('/api/register', 'POST', {'username': ['a'], 'password': 'Passw0rd!'}, 'username 传 list'),
    ('/api/register', 'POST', {'username': {'a': 1}, 'password': 'Passw0rd!'}, 'username 传 dict'),
    ('/api/register', 'POST', {'username': True, 'password': 'Passw0rd!'}, 'username 传 bool'),
    ('/api/login', 'POST', {'username': 12345, 'password': 'x'}, 'login username 传 int'),
    ('/api/login', 'POST', {'username': ['a'], 'password': 'x'}, 'login username 传 list'),
]
# 需要登录的用例
AUTH_CASES = [
    ('/api/notify_alert', 'POST', {'msg': 12345}, 'msg 传 int'),
    ('/api/notify_alert', 'POST', {'msg': ['a']}, 'msg 传 list'),
    ('/api/notify_alert', 'POST', {'msg': 'ok', 'level': 123}, 'level 传 int'),
    ('/api/notify_alert', 'POST', {'msg': 'ok', 'level': ['a']}, 'level 传 list'),
    ('/api/ai_chat', 'POST', {'msg': 12345}, 'ai_chat msg 传 int'),
    ('/api/ai_chat', 'POST', {'msg': ['a']}, 'ai_chat msg 传 list'),
    ('/api/change_password', 'POST', {'old_password': 123, 'new_password': 'abcdef'},
     'old_password 传 int'),
]

results = []
s = requests.Session()
import random
u = 'tc_%d' % random.randint(100000, 999999)
s.post(f'{BASE}/api/register', json={'username': u, 'password': 'Passw0rd!'})
s.post(f'{BASE}/api/login', json={'username': u, 'password': 'Passw0rd!'})

print('=' * 72)
print('A. 未登录接口（含 register/login）')
print('=' * 72)
for path, meth, payload, desc in CASES:
    try:
        r = requests.post(f'{BASE}{path}', json=payload, timeout=15)
        snippet = r.text[:150].replace('\n', ' ')
        mark = '  <<< 500 !!!' if r.status_code >= 500 else ''
        print(f'[{r.status_code}] {path:24s} {desc:22s} -> {snippet}{mark}')
        results.append((path, desc, r.status_code, snippet))
    except Exception as e:
        print(f'[ERR] {path} {desc} -> {type(e).__name__}: {e}')
        results.append((path, desc, 'ERR', str(e)))

print()
print('=' * 72)
print('B. 需登录接口（session 已建立）')
print('=' * 72)
for path, meth, payload, desc in AUTH_CASES:
    try:
        r = s.post(f'{BASE}{path}', json=payload, timeout=20)
        snippet = r.text[:150].replace('\n', ' ')
        mark = '  <<< 500 !!!' if r.status_code >= 500 else ''
        print(f'[{r.status_code}] {path:24s} {desc:24s} -> {snippet}{mark}')
        results.append((path, desc, r.status_code, snippet))
    except Exception as e:
        print(f'[ERR] {path} {desc} -> {type(e).__name__}: {e}')
        results.append((path, desc, 'ERR', str(e)))

n500 = sum(1 for r in results if isinstance(r[2], int) and r[2] >= 500)
print()
print(f'>>> 触发 5xx 的用例数：{n500} / {len(results)}')
with open('tools/_tc.json', 'w', encoding='utf-8') as f:
    json.dump([{'path': a, 'desc': b, 'status': c, 'body': d} for a, b, c, d in results],
              f, ensure_ascii=False, indent=1)
