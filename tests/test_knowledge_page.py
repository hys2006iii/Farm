"""知识库页面（/knowledge）的契约测试。

页面本身不参与控制逻辑，但它把大量「数值口径」写进了正文，最容易与
代码悄悄脱节。这里用纯静态断言 + 一次 Flask 请求把约定固化下来：

1. 访问控制：未登录必须 302 回首页，登录后 200；
2. 内容完整性：五章标题齐全且按序出现，关键数值与 qinghe/config.py 一致；
3. 资源与安全：模板引用的静态文件真实落盘，不引 CDN，脚本不做 HTML 拼接；
4. 锚点一致性：目录条目、aria-labelledby、页内 href 都指向真实存在的 id；
5. 诚实性：未实现的能力（边缘固件自治、微信小程序）必须明确写「尚未实现」。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "knowledge.html"
CSS = ROOT / "static" / "css" / "knowledge.css"
JS = ROOT / "static" / "js" / "knowledge.js"

# 五章标题，顺序即页面顺序
CHAPTER_TITLES = [
    "稻田灌溉的基础",
    "根区氧环境：DO 与 Eh",
    "智能灌溉怎么看天看地",
    "青禾智灌的系统内核",
    "操作问答",
]

# 与 qinghe/config.py 对齐的关键数值（缺失即说明文案与代码脱节）
KEY_NUMBERS = ["0.35", "450", "1.5mg/L", "45%"]

ASSET_PATTERN = (
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)"
)


def _read(path: Path) -> str:
    """读取 UTF-8 文本文件。"""
    return path.read_text(encoding="utf-8")


def _static_assets(html: str) -> set[str]:
    """解析模板里 url_for('static', filename='...') 引用的资源相对路径。"""
    return set(re.findall(ASSET_PATTERN, html))


def test_knowledge_page_requires_login(client):
    """未登录访问知识库必须 302 回首页，而不是直接渲染内容。"""
    resp = client.get("/knowledge")
    assert resp.status_code == 302, "未登录访问 /knowledge 应 302 重定向"
    location = resp.headers.get("Location", "")
    assert location.endswith("/"), "应重定向到首页，实际 Location=%r" % location
    assert "/knowledge" not in location, "重定向目标不应仍是知识库自身"


def test_knowledge_page_renders_after_login(client, registered):
    """登录后页面可渲染，五章标题按顺序出现。"""
    resp = client.get("/knowledge")
    assert resp.status_code == 200, "登录后 GET /knowledge 应返回 200"
    html = resp.get_data(as_text=True)

    # 只看正文里的 h2 章节标题（顶栏与目录里也有同名文字，不能直接 index）
    chapters = re.findall(r'<h2[^>]*\bid="(ch-\d)"[^>]*>([^<]*)</h2>', html)
    assert [text.strip() for _, text in chapters] == CHAPTER_TITLES, (
        "正文五章标题与设计不一致：%r" % (chapters,)
    )
    assert [chapter_id for chapter_id, _ in chapters] == [
        "ch-1", "ch-2", "ch-3", "ch-4", "ch-5"
    ], "章节锚点应为 ch-1…ch-5"


def test_knowledge_static_assets_exist():
    """模板引用的 css/js 必须真实存在，且复用 base.css 的设计令牌。"""
    html = _read(TEMPLATE)
    assets = _static_assets(html)
    assert "css/knowledge.css" in assets, "模板未引用 knowledge.css"
    assert "js/knowledge.js" in assets, "模板未引用 knowledge.js"
    assert "css/base.css" in assets, "应复用 base.css 的设计令牌"
    missing = sorted(a for a in assets if not (ROOT / "static" / a).is_file())
    assert not missing, "模板引用了不存在的静态资源：%s" % missing


def test_knowledge_css_reuses_design_tokens():
    """样式只消费 base.css 的变量，不允许在本页重复定义 :root 令牌。"""
    css = _read(CSS)
    assert not re.search(r"^\s*:root\s*\{", css, re.MULTILINE), (
        "knowledge.css 不应重定义设计令牌"
    )
    assert "var(--" in css, "样式应使用 base.css 的 CSS 变量"


def test_knowledge_js_avoids_html_splicing():
    """AGENTS.md：前端禁止用 HTML 字符串拼接写入页面。"""
    js = _read(JS)
    banned = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
    for word in banned:
        assert word not in js, "knowledge.js 不应出现 %s" % word
    # 统一用 querySelector，避免与 index.html 的 id 契约测试冲突
    assert "getElementById" not in js, "knowledge.js 应统一用 querySelector 取节点"


def test_knowledge_page_contains_key_numbers():
    """页面里的关键数值必须与当前代码口径一致。"""
    html = _read(TEMPLATE)
    missing = [value for value in KEY_NUMBERS if value not in html]
    assert not missing, "页面缺少与代码一致的关键数值：%s" % missing


def test_knowledge_page_has_no_cdn_and_defers_scripts():
    """不引任何 CDN；本地脚本必须 defer，避免阻塞首屏。"""
    html = _read(TEMPLATE)
    assert "cdn" not in html.lower(), "页面不应引用任何 CDN"
    script_tags = re.findall(r"<script\b[^>]*>", html)
    assert script_tags, "页面缺少脚本引用"
    for tag in script_tags:
        if "src=" in tag:
            assert 'src="http' not in tag, "脚本不应来自外部地址：%s" % tag
            assert "defer" in tag, "本地脚本应 defer 加载：%s" % tag
    for tag in re.findall(r"<link\b[^>]*>", html):
        if "stylesheet" in tag:
            assert 'href="http' not in tag, "样式不应来自外部地址：%s" % tag


def test_knowledge_anchors_all_resolve():
    """目录条目、aria-labelledby 与页内链接都必须指向真实存在的 id。"""
    html = _read(TEMPLATE)
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    toc_targets = set(re.findall(r'data-toc-link="([^"]+)"', html))
    headings = set(re.findall(r'data-toc-target="([^"]+)"', html))

    assert toc_targets, "目录缺少 data-toc-link 锚点"
    assert toc_targets <= ids, "目录条目指向了不存在的 id：%s" % (toc_targets - ids)
    assert headings <= ids, "正文标题缺少对应 id：%s" % (headings - ids)

    labelled = set(re.findall(r'aria-labelledby="([^"]+)"', html))
    assert labelled <= ids, "aria-labelledby 指向了不存在的 id：%s" % (labelled - ids)

    for anchor in re.findall(r'href="#([^"]+)"', html):
        assert anchor in ids, "页内链接指向了不存在的 id：%s" % anchor


def test_knowledge_marks_unimplemented_features():
    """设计里有、代码里没有的能力必须如实标注「尚未实现」。"""
    html = _read(TEMPLATE)
    assert html.count("尚未实现") >= 2, "未实现能力应在正文中多处明确标注"
    assert "小程序" in html, "微信小程序端应说明尚未实现"
