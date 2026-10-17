"""青禾智灌 —— AI 助手对话代理。

把前端 `/api/ai_chat` 的提问转发给用户配置的 OpenAI 兼容接口（默认 DeepSeek），
无论上游成功、失败还是返回非 JSON，都包装成前端认识的
`{'choices': [{'message': {'content': '...'}}]}` 结构，绝不向请求栈抛异常。
"""

import requests

from qinghe import config, db

SYSTEM_PROMPT = '你是一个智能灌溉与水利控制系统助手，请简洁专业地回答中文问题。'


def _wrap(content: str) -> dict:
    """把纯文本包装成前端需要的 choices 结构。"""
    return {'choices': [{'message': {'content': content}}]}


def load_ai_config(uid: int):
    """读取用户的 AI 配置行（ai_domain / ai_key），不存在返回 None。"""
    return db.load_ai_config(uid)


def normalize_base_url(ai_domain) -> str:
    """规整 AI 接口基址：空值取默认；deepseek 官方误填 http 时自动纠正为 https。"""
    base_url = (ai_domain.strip() if ai_domain else config.DEFAULT_AI_DOMAIN)
    if base_url.startswith('http://api.deepseek.com'):
        base_url = 'https://api.deepseek.com'
    return base_url


def build_chat_request(ai_domain, user_msg: str):
    """构造 (url, headers, body)。"""
    base_url = normalize_base_url(ai_domain)
    url = '%s/chat/completions' % base_url.rstrip('/')
    headers = {'Content-Type': 'application/json'}
    body = {
        'model': config.DEFAULT_AI_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_msg},
        ],
        'stream': False,
    }
    return url, headers, body


def chat(ai_domain, ai_key, user_msg: str) -> dict:
    """调用 AI 接口并返回可直接 jsonify 的 dict。"""
    url, headers, body = build_chat_request(ai_domain, user_msg)
    headers['Authorization'] = 'Bearer %s' % ai_key
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=config.TIMEOUT_AI)
        if resp.status_code != 200:
            snippet = (resp.text or '(空响应)')[:300]
            return _wrap('AI 接口返回异常（HTTP %s）：%s' % (resp.status_code, snippet))
        try:
            return resp.json()
        except Exception:
            return _wrap(
                'AI 接口返回非 JSON 内容（HTTP %s）：%s'
                % (resp.status_code, (resp.text or '')[:300])
            )
    except Exception as e:
        return _wrap('请求失败: %s' % str(e))
