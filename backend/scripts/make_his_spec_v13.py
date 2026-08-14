"""生成 v1.3 变更版规范：开头插一页醒目的变更摘要。

为什么把摘要放最前面而不是只改正文：
  厂商工程师拿到新版文档不会逐页对比，改动散在 20 多处正文里必然漏看。
  第一页一张表把「改了什么 / 在哪 / 你要不要动代码」讲完，才是他真正会读的东西。
  正文里的逐处修订随后再做（见 apply_v13_body.py）。
"""
import copy
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

sys.path.insert(0, str(Path(__file__).parent))
from his_spec_changes_v13 import CHANGES  # noqa: E402

SRC = Path("d:/Code/hospital-ai-assistant/docs/MediScribe_HIS接口规范.docx")
OUT = Path("d:/Code/hospital-ai-assistant/docs/MediScribe_HIS接口规范_v1.3.docx")

RED = RGBColor(0xC0, 0x00, 0x00)
DARK = RGBColor(0x33, 0x33, 0x33)
GRAY = RGBColor(0x66, 0x66, 0x66)

PRIO_TITLE = {
    "A": ("A 类｜请在贵方开发完成前对齐", RGBColor(0xC0, 0x00, 0x00)),
    "B": ("B 类｜可省掉贵方工作量（原要求已取消）", RGBColor(0x00, 0x70, 0xC0)),
    "C": ("C 类｜口径补充，避免联调时产生分歧", RGBColor(0x54, 0x6E, 0x7A)),
}


def _para_before(anchor, text="", *, size=10.5, bold=False, color=DARK,
                 align=None, space_after=4):
    """在 anchor 段落之前插入一个新段落并返回它。"""
    new_p = copy.deepcopy(anchor._p)
    anchor._p.addprevious(new_p)
    from docx.text.paragraph import Paragraph
    p = Paragraph(new_p, anchor._parent)
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.text = ""
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = "微软雅黑"
    p.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        p.alignment = align
    return p


def main() -> None:
    doc = docx.Document(str(SRC))

    # 版本号就地更新
    for p in doc.paragraphs[:5]:
        if "版本 v1.2" in p.text:
            for r in p.runs:
                if "v1.2" in r.text:
                    r.text = r.text.replace("v1.2", "v1.3")
                    r.font.color.rgb = RED
                    r.font.bold = True
            if "2026-08-11" in p.text:
                for r in p.runs:
                    r.text = r.text.replace("2026-08-11", "2026-08-14")

    anchor = doc.paragraphs[0]  # 全部插在文档最开头

    _para_before(anchor, "⚠ 本次修订说明（v1.2 → v1.3）", size=16, bold=True,
                 color=RED, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    _para_before(
        anchor,
        "本版共 %d 处修订。我方在联调前对代码与本规范做了一次逐条比对，"
        "把「规范写的」与「系统实际行为」不一致的地方一次性改齐，"
        "避免分多次打扰贵方。" % len(CHANGES),
        size=10.5, color=DARK, space_after=4,
    )
    _para_before(
        anchor,
        "请重点看 A 类（%d 项）——这几处若不对齐，联调时会出现"
        "「消息发出去了但对方没反应」这类难排查的问题。"
        "B 类是我方取消的要求，贵方可以少做一些事。"
        % len([c for c in CHANGES if c["prio"] == "A"]),
        size=10.5, bold=True, color=RED, space_after=10,
    )

    for prio in ("A", "B", "C"):
        items = [c for c in CHANGES if c["prio"] == prio]
        if not items:
            continue
        title, color = PRIO_TITLE[prio]
        _para_before(anchor, f"{title}（{len(items)} 项）",
                     size=12, bold=True, color=color, space_after=6)

        tbl = doc.add_table(rows=1, cols=4)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for i, h in enumerate(["位置", "改动内容", "为什么改", "贵方是否需改代码"]):
            para = hdr[i].paragraphs[0]
            for r0 in list(para.runs):
                r0._r.getparent().remove(r0._r)
            run = para.add_run(h)
            run.font.bold = True
            run.font.size = Pt(9)
            run.font.name = "微软雅黑"
        for c in items:
            row = tbl.add_row().cells
            for i, val in enumerate([c["loc"], c["what"], c["why"], c["impact"]]):
                para = row[i].paragraphs[0]
                for r0 in list(para.runs):
                    r0._r.getparent().remove(r0._r)
                run = para.add_run(val)
                run.font.size = Pt(9)
                run.font.name = "微软雅黑"
                if i == 3:
                    run.font.bold = True
                    run.font.color.rgb = (
                        RED if val == "需改代码"
                        else RGBColor(0x00, 0x80, 0x00) if val == "可省工作量"
                        else GRAY
                    )
        # 表格是 append 到文档末尾的，搬到锚点前
        anchor._p.addprevious(tbl._tbl)
        _para_before(anchor, "", size=6, space_after=6)

    _para_before(
        anchor,
        "以下为规范正文（v1.3）。正文中对应上述条目的位置已同步修订。",
        size=10, color=GRAY, space_after=2,
    )
    _para_before(anchor, "—" * 46, size=9, color=GRAY, space_after=10)

    doc.save(str(OUT))
    print(f"已生成：{OUT}")
    print(f"变更条目 {len(CHANGES)} 项（A {len([c for c in CHANGES if c['prio']=='A'])} / "
          f"B {len([c for c in CHANGES if c['prio']=='B'])} / "
          f"C {len([c for c in CHANGES if c['prio']=='C'])}）")


if __name__ == "__main__":
    main()
