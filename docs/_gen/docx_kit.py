# -*- coding: utf-8 -*-
"""Markdown 子集 -> Word 渲染器（青禾智灌 说明书 系列专用）。

只服务于 docs/_gen/ 下的两份设计说明书，语法见 docs/_gen/契约_格式与Markdown.md。
依赖：python-docx（已装）。可选：Pillow（用于按原图比例限宽）。
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.styles.style import _ParagraphStyle

# ---------------------------------------------------------------- 主题
DARK = RGBColor(0x17, 0x4D, 0x32)
GREEN = RGBColor(0x1F, 0x6B, 0x45)
SUB = RGBColor(0x6B, 0x7A, 0x72)
BLACK = RGBColor(0x22, 0x22, 0x22)
HEAD_FILL = "E7F3EB"
CODE_FILL = "F4F6F4"
QUOTE_FILL = "F1F7F2"

CN_FONT = "微软雅黑"
LATIN_FONT = "Segoe UI"
MONO_FONT = "Consolas"
BODY_SIZE = Pt(10.5)
MAX_IMG_CM = 15.5

# ---------------------------------------------------------------- 底层工具


def set_run_font(run, cn: str = CN_FONT, latin: str = LATIN_FONT) -> None:
    """让同一个 run 的中文与西文都有字体（python-docx 不直接支持 eastAsia）。"""
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), cn)


def shade(element, fill: str) -> None:
    pr = element.get_or_add_tcPr() if element.tag.endswith("}tc") else element.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def para_border(paragraph, fill: str = None) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    for edge in ("top", "left", "bottom", "right"):
        e = OxmlElement("w:" + edge)
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:space"), "4")
        e.set(qn("w:color"), "D5E4D9")
        bdr.append(e)
    ppr.append(bdr)
    if fill:
        shade(paragraph._p, fill)


def add_field(paragraph, instr: str) -> None:
    r = paragraph.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    r._r.append(fld)
    r = paragraph.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r._r.append(it)
    r = paragraph.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "separate")
    r._r.append(fld)
    r = paragraph.add_run("1")
    r = paragraph.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "end")
    r._r.append(fld)


# ---------------------------------------------------------------- 行内解析
INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")


def emit_inline(paragraph, text: str, size: Pt = None, color: RGBColor = None, bold=False):
    for chunk in INLINE_RE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            run = paragraph.add_run(chunk[2:-2])
            run.bold = True
            set_run_font(run)
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            run = paragraph.add_run(chunk[1:-1])
            set_run_font(run, cn=MONO_FONT, latin=MONO_FONT)
            run.font.color.rgb = RGBColor(0x0B, 0x50, 0x34)
        else:
            run = paragraph.add_run(chunk)
            set_run_font(run)
        if size:
            run.font.size = size
        if color:
            run.font.color.rgb = color
        if bold:
            run.bold = True
    return paragraph


# ---------------------------------------------------------------- 渲染器
@dataclass
class Meta:
    title: str = "青禾智灌智慧灌溉管理平台"
    subtitle: str = "设计说明书"
    version: str = "V1.0"
    date: str = ""


@dataclass
class Renderer:
    doc: Document
    base_dir: str
    meta: Meta = field(default_factory=Meta)

    # ------ 样式初始化
    def setup(self):
        # 文档属性：让「文件 → 属性」与资源管理器里能看出这是什么文档
        cp = self.doc.core_properties
        cp.title = "%s %s" % (self.meta.title, self.meta.subtitle)
        cp.subject = self.meta.subtitle
        cp.author = "青禾智灌项目组"
        cp.category = "设计文档"
        cp.comments = "%s %s" % (self.meta.version, self.meta.date)
        for name, size_pt, color, bold, before, after in (
            ("Heading 1", 16, DARK, True, 14, 8),
            ("Heading 2", 14, DARK, True, 12, 6),
            ("Heading 3", 12, GREEN, True, 10, 4),
            ("Heading 4", 11, GREEN, True, 8, 4),
        ):
            st: _ParagraphStyle = self.doc.styles[name]
            st.font.size = Pt(size_pt)
            st.font.bold = bold
            st.font.color.rgb = color
            st.font.name = LATIN_FONT
            rpr = st.element.get_or_add_rPr()
            rf = rpr.find(qn("w:rFonts"))
            if rf is None:
                rf = OxmlElement("w:rFonts")
                rpr.append(rf)
            rf.set(qn("w:eastAsia"), CN_FONT)
            st.paragraph_format.space_before = Pt(before)
            st.paragraph_format.space_after = Pt(after)
            st.paragraph_format.keep_with_next = True

        normal = self.doc.styles["Normal"]
        normal.font.size = BODY_SIZE
        normal.font.color.rgb = BLACK
        normal.font.name = LATIN_FONT
        rpr = normal.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        rf.set(qn("w:eastAsia"), CN_FONT)
        normal.paragraph_format.line_spacing = 1.45
        normal.paragraph_format.space_after = Pt(4)

        sec = self.doc.sections[0]
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.4)
        sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.6)
        sec.right_margin = Cm(2.6)
        self._footer(sec)
        self._header(sec)

    def _header(self, sec):
        p = sec.header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(f"{self.meta.title}  {self.meta.subtitle}  {self.meta.version}")
        set_run_font(r)
        r.font.size = Pt(8.5)
        r.font.color.rgb = SUB

    def _footer(self, sec):
        p = sec.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_field(p, "PAGE")
        for r in p.runs:
            set_run_font(r)
            r.font.size = Pt(9)
            r.font.color.rgb = SUB

    # ------ 封面 + 目录
    def cover(self):
        for _ in range(6):
            self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.meta.title)
        set_run_font(r)
        r.font.size = Pt(26)
        r.bold = True
        r.font.color.rgb = DARK

        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.meta.version)
        set_run_font(r)
        r.font.size = Pt(15)
        r.font.color.rgb = SUB

        for _ in range(3):
            self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.meta.subtitle)
        set_run_font(r)
        r.font.size = Pt(24)
        r.bold = True
        r.font.color.rgb = GREEN

        for _ in range(8):
            self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.meta.date)
        set_run_font(r)
        r.font.size = Pt(12)
        r.font.color.rgb = SUB
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def toc(self):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("目　录")
        set_run_font(r)
        r.font.size = Pt(18)
        r.bold = True
        r.font.color.rgb = DARK
        self.doc.add_paragraph()
        p = self.doc.add_paragraph()
        add_field(p, 'TOC \\o "1-3" \\h \\z \\u')
        for r in p.runs:
            set_run_font(r)
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ------ 块级
    def heading(self, level: int, text: str):
        self.doc.add_heading(text, level=level)

    def para(self, text: str, indent: bool = True):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if indent:
            p.paragraph_format.first_line_indent = Pt(21)
        emit_inline(p, text)

    def bullet(self, text: str, level: int = 0):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(18 + 18 * level)
        p.paragraph_format.space_after = Pt(2)
        mark = "●　" if level == 0 else "○　"
        r = p.add_run(mark)
        set_run_font(r)
        r.font.size = BODY_SIZE
        r.font.color.rgb = GREEN
        emit_inline(p, text)

    def ordered(self, num: str, text: str):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(18)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(num + "　")
        set_run_font(r)
        r.font.size = BODY_SIZE
        emit_inline(p, text)

    def quote(self, lines: List[str]):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(14)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(8)
        for i, line in enumerate(lines):
            if i:
                p.add_run().add_break()
            emit_inline(p, line)
        para_border(p, QUOTE_FILL)

    def code(self, lines: List[str]):
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Pt(12)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.0
        for i, line in enumerate(lines):
            if i:
                p.add_run().add_break()
            r = p.add_run(line)
            set_run_font(r, cn=MONO_FONT, latin=MONO_FONT)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x21, 0x2A, 0x24)
        para_border(p, CODE_FILL)

    def caption(self, text: str, above: bool):
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2 if not above else 8)
        p.paragraph_format.space_after = Pt(2 if above else 8)
        p.paragraph_format.keep_with_next = above
        emit_inline(p, text, size=Pt(9.5), color=SUB)

    def image(self, rel: str, caption: str):
        path = rel if os.path.isabs(rel) else os.path.join(self.base_dir, rel)
        if not os.path.exists(path):
            self.para(f"［缺图：{rel}］", indent=False)
            return
        width = Cm(MAX_IMG_CM)
        try:
            from PIL import Image

            with Image.open(path) as im:
                if im.width / im.height < 1.2:  # 偏竖的图压窄一点更好看
                    width = Cm(min(MAX_IMG_CM, 11.0))
        except Exception:
            pass
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(path, width=width)
        self.caption(caption, above=False)

    def table(self, rows: List[List[str]], caption: Optional[str]):
        if caption:
            self.caption(caption, above=True)
        cols = max(len(r) for r in rows)
        t = self.doc.add_table(rows=0, cols=cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = True
        for ri, row in enumerate(rows):
            cells = t.add_row().cells
            for ci in range(cols):
                txt = row[ci] if ci < len(row) else ""
                cell = cells[ci]
                cell.text = ""
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing = 1.15
                emit_inline(p, txt, size=Pt(9.5), color=DARK if ri == 0 else BLACK, bold=(ri == 0))
                if ri == 0:
                    shade(cell._tc, HEAD_FILL)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    # ------ 主流程
    def blocks(self, text: str, base_dir: Optional[str] = None):
        base = base_dir or self.base_dir
        saved, self.base_dir = self.base_dir, base
        lines = text.split("\n")
        i = 0
        prev_caption = None
        while i < len(lines):
            raw = lines[i]
            line = raw.rstrip()
            s = line.strip()

            if not s:
                i += 1
                continue
            if s == "<!-- pagebreak -->":
                self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
                i += 1
                continue
            if s.startswith("```"):
                i += 1
                buf = []
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    buf.append(lines[i].rstrip())
                    i += 1
                i += 1
                self.code(buf)
                continue
            if s.startswith("|"):
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                        rows.append(cells)
                    i += 1
                self.table(rows, prev_caption)
                prev_caption = None
                continue
            if s.startswith("!["):
                m = re.match(r"!\[(.*?)\]\((.*?)\)", s)
                if m:
                    self.image(m.group(2), m.group(1))
                i += 1
                continue
            if s.startswith("#"):
                lvl = len(s) - len(s.lstrip("#"))
                self.heading(min(lvl, 4), s.lstrip("#").strip())
                prev_caption = None
                i += 1
                continue
            if s.startswith(">"):
                buf = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    buf.append(lines[i].strip().lstrip(">").strip())
                    i += 1
                self.quote(buf)
                continue
            m = re.match(r"^([-*])\s+(.*)$", s)
            if m:
                lvl = 1 if raw.startswith("  ") else 0
                self.bullet(m.group(2), lvl)
                i += 1
                continue
            m = re.match(r"^(\d+[.、)]|\(\d+\))\s*(.*)$", s)
            if m:
                self.ordered(m.group(1), m.group(2))
                i += 1
                continue
            # 表题 / 图题 单独一行：表题暂存，图题已由 ![..] 处理
            if re.match(r"^表\s*\d+[-–]\d+", s):
                prev_caption = s
                i += 1
                continue
            prev_caption = None
            self.para(s)
            i += 1
        self.base_dir = saved


# ---------------------------------------------------------------- 对外 API
def parse_front_matter(text: str) -> tuple[Meta, str]:
    meta = Meta()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4 :]
            for ln in head.split("\n"):
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    k, v = k.strip(), v.strip()
                    if hasattr(meta, k):
                        setattr(meta, k, v)
            return meta, body.lstrip("\n")
    return meta, text


def build(md_path: str, out_path: str) -> str:
    with open(md_path, "r", encoding="utf-8-sig") as fh:
        text = fh.read().lstrip("\ufeff")
    meta, body = parse_front_matter(text)
    base_dir = os.path.dirname(os.path.abspath(md_path))
    doc = Document()
    r = Renderer(doc=doc, base_dir=base_dir, meta=meta)
    r.setup()
    # 让 Word 打开时自动更新目录域
    try:
        settings = doc.settings.element
        el = settings.find(qn("w:updateFields"))
        if el is None:
            el = OxmlElement("w:updateFields")
            settings.append(el)
        el.set(qn("w:val"), "true")
    except Exception:
        pass
    r.cover()
    r.toc()
    r.blocks(body, base_dir)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc.save(out_path)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: docx_kit.py <in.md> <out.docx>")
        raise SystemExit(2)
    print(build(sys.argv[1], sys.argv[2]))


