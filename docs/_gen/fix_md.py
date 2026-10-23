# -*- coding: utf-8 -*-
"""按 docs/_gen/契约_格式与Markdown.md 自动修正分片里的机械性格式问题。

目前只做两件事（都是无歧义、可幂等重跑的变换）：
  1. 删除「表 N-M 标题」与紧随其后的表格之间的空行（契约要求紧贴）；
  2. 去掉文件开头多余的 BOM 与文件末尾多余空行。

不会改动任何文字内容，也不会动代码块内部。

用法：
    python fix_md.py            # 修正全部分片
    python fix_md.py --dry      # 只报告将要修改的文件，不落盘
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")

CAP = re.compile(r"^表\s*\d+-\d+\s+\S")
TABLE = re.compile(r"^\|.*\|\s*$")


def fix_text(text: str) -> tuple[str, int]:
    """返回 (修正后的文本, 删除的空行数)。"""
    lines = text.splitlines()
    out: list[str] = []
    removed = 0
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append(line)
            i += 1
            continue
        if not in_code and CAP.match(line.strip()):
            # 表题行：跳过其后的空行，直到表格首行（只跳空行，不动其他内容）
            out.append(line)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                removed += 1
                j += 1
            i = j
            continue
        out.append(line)
        i += 1
    # 去掉末尾多余空行，补一个换行
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n", removed


def main(argv: list[str]) -> int:
    dry = "--dry" in argv
    changed = 0
    for book in ("概要", "详细"):
        d = os.path.join(SRC, book)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".md"):
                continue
            path = os.path.join(d, f)
            with open(path, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
            text = raw.lstrip("\ufeff")
            new, removed = fix_text(text)
            if new != text:
                changed += 1
                print(f"[fix] {book}/{f}  删除表题与表格之间空行 {removed} 处")
                if not dry:
                    with open(path, "w", encoding="utf-8", newline="\n") as fh:
                        fh.write(new)
    print(f"\n共修改 {changed} 个文件" + ("（dry-run，未落盘）" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
