# -*- coding: utf-8 -*-
"""医生使用指南 markdown → PDF（2026-08-17 建）。

**为什么要有这个脚本**：指南此前只有一份 md + 一份 PDF 躺在交付目录里，
仓库无源文件、无生成方式，于是产品改了三个月没人动它——上线时医生拿到的
是对不上的文档。现在源文件进仓库（docs/guide/），生成脚本化，改完重跑即可。

生成路径与原 PDF 一致（原文件 Producer=Skia/PDF、Creator=Windows Chrome，
即浏览器打印）：markdown → HTML（带打印样式）→ Edge 无头打印。
不引第三方排版引擎，中文字体直接用系统的微软雅黑，不会缺字。

用法：
    python scripts/build_doctor_guide_pdf.py
"""
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "guide" / "医生使用指南.md"
OUT_HTML = ROOT / "docs" / "guide" / "_医生使用指南.html"
OUT_PDF = ROOT / "docs" / "guide" / "MediScribe-医生使用指南.pdf"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# 打印样式：A4、页边距、表格边框、代码块灰底。
# 关键几条：表格不允许跨页断行（医生查表最怕半张表在上一页）、
# 标题与其后内容保持在同一页（page-break-after: avoid）。
CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Microsoft YaHei", sans-serif; font-size: 10.5pt;
       line-height: 1.75; color: #222; }
h1 { font-size: 20pt; color: #0891B2; border-bottom: 2px solid #0891B2;
     padding-bottom: 8px; }
h2 { font-size: 15pt; color: #0E7490; margin-top: 22px;
     border-left: 4px solid #0891B2; padding-left: 10px;
     page-break-after: avoid; }
h3 { font-size: 12pt; color: #155E75; margin-top: 16px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 10px 0;
        page-break-inside: avoid; }
th, td { border: 1px solid #cfd8dc; padding: 6px 9px; font-size: 9.5pt;
         vertical-align: top; }
th { background: #ECFEFF; font-weight: 600; }
code { background: #F1F5F9; padding: 1px 5px; border-radius: 3px;
       font-family: Consolas, monospace; font-size: 9.5pt; }
pre { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 4px;
      padding: 10px; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #94A3B8; margin: 10px 0; padding: 4px 14px;
             color: #475569; background: #F8FAFC; }
hr { border: none; border-top: 1px solid #E2E8F0; margin: 18px 0; }
strong { color: #0F172A; }
"""


def main() -> int:
    if not SRC.exists():
        print(f"找不到源文件：{SRC}")
        return 1
    if not EDGE.exists():
        print(f"找不到 Edge：{EDGE}\n（改用 Chrome 也可，把 EDGE 换成 chrome.exe 路径）")
        return 1

    html_body = markdown.markdown(
        SRC.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
    )
    OUT_HTML.write_text(
        f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<style>{CSS}</style></head><body>{html_body}</body></html>",
        encoding="utf-8",
    )

    # --headless=new 才支持 --print-to-pdf 的现代渲染；--no-pdf-header-footer
    # 去掉浏览器自带的页眉页脚（默认会印上 file:/// 路径，很难看）
    proc = subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={OUT_PDF}", OUT_HTML.as_uri()],
        capture_output=True, text=True, timeout=180,
    )
    if not OUT_PDF.exists():
        print("PDF 未生成\n", proc.stderr[-500:])
        return 1
    print(f"已生成：{OUT_PDF}（{OUT_PDF.stat().st_size / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
