# -*- coding: utf-8 -*-
"""通用 markdown → PDF（scripts/build_md_pdf.py，2026-09-01 建）。

给医院/厂商的材料统一走这里生成，路径与样式跟 build_doctor_guide_pdf.py 一致
（markdown → 带打印样式的 HTML → Edge 无头打印），不引第三方排版引擎，中文
直接用系统微软雅黑不会缺字。

与 build_doctor_guide_pdf.py 的分工：那个脚本专管医生使用指南（源文件路径写死、
产物名固定，改完重跑即可）；本脚本处理一次性/临时的交付材料，源和目标都由参数给。

用法：
    python scripts/build_md_pdf.py <源.md> <目标.pdf>
"""
import subprocess
import sys
from pathlib import Path

import markdown

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Microsoft YaHei", sans-serif; font-size: 10.5pt;
       line-height: 1.75; color: #222; }
h1 { font-size: 19pt; color: #0891B2; border-bottom: 2px solid #0891B2;
     padding-bottom: 6px; }
h2 { font-size: 14pt; color: #0E7490; margin-top: 24px;
     border-left: 4px solid #0891B2; padding-left: 9px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #155E75; margin-top: 15px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 10px 0;
        page-break-inside: avoid; }
th, td { border: 1px solid #cfd8dc; padding: 6px 9px; font-size: 9.5pt;
         text-align: left; }
th { background: #ECFEFF; font-weight: 600; }
blockquote { border-left: 3px solid #94a3b8; margin: 10px 0; padding: 4px 14px;
             color: #475569; background: #f8fafc; }
strong { color: #0F172A; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 22px 0; }
li { margin: 3px 0; }
"""


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    # resolve()：Edge 的 --print-to-pdf 与 file:// URI 都要求绝对路径
    src, out_pdf = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if not src.exists():
        print(f"源文件不存在：{src}")
        return 1
    if not EDGE.exists():
        print(f"找不到 Edge：{EDGE}")
        return 1
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    html_body = markdown.markdown(
        src.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists"],
    )
    tmp_html = src.with_suffix(".tmp.html")
    tmp_html.write_text(
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<style>{CSS}</style></head><body>{html_body}</body></html>",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={out_pdf}", tmp_html.as_uri()],
        capture_output=True, text=True, timeout=180,
    )
    tmp_html.unlink(missing_ok=True)  # 中间产物不留，避免和源文件混在一起
    if not out_pdf.exists():
        print("PDF 未生成\n", proc.stderr[-500:])
        return 1
    print(f"已生成：{out_pdf}（{out_pdf.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
