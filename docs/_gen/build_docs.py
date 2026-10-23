# -*- coding: utf-8 -*-
"""把 docs/_gen/src/ 下的分片 Markdown 组装成两份说明书并输出 docx。

分片约定（见 docs/_gen/契约_格式与Markdown.md）：
  docs/_gen/src/<书>/00_meta.md      front matter（--- title/subtitle/version/date ---）
  docs/_gen/src/<书>/NN_<标题>.md    一个分片一章（首行是 `## 一、xxx`），按文件名排序拼接
产物：
  docs/_gen/build/<书>.md            合并后的全文（可 diff，便于复核）
  文档/青禾智灌智慧灌溉管理平台_<subtitle>.docx
用法：
  python build_docs.py            # 两份都出
  python build_docs.py 概要        # 只出概要
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
BUILD = os.path.join(HERE, "build")
OUTDIR = os.path.abspath(os.path.join(HERE, "..", "..", "文档"))

BOOKS = {
    "概要": "概要设计说明书",
    "详细": "详细设计说明书",
}

# 章节顺序即文件名字典序；这里只做完整性提醒
EXPECTED = {
    "概要": ["00_meta.md", "10_引言.md", "20_总体设计.md", "30_模块设计.md", "40_接口设计.md",
             "50_主要流程设计.md", "60_数据结构设计.md", "70_非功能设计.md", "80_设计权衡与风险.md",
             "90_界面设计.md", "99_附录.md"],
    "详细": ["00_meta.md", "10_引言.md", "20_设计约定.md", "30_配置与常量设计.md", "40_数据访问层详细设计.md",
             "50_核心算法详细设计.md", "60_认证与安全详细设计.md", "70_设备接入层详细设计.md",
             "80_告警与推送详细设计.md", "90_实时通道详细设计.md", "100_天气与AI详细设计.md",
             "110_HTTP接口详细设计.md", "120_新增功能模块详细设计.md", "130_前端详细设计.md",
             "140_部署与运行详细设计.md", "150_测试设计.md", "160_待复核假设与缺陷.md", "199_附录.md"],
}


def parts_of(book: str) -> list[str]:
    d = os.path.join(SRC, book)
    if not os.path.isdir(d):
        raise SystemExit(f"缺少分片目录：{d}")
    files = [f for f in os.listdir(d) if f.endswith(".md")]

    def _key(name: str):
        """按文件名前缀的整数值排序，避免 '90' 被排到 '100' 之后。"""
        head = name.split("_", 1)[0]
        return (int(head) if head.isdigit() else 10 ** 6, name)

    files.sort(key=_key)
    if not files:
        raise SystemExit(f"分片目录为空：{d}")
    missing = [f for f in EXPECTED[book] if f not in files]
    if missing:
        print(f"[warn] {book} 缺少预期分片：{', '.join(missing)}")
    extra = [f for f in files if f not in EXPECTED[book]]
    if extra:
        print(f"[warn] {book} 多出未预期分片：{', '.join(extra)}")
    return [os.path.join(d, f) for f in files]


def shift_headings(text: str) -> str:
    """把分片里的标题整体上提一级（`##`→`#`，`###`→`##`），代码块内不处理。

    分片用 `## 一、引言` 表示章，是为了单独预览时也有层级；合成书稿时要让章
    成为 Heading 1，Word 的目录才会以章为顶层。
    """
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and line.startswith("#"):
            out.append(line[1:])
        else:
            out.append(line)
    return "\n".join(out)


def merge(book: str) -> str:
    chunks = []
    for path in parts_of(book):
        with open(path, "r", encoding="utf-8-sig") as fh:
            txt = fh.read().lstrip("\ufeff").rstrip("\n")
        if not txt.strip():
            print(f"[warn] 空分片，已跳过：{os.path.basename(path)}")
            continue
        chunks.append(txt)
    meta = chunks[0]
    body = "\n\n".join(shift_headings(c) for c in chunks[1:])
    return meta + "\n\n" + body.strip() + "\n"


def check(book: str, text: str) -> list[str]:
    """交付前自检：章号连续性、图/表编号是否重复。

    章号连续性只在分片齐备时才检查——缺章阶段（分片仍在陆续交付）必然报错，
    那是噪声而不是缺陷。图/表编号重复与缺图占位在任何阶段都检查。
    """
    problems: list[str] = []
    cn = ["一", "二", "三", "四", "五", "六", "七", "八", "九",
          "十", "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八"]
    chapters = re.findall(r"^##\s*([一二三四五六七八九十]+)、", text, re.M)
    complete = not [f for f in EXPECTED[book]
                    if f not in os.listdir(os.path.join(SRC, book))]
    if complete:
        for i, ch in enumerate(chapters):
            expect = cn[i] if i < len(cn) else f"({i + 1})"
            if ch != expect:
                problems.append(f"第 {i + 1} 章号应为「{expect}、」实为「{ch}、」")
    figs = re.findall(r"!\[图\s*(\d+-\d+)", text)
    dups = {f for f in figs if figs.count(f) > 1}
    if dups:
        problems.append(f"图号重复：{'、'.join(sorted(dups))}")
    caps = re.findall(r"^表\s*(\d+-\d+)", text, re.M)
    dupc = {c for c in caps if caps.count(c) > 1}
    if dupc:
        problems.append(f"表号重复：{'、'.join(sorted(dupc))}")
    misses = re.findall(r"［缺图：([^\]]+)\]", text)
    if misses:
        problems.append(f"缺图 {len(misses)} 处：" + "、".join(sorted(set(misses))))
    return problems


def main(argv: list[str]) -> int:
    import docx_kit

    check_only = "--check" in argv
    argv = [a for a in argv if a != "--check"]
    want = argv[1] if len(argv) > 1 else None
    if not check_only:
        os.makedirs(OUTDIR, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    rc = 0
    for book, subtitle in BOOKS.items():
        if want and want not in (book, subtitle):
            continue
        md = merge(book)
        # 分片里图路径写的是 figs/xxx.png，合并文件在 build/ 下，需回指上一级
        md = md.replace("](figs/", "](../figs/")
        merged = os.path.join(BUILD, f"{subtitle}.md")
        with open(merged, "w", encoding="utf-8") as fh:
            fh.write(md)
        for p in check(book, md):
            print(f"[check][{book}] {p}")
            rc = 1
        if check_only:
            print(f"[check][{book}] 完稿 {len(md)} 字符，检查结束（未生成 docx）")
            continue
        out = os.path.join(OUTDIR, f"青禾智灌智慧灌溉管理平台_{subtitle}.docx")
        docx_kit.build(merged, out)
        print(f"[ok] {subtitle} -> {out}  ({os.path.getsize(out)} bytes)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
