"""生成HIS联调验收步骤单，保留2026-09-22交付PDF的原有版式。

原深蓝样式来自历史生成命令；通用生成器的青色样式不适用于这份已定稿材料。
用法：python backend/scripts/build_his_acceptance_pdf.py [输出PDF路径]
默认从仓库Markdown生成 docs/guide/MediScribe_HIS联调验收步骤单.pdf。
"""
import sys
from pathlib import Path

import build_md_pdf

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/guide/HIS联调验收步骤单.md"
OUTPUT = ROOT / "docs/guide/MediScribe_HIS联调验收步骤单.pdf"

# 保持原A4页边距、字体、字号、表头颜色和整表分页规则；中文代码也回退到微软雅黑。
CSS = """
@page { size: A4; margin: 17mm 15mm; }
* { font-family: "Microsoft YaHei", "PingFang SC", sans-serif; }
body { font-size: 12.5px; color: #1f2937; line-height: 1.78; }
h1 { font-size: 20px; border-bottom: 3px solid #2563eb; padding-bottom: 8px; color: #1e3a8a; }
h2 { font-size: 16px; color: #1e3a8a; border-left: 4px solid #2563eb; padding-left: 8px;
     margin-top: 24px; page-break-after: avoid; }
h3 { font-size: 14px; color: #0f172a; margin-top: 18px; page-break-after: avoid; }
blockquote { margin: 10px 0; padding: 8px 14px; background: #eff6ff;
             border-left: 3px solid #93c5fd; color: #374151; }
blockquote p { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 11.5px;
        page-break-inside: avoid; }
th { background: #1e3a8a; color: #fff; padding: 6px 8px; text-align: left; }
td { border: 1px solid #cbd5e1; padding: 6px 8px; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
code { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 3px; padding: 0 4px;
       font-family: Consolas, "Microsoft YaHei", monospace; font-size: 11px; color: #be123c; }
th code { color: #fde68a; background: transparent; border: none; }
strong { color: #111827; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 16px 0; }
ol, ul { padding-left: 22px; }
"""


def main() -> int:
    """复用现有Markdown/Edge管线，仅指定这份材料的维护源及原版样式。"""
    if len(sys.argv) > 2:
        print(__doc__)
        return 1
    output = Path(sys.argv[1]) if len(sys.argv) == 2 else OUTPUT
    build_md_pdf.CSS = CSS
    sys.argv = [sys.argv[0], str(SOURCE), str(output)]
    return build_md_pdf.main()


if __name__ == "__main__":
    sys.exit(main())
