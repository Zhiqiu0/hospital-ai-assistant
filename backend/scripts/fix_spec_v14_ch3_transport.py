# -*- coding: utf-8 -*-
"""修 v1.4 规范第 3 章三张「接口信息」表里的方案 A（HTTP）残留。

背景（2026-08-17 发文前最后一遍核验发现）：
  make_spec_ws_only.py 出 v1.4 时清理了附录 A.1~A.3 示例的 HTTP 外壳，
  但 3.1 / 3.2 / 3.3 三张「接口信息」表的「请求地址 / 请求方式」两行漏掉了——
  3.2、3.3 仍写着「POST http://{his_host}:{port}/...（贵方提供）」，
  与 5.2「贵方无需提供任何地址、无需对外开放任何接口」直接矛盾。
  厂商先读第 3 章会以为自己要开发 HTTP 接口，属「同一份文档给相反指令」。

做法：直接改 v1.4 docx（它是唯一真源），把三张表的传输行改成 WebSocket 口径。
  与 v1.4 其余单通道改写一致，不加「▲」高亮（这是新基线，不是待厂商评审的变更）。
  幂等：重复运行时按「已是新措辞」跳过，不会叠加。

用法：python scripts/fix_spec_v14_ch3_transport.py
"""
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table

DOC = Path("d:/Code/hospital-ai-assistant/docs/MediScribe_HIS接口规范_v1.4_单通道.docx")

applied: list[str] = []
skipped: list[str] = []
failed: list[str] = []


def _tables(doc):
    """按文档顺序取所有顶层表格。"""
    return [Table(c, doc) for c in doc.element.body.iterchildren() if c.tag == qn("w:tbl")]


def _set_cell(cell, text, tag):
    """整格换文本：保留首个 run 的字体格式，删掉其余 run（与 make_spec_ws_only 同法）。"""
    para = cell.paragraphs[0]
    runs = list(para.runs)
    if not runs:
        failed.append(f"{tag}｜目标格没有 run")
        return
    runs[0].text = text
    for r in runs[1:]:
        r._r.getparent().remove(r._r)
    applied.append(tag)


def _fix_row(tbl, old_key, new_key, new_val, tag):
    """把「old_key | 旧内容」行改成「new_key | new_val」；已改过则跳过（幂等）。"""
    for row in tbl.rows:
        key = row.cells[0].text.strip()
        if key == new_key:
            skipped.append(f"{tag}｜已是新措辞")
            return
        if key == old_key:
            _set_cell(row.cells[0], new_key, f"{tag}｜键")
            _set_cell(row.cells[1], new_val, f"{tag}｜值")
            return
    failed.append(f"{tag}｜表里找不到行：{old_key}")


def _fix_cell_value(tbl, key, old_sub, new_val, tag):
    """按行键定位，整格替换内容；内容里已无 old_sub 则跳过（幂等）。"""
    for row in tbl.rows:
        if row.cells[0].text.strip() == key:
            if old_sub not in row.cells[1].text:
                skipped.append(f"{tag}｜已是新措辞")
                return
            _set_cell(row.cells[1], new_val, tag)
            return
    failed.append(f"{tag}｜表里找不到行：{key}")


def main() -> int:
    doc = docx.Document(str(DOC))
    tables = _tables(doc)

    # 三张「接口信息」表按结构定位：全文只有它们三张含「接口说明」行，
    # 且按文档顺序恰为 3.1 接诊推送 / 3.2 回写写入 / 3.3 触发刷新。
    # （不按内容关键词找：record_writeback 等词也出现在附录 C 变更表里，会抓错。）
    info_tables = [t for t in tables
                   if any(r.cells[0].text.strip() == "接口说明" for r in t.rows)]
    if len(info_tables) != 3:
        print(f"[失败] 期望恰好 3 张接口信息表，实际找到 {len(info_tables)} 张")
        return 1
    admit, writeback, refresh = info_tables

    # ── 3.1 接诊数据推送（HIS → 我方，上行）─────────────────────────────
    _fix_row(admit, "请求地址", "传输方式",
             "经贵方建立的 wss 长连接上行发送，消息 type=encounter_admit（外层信封见 7.3，通道见第 7 章）",
             "3.1 传输方式")
    _fix_row(admit, "请求方式", "报文格式",
             "JSON（业务字段作为信封 payload 携带）",
             "3.1 报文格式")

    # ── 3.2 病历回写·写入（我方 → HIS，下行）───────────────────────────
    _fix_cell_value(writeback, "提供方", "需贵方提供",
                    "HIS（贵方在客户端内实现接收处理）",
                    "3.2 提供方")
    _fix_row(writeback, "请求地址", "传输方式",
             "经同一条 wss 长连接下行送达，消息 type=record_writeback（见第 7 章）；贵方无需提供任何接口地址",
             "3.2 传输方式")
    _fix_row(writeback, "请求方式", "报文格式",
             "JSON（业务字段作为信封 payload 携带）",
             "3.2 报文格式")

    # ── 3.3 病历回写·触发刷新（我方 → HIS，下行）────────────────────────
    _fix_cell_value(refresh, "提供方", "需贵方提供",
                    "HIS（贵方在客户端内实现接收处理）",
                    "3.3 提供方")
    _fix_row(refresh, "请求地址", "传输方式",
             "经同一条 wss 长连接下行送达，消息 type=record_refresh（见第 7 章）；贵方无需提供任何接口地址",
             "3.3 传输方式")

    doc.save(str(DOC))
    print(f"[完成] 应用 {len(applied)} 处，跳过 {len(skipped)} 处，失败 {len(failed)} 处")
    for t in applied:
        print("  改:", t)
    for t in skipped:
        print("  跳:", t)
    for t in failed:
        print("  败:", t)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
