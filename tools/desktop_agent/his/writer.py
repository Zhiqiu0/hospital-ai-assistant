"""写回金算盘 HIS(writer.py)

按 jinsuanpan_map.yaml 字段映射,把 MediScribe 生成的病历字段一个一个
填入金算盘对应控件。

填入策略(按 YAML strategy 字段):
  - skip_if_filled    : HIS 已有内容就不重填(姓名/身份证等已知字段)
  - set_value_if_empty: HIS 为空才填(电话/地址等可选字段)
  - set_value         : 直接覆盖填(过敏史等 AI 写入字段)
  - set_combo_value   : ComboBox 用 SelectionItemPattern
  - click_send_tab    : DataGrid 编辑模式 — Click → SendKeys → Tab
  - find_sibling_set_value: 病历主页 baseControl* — 按 label 找 sibling
  - typeahead         : 诊断面板 — 输入关键字 → 等下拉 → Click 选中

兜底:
  单字段失败重试 max_retries 次,仍失败 → 复制到剪贴板 + 标 fallback_clipboard
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("mediscribe.agent.writer")


@dataclass
class FillFieldResult:
    field_key: str
    his_automation_id: str | None
    status: str  # success / failed / skipped / fallback_clipboard
    duration_ms: int = 0
    error_message: str | None = None


def fill_fields(
    window: Any,
    field_map: dict[str, Any],
    fields: list[dict[str, Any]],
) -> list[FillFieldResult]:
    """按字段映射依次填入。

    Args:
        window:      detector.find_jinsuanpan_window() 返回的窗口对象。
        field_map:   jinsuanpan_map.yaml 解析后的 dict。
        fields:      前端 /fill 入参中的 fields 列表。

    Returns:
        每个字段的填入结果列表(同顺序)。
    """
    results: list[FillFieldResult] = []
    # TODO: 真实实现 — 按 section 分流到 intake / record / diagnosis 子流程
    # for f in fields:
    #     if f['section'] == 'intake':
    #         results.append(_fill_intake_field(window, field_map, f))
    #     elif f['section'] == 'record':
    #         results.append(_fill_record_field(window, field_map, f))
    #     elif f['section'] == 'diagnosis':
    #         results.append(_fill_diagnosis(window, field_map, f))
    #     else:
    #         results.append(FillFieldResult(
    #             field_key=f['field_key'], status='skipped',
    #             error_message=f'unknown section: {f["section"]}'
    #         ))
    logger.warning("writer.fill_fields: 骨架版 stub,所有字段直接返回 skipped")
    for f in fields:
        results.append(
            FillFieldResult(
                field_key=f["field_key"],
                his_automation_id=None,
                status="skipped",
                error_message="骨架版未实现",
            )
        )
    return results
