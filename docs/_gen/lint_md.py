# -*- coding: utf-8 -*-
"""对 docs/_gen/src/ 下的分片做格式自检。

用法：
    python lint_md.py            # 检查全部分片
    python lint_md.py 详细       # 只查一本
    python lint_md.py 详细 120   # 只查指定前缀的分片
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")

CN = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一",
      "十二", "十三", "十四", "十五", "十六", "十七", "十八"]

FIG_SPEC = {
    "g_arch.png": "2-1", "g_creative.png": "2-2", "g_edgecloud.png": "2-3",
    "g_module_dep.png": "3-1",
    "g_dataflow.png": "5-1", "g_controlflow.png": "5-2", "g_rori.png": "5-3",
    "g_p6d.png": "5-4", "g_autocontrol.png": "5-5", "g_hitl.png": "5-6",
    "g_alert.png": "5-7", "g_er.png": "6-1",
    "g_ui_login.png": "12-1", "g_ui_dashboard.png": "12-2",
    "g_ui_insight.png": "12-3", "g_ui_settings.png": "12-4",
    "g_ui_knowledge.png": "12-5", "g_ui_narrow.png": "12-6",
    "x_layers.png": "2-1", "x_thread.png": "2-2", "x_migration.png": "4-1",
    "x_rori_norm.png": "5-1", "x_rori_fuse.png": "5-2",
    "x_histwriter.png": "7-1", "x_mqtt.png": "7-2",
    "x_alertdedup.png": "8-1", "x_realtime.png": "9-1",
    "x_ai_fallback.png": "10-1", "x_http_pipeline.png": "11-1",
    "x_plan_ttl.png": "12-1", "x_tick.png": "13-1", "x_ui_panel.png": "13-2",
    "x_test_layers.png": "15-1",
}

CHAPTER_FIGS = {
    ("概要", "一"): set(), ("概要", "二"): {"2-1", "2-2", "2-3"},
    ("概要", "三"): {"3-1"}, ("概要", "四"): set(),
    ("概要", "五"): {"5-1", "5-2", "5-3", "5-4", "5-5", "5-6", "5-7"},
    ("概要", "六"): {"6-1"}, ("概要", "七"): set(), ("概要", "八"): set(),
    ("概要", "九"): {"12-1", "12-2", "12-3", "12-4", "12-5", "12-6"},
    ("概要", "十"): set(),
    ("详细", "一"): set(), ("详细", "二"): {"2-1", "2-2"}, ("详细", "三"): set(),
    ("详细", "四"): {"4-1"}, ("详细", "五"): {"5-1", "5-2"},
    ("详细", "六"): set(), ("详细", "七"): {"7-1", "7-2"},
    ("详细", "八"): {"8-1"}, ("详细", "九"): {"9-1"}, ("详细", "十"): {"10-1"},
    ("详细", "十一"): {"11-1"}, ("详细", "十二"): {"12-1"},
    ("详细", "十三"): {"13-1", "13-2"}, ("详细", "十四"): set(),
    ("详细", "十五"): {"15-1"}, ("详细", "十六"): set(), ("详细", "十七"): set(),
}

BANNED = ("TODO", "待补充", "待定")
CODE_MAX_LINES = 45
CAPTION_RE = re.compile(r"^表\s*(\d+)-(\d+)\s")
FIG_RE = re.compile(r"^!\[图\s*([0-9]+-[0-9]+)[^\]]*\]\(figs/([^\)]+)\)")


def cjk_count(text):
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def check_file(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        text = fh.read().lstrip("\ufeff")
    lines = text.split("\n")
    problems = []

    first = next((ln for ln in lines if ln.strip()), "")
    if not re.match(r"^##\s*[一二三四五六七八九十]+、\S", first):
        problems.append("首行不是「## 中文数字、标题」：%s" % first[:40])

    in_fence = False
    fence_start = 0
    fence_len = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_fence:
                in_fence, fence_start, fence_len = True, idx, 0
            else:
                in_fence = False
                if fence_len > CODE_MAX_LINES:
                    problems.append("第 %d 行起的代码块共 %d 行，超过 %d 行上限"
                                    % (fence_start + 1, fence_len, CODE_MAX_LINES))
            continue
        if in_fence:
            fence_len += 1
            continue

        for word in BANNED:
            if word in line and "观察待定" not in line:
                problems.append("第 %d 行含禁用词「%s」" % (idx + 1, word))

        if CAPTION_RE.match(stripped):
            nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            if not nxt.startswith("|"):
                problems.append("第 %d 行的表题与表格之间有空行或缺表格" % (idx + 1))

        fm = FIG_RE.match(stripped)
        if fm:
            num, name = fm.group(1), fm.group(2)
            if name not in FIG_SPEC:
                problems.append("第 %d 行图文件名未登记：%s" % (idx + 1, name))
            elif FIG_SPEC[name] != num:
                problems.append("第 %d 行图号不符：图 %s 应为 图 %s"
                                % (idx + 1, num, FIG_SPEC[name]))
            prev = lines[idx - 1].strip() if idx > 0 else ""
            nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            if prev or nxt:
                problems.append("第 %d 行图标签前后需各留一个空行" % (idx + 1))

    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            block = []
            start = i
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            counts = {row.count("|") for row in block}
            if len(counts) > 1:
                problems.append("第 %d 行起的表格列数不一致：%s" % (start + 1, sorted(counts)))
            continue
        i += 1
    return problems


def chapter_figs(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    m = re.search(r"^##\s*([一二三四五六七八九十]+)、", text, re.M)
    figs = set(re.findall(r"!\[图\s*([0-9]+-[0-9]+)", text))
    return (m.group(1) if m else ""), figs


def main(argv):
    book_filter = argv[1] if len(argv) > 1 else ""
    pref_filter = argv[2] if len(argv) > 2 else ""
    total_bad = 0
    total_cjk = 0
    for book in ("概要", "详细"):
        if book_filter and book != book_filter:
            continue
        bdir = os.path.join(SRC, book)
        if not os.path.isdir(bdir):
            continue
        print("===== %s =====" % book)
        for name in sorted(os.listdir(bdir)):
            if not name.endswith(".md") or name.startswith("00_"):
                continue
            if pref_filter and not name.startswith(pref_filter):
                continue
            path = os.path.join(bdir, name)
            problems = check_file(path)
            with io.open(path, encoding="utf-8-sig") as fh:
                n = cjk_count(fh.read())
            total_cjk += n
            print("[%s] %-34s CJK %6d" % ("OK " if not problems else "ERR", name, n))
            for p in problems:
                print("        - %s" % p)
            if problems:
                total_bad += 1
            chap, figs = chapter_figs(path)
            if chap in CN:
                expect = CHAPTER_FIGS.get((book, chap))
                if expect is None:
                    print("        - 章「%s」未登记应有图编号" % chap)
                elif expect != figs:
                    print("        - 章「%s」图编号不符：应有 %s，实有 %s"
                          % (chap, sorted(expect) or "无", sorted(figs) or "无"))
    print("\n合计 CJK 字数：%d" % total_cjk)
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
