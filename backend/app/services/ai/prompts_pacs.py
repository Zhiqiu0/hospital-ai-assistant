"""
PACS 影像 AI 分析专用 prompt（千问 VL 等多模态模型）

集中管理两条调用链的 prompt：
  - analyze_study   ：放射科医生从已上传的 study 选关键帧批量分析
  - analyze_image   ：临床医生上传单张 JPG/PNG/DCM 即时分析

两条链共用同一份"放射科结构化报告"格式，仅在头部一句话上区分：
  - study   含 "序列" 字样（多帧 CT/MR 必谈序列）
  - image   只到 "部位"（单图无序列概念）

如需调整结构化字段（影像类型/影像所见/印象/建议），改这一处即可。
"""
from typing import Optional


# 公共结构化报告主体（不含开头一句"你是放射科医生..."）
_PACS_REPORT_BODY = """请按以下结构输出报告：

【影像类型】
（说明检查类型、部位{seq_hint}）

【影像所见】
（逐系统描述主要所见，使用规范医学术语）

【印象】
（总结主要发现，按重要性排列）

【建议】
（后续处理或随访建议）

要求：使用规范中文医学术语，客观描述所见，不过度推断。"""


def build_study_prompt(modality: Optional[str], body_part: Optional[str]) -> str:
    """构造 study 级（多帧）分析 prompt。

    modality 为 None 时退化成 "影像"，body_part 为 None 时省略括号内容。
    包含"序列"提示——多帧 CT/MR 一般会有不同序列（轴位/矢状位/T1/T2 等）。
    """
    mod = modality or "影像"
    part = body_part or ""
    head = f"你是一位经验丰富的放射科医生。请对以下{mod}影像（{part}）进行专业分析。"
    body = _PACS_REPORT_BODY.format(seq_hint="、序列")
    return f"{head}\n\n{body}"


def build_image_prompt(image_type: Optional[str]) -> str:
    """构造单图分析 prompt（临床医生侧入口）。

    image_type 为可选标签（如 "胸部 X 光"），仅作为提示词的一部分。
    单图无"序列"概念，因此结构化字段中不出现"序列"二字。
    """
    hint = f"（{image_type}）" if image_type else ""
    head = f"你是一位经验丰富的放射科医生。请对以下医学影像{hint}进行专业分析。"
    body = _PACS_REPORT_BODY.format(seq_hint="")
    return f"{head}\n\n{body}"
