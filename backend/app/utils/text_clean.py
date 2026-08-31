# -*- coding: utf-8 -*-
"""不可见字符清洗的单一真源（app/utils/text_clean.py）

2026-08-31 极端输入审计新增。起因是一个纯静默的病历损坏路径：

    医生从 Word / PDF / 微信里复制一段话粘进「主诉」，再删掉可见文字，
    字段里常残留一个**零宽空格**（排版软件用它控制断行，复制时一并带走）。

    Python 的 str.strip() 认得 U+3000 全角空格和 U+00A0，**认不得零宽字符系**
    （实测 "\u200b".strip() 长度仍是 1）。于是：
      · 打印出来的法定病历上，「主诉」栏是**空白**；
      · 而质控引擎的 Section.is_filled() 判定它「已填写」——阈值
        MIN_FILLED_LENGTH=1，一个零宽字符就够——不扣分、不报缺项。
    医生据此正常签发，浙江省门急诊病历评分标准里「主诉未填写」这类强制项
    整条失效。这是**静默损坏**，不是报错，事后也查不出来。

同一份字符清单此前被复制粘贴到三处（schemas/patient.py 的姓名清洗、
schemas/diagnosis.py 的诊断名清洗、his_adapter/admit_service.py 的 HIS 姓名
清洗），唯独病历正文这条路径漏了——清单散落多份就迟早漂移（补一个新码点
只改了两处，就是第四种不一致）。故收口于此，谁都不要再自己抄一份。
"""

# 零宽空格 / 零宽非连接符 / 零宽连接符 / BOM / 词连接符 / NUL。
# 这些码点在中文病历里没有任何合法用途，一律视为噪声。
INVISIBLE_CHARS: tuple[str, ...] = (
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\ufeff",  # BOM / ZERO WIDTH NO-BREAK SPACE
    "\u2060",  # WORD JOINER
    "\x00",    # NUL
)


def strip_invisible(text: str) -> str:
    """剥掉不可见字符，其余内容原样保留（不 strip 首尾、不压平换行）。

    Args:
        text: 原始文本。

    Returns:
        剥离不可见字符后的文本；入参非字符串时原样返回。
    """
    if not isinstance(text, str):
        return text
    for ch in INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return text
