"""
病历 AI 生成服务的辅助模块（app/services/ai/_record_gen_helpers.py）

从 record_gen_service.py 拆出的纯常量与纯函数：
  - GENERATE_PROMPT / POLISH_PROMPT ：生成、润色的提示词模板
  - RECORD_TYPE_MAP                 ：病历类型英文键→中文名
  - _clean_ai_intro                 ：剥离 AI 输出里的引言/装饰符号

拆分目的：把与 db/session 无关的纯逻辑从服务门面剥离，主文件专注编排。
行为与原实现完全一致，仅做机械搬迁。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import re as _re


# AI 引言常见前缀，正文里出现这些就剥离
# prompt 已经强约束禁止，本清洗作为兜底（LLM 偶尔越界）
_AI_INTRO_PATTERNS = (
    "根据您提供的信息",
    "根据以上信息",
    "现为您生成",
    "以下是",
    "以下为",
    "请您查看",
    "请医生审核",
    "希望对您有帮助",
)


def _clean_ai_intro(text: str) -> str:
    """剥离 AI 输出里的引言、Markdown 装饰、章节名包裹的星号。

    医生看到的应该是纯病历内容，不要 AI "我现在为您生成..."这类元描述。

    步骤：
      1. 如果文本含 `【` 章节标题，剥离第一个 `【` 之前的所有前言（最干净）
      2. 如果不含章节标题（如润色场景返回纯文本），按行剥离引言/装饰
      3. 全文范围去掉 `**【XXX】**` 的多余星号包裹
    """
    if not text:
        return text

    # 步骤 0：先把 `**【XXX】**` → `【XXX】`，避免后面找 `【` 时残留前面的 `**`
    text = _re.sub(r"\*\*(【[^】]+】)\*\*", r"\1", text)

    # 优先方案：找到第一个 【 章节作为正文起点
    # 这是入院记录、首次病程等结构化文档的明显特征
    bracket_idx = text.find("【")
    if bracket_idx > 0:
        text = text[bracket_idx:].strip()

    # 兜底：按行剥离开头的空行 / 装饰符号 / 引言行
    lines = text.split("\n")
    skip_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            skip_idx = i + 1
            continue
        if stripped in {"---", "###", "**"} or stripped.startswith("---") or stripped.startswith("###"):
            skip_idx = i + 1
            continue
        if any(p in stripped for p in _AI_INTRO_PATTERNS):
            skip_idx = i + 1
            continue
        break
    cleaned = "\n".join(lines[skip_idx:]).strip()
    return cleaned


GENERATE_PROMPT = """你是一名专业的临床病历书写助手。根据以下问诊信息，生成标准化的{record_type}病历草稿。

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

请输出JSON格式，包含以下字段：
{{
  "chief_complaint": "规范化主诉（症状+时间，20字以内）",
  "history_present_illness": "规范化现病史（时间顺序，书面语）",
  "past_history": "规范化既往史",
  "allergy_history": "规范化过敏史",
  "personal_history": "规范化个人史",
  "physical_exam": "规范化体格检查",
  "initial_diagnosis": "初步诊断"
}}

要求：口语转书面语，时间线清晰，符合医疗文书规范。"""

POLISH_PROMPT = """你是临床病历规范化专家。请对以下病历内容进行润色，要求：
1. 口语转书面医学语言
2. 消除重复内容
3. 优化时间顺序
4. 保持医学术语准确性

原始内容：
{content}

请输出相同JSON结构，仅改善表达，不添加虚构内容。"""


RECORD_TYPE_MAP = {
    "outpatient": "门诊",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
}
