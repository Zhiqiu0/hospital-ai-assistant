"""病历 prompt 构造共享件（services/ai/record_prompts_shared.py）

从 record_prompts.py 拆出（2026-08-11 超标文件拆分：310 行 → 门诊急诊主文件
+ 住院病程 record_prompts_inpatient.py + 本共享件），供两侧共同引用，
避免主文件与住院文件互相导入成环。
"""
from typing import Mapping

# 共享真实性硬约束（嵌入每个 prompt 末尾）
TRUTHFULNESS_RULES = """⚠️ 内容真实性硬约束（违反就是医疗合规事故）：
1. 严格只使用医生录入的问诊信息，**禁止编造任何医生未提供的内容**
2. 任何字段为空时，对应 JSON value **必须**填字符串 "[未填写，需补充]"，
   不得按"规范模板"自动补"发育正常""营养良好""无心脑血管疾病"等
3. 主诉/诊断/舌象/脉象/治则治法 这五项**内容严格照抄**医生录入原文，不得推断、
   不得增删任何诊断名/证型/舌脉描述；仅允许对诊断做**排版整理**
   （如拆成"中医诊断：X（Y证）"与"西医诊断：1.… 2.…"两行、补序号）
4. 体格检查的生命体征（physical_exam_vitals）必须按
   "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg" 一整行格式输出，
   严格照抄医生录入的体征数据；缺项写"[未测]"；全部为空写"[未填写，需补充]"
5. 输出**必须是合法 JSON**，key **严格匹配** schema 列出的字段（不增不减），
   value 全部为字符串类型；禁止任何前言、Markdown 装饰、代码块标记"""


def format_schema_block(schema: Mapping[str, str]) -> str:
    """把 schema 字段表渲染成"- key: 描述"列表，注入 prompt 让 LLM 知道要填哪些 key。"""
    return "\n".join(f"- {key}: {desc}" for key, desc in schema.items())
