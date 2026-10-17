"""前端结构契约测试。

界面拆分之后，模板、样式、脚本三者之间靠"约定"连接：JS 用 id 取节点、
HTML 用 ``url_for`` 引资源。这类连接一旦写错，浏览器里只是静默失效
（取不到节点就 return），pytest 与 node 测试都发现不了。

本文件把这几条约定固化成断言：

1. 静态脚本里 ``QH.$('x')`` / ``getElementById('x')`` 引用到的 id，
   必须在模板里真实存在（否则对应功能永远不刷新）；
2. 模板里用 ``url_for('static', filename=...)`` 引用的资源文件必须存在；
3. 页面内的 id 不重复（重复会让取节点拿到错的那个）；
4. 前端不出现 ``innerHTML`` 赋值（AGENTS.md 要求走 textContent/esc）。

这些断言只依赖文件内容，不启动服务、不跑浏览器，属于纯静态契约。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"

INDEX_HTML = TEMPLATES / "index.html"
LOGIN_HTML = TEMPLATES / "login.html"

# 由 JS 动态创建、模板里本就不该出现的节点 id（当前为空，留作白名单挂载点）
DYNAMIC_IDS: set[str] = set()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _html_ids(html: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', html))


def _js_referenced_ids(js: str) -> set[str]:
    """抓取脚本里通过 QH.$ 或 getElementById 取用的 id。"""
    patterns = [
        r"QH\.\$\(\s*['\"]([A-Za-z0-9_\-]+)['\"]\s*\)",
        r"(?<![\w.])getElementById\(\s*['\"]([A-Za-z0-9_\-]+)['\"]\s*\)",
    ]
    found: set[str] = set()
    for pat in patterns:
        found.update(re.findall(pat, js))
    return found


def _static_assets(html: str) -> set[str]:
    """解析 url_for('static', filename='...') 里引用的静态文件路径。"""
    pat = r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)"
    return set(re.findall(pat, html))


@pytest.fixture(scope="module")
def index_html() -> str:
    assert INDEX_HTML.is_file(), "缺少 templates/index.html"
    return _read(INDEX_HTML)


@pytest.fixture(scope="module")
def js_files() -> list[Path]:
    files = sorted((STATIC / "js").glob("*.js"))
    assert files, "static/js 下没有任何脚本"
    return files


def test_index_ids_exist_for_all_dom_lookups(index_html, js_files):
    """脚本取用的每个 id 都必须能在 index.html 里找到。"""
    ids = _html_ids(index_html)
    missing = {}
    for path in js_files:
        needed = _js_referenced_ids(_read(path)) - DYNAMIC_IDS
        gone = sorted(needed - ids)
        if gone:
            missing[path.name] = gone

    assert not missing, "以下 id 被脚本引用但模板里不存在：%s" % missing


def test_index_static_assets_exist(index_html):
    """模板引用的 css/js 文件必须真实落盘。"""
    assets = _static_assets(index_html)
    assert assets, "index.html 未引用任何静态资源"
    missing = sorted(a for a in assets if not (STATIC / a).is_file())
    assert not missing, "模板引用了不存在的静态资源：%s" % missing


def test_login_page_references_its_assets():
    """登录页同样要有自己的样式与脚本，且文件存在。"""
    html = _read(LOGIN_HTML)
    assets = _static_assets(html)
    missing = sorted(a for a in assets if not (STATIC / a).is_file())
    assert not missing, "login.html 引用了不存在的静态资源：%s" % missing
    assert any(a.startswith("css/") for a in assets), "登录页缺少样式引用"
    assert any(a.startswith("js/") for a in assets), "登录页缺少脚本引用"


def test_index_ids_are_unique(index_html):
    """重复 id 会让 getElementById 取到意料之外的节点。"""
    all_ids = re.findall(r'\bid="([^"]+)"', index_html)
    dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
    assert not dupes, "index.html 存在重复 id：%s" % dupes


def test_no_innerhtml_assignment_in_frontend():
    """AGENTS.md：前端不得用 innerHTML 拼接未转义数据。"""
    offenders = []
    for path in sorted((STATIC / "js").rglob("*.js")):
        for lineno, line in enumerate(_read(path).splitlines(), start=1):
            if re.search(r"\.innerHTML\s*=", line) and not line.strip().startswith("//"):
                offenders.append("%s:%d" % (path.name, lineno))
    assert not offenders, "以下位置出现 innerHTML 赋值：%s" % offenders


def test_service_worker_free_and_cdn_scripts_deferred(index_html):
    """CDN 脚本必须 defer，避免阻塞首屏；同时不允许出现同步阻塞脚本标签。"""
    for tag in re.findall(r"<script\b[^>]*>", index_html):
        if "src=" in tag and "http" in tag:
            assert "defer" in tag, "CDN 脚本未加 defer：%s" % tag
