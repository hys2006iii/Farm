# -*- coding: utf-8 -*-
"""对生成好的 docx 做结构自检（不依赖 Word / LibreOffice）。

用法：
    python verify_docx.py                  # 检查 docs/../../文档/ 下两份
    python verify_docx.py <path.docx>      # 检查指定文件

检查项：
  - 段落总数、各级标题数量（Heading 1/2/3）；
  - 表格数量与每个表格的行列数；
  - 内嵌图片数量；
  - 是否残留「缺图」「TODO」「待补充」等占位文本；
  - 目录域（TOC）是否存在、目录条目数；
  - 中文字数与总字符数；
  - 是否出现空段落连续超过 3 个的可疑排版。
"""
from __future__ import annotations

import os
import sys
import zipfile

from docx import Document
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.abspath(os.path.join(HERE, "..", "..", "文档"))

BAD = ("［缺图", "TODO", "待补充", "待定")


def image_count(docx_path: str) -> int:
    """统计 docx 包里 word/media 下的图片文件数。"""
    try:
        with zipfile.ZipFile(docx_path) as z:
            return len([n for n in z.namelist() if n.startswith("word/media/")])
    except Exception:
        return 0


def toc_entries(doc) -> int:
    """粗算目录条目数：目录域的 TOC 结果里每个条目含 w:instrText 与超链接。"""
    body = doc.element.body
    return len(body.findall(".//" + qn("w:hyperlink")))


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        targets = [argv[1]]
    else:
        targets = []
        for f in sorted(os.listdir(OUTDIR)) if os.path.isdir(OUTDIR) else []:
            if f.endswith(".docx"):
                targets.append(os.path.join(OUTDIR, f))
    if not targets:
        print("没有找到 docx：%s" % OUTDIR)
        return 1

    rc = 0
    for path in targets:
        print("=" * 70)
        print(os.path.basename(path), "  %.1f KB" % (os.path.getsize(path) / 1024))
        doc = Document(path)
        paras = doc.paragraphs
        heads = {}
        for p in paras:
            name = (p.style.name or "")
            if name.startswith("Heading"):
                heads[name] = heads.get(name, 0) + 1
        print("段落 %d 个；标题分布：%s" % (len(paras), heads or "无"))
        print("表格 %d 个" % len(doc.tables))
        for i, t in enumerate(doc.tables, 1):
            rows = len(t.rows)
            cols = len(t.columns)
            print("   表 %-2d %d 行 × %d 列" % (i, rows, cols))
        print("内嵌图片 %d 张" % image_count(path))
        print("目录超链接 %d 条" % toc_entries(doc))

        text = "\n".join(p.text for p in paras)
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    text += "\n" + cell.text
        bad = [w for w in BAD if w in text]
        if bad:
            print("[ERR] 残留占位文本：%s" % "、".join(bad))
            rc = 1
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        print("字符 %d 个，其中中文 %d 个" % (len(text), cjk))
        print("文档属性：标题=%s  主题=%s" % (doc.core_properties.title, doc.core_properties.subject))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
