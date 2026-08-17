"""问诊字段规范化服务（services/ai/field_normalize_service.py）

从 api/v1/ai_generation.py 拆出（2026-08-11 超标文件拆分）：
把"口语→书面、去重、格式统一"的 prompt 组装 + LLM 调用 + 结果解析
收进 service 层，路由只做请求/响应。
"""
import json
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options

logger = logging.getLogger(__name__)

# 字段英文名 → 中文标签映射（用于 normalize prompt 构建）
FIELD_LABELS: dict[str, str] = {
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "menstrual_history": "月经史",
    "physical_exam": "体格检查",
    "auxiliary_exam": "辅助检查",
    "initial_impression": "初步诊断",
}


async def run_normalize_fields(db: AsyncSession, fields: dict[str, str]) -> dict:
    """将修改的问诊字段规范化，返回 {"fields": {...}}（失败时原样返回不阻塞保存）。"""
    field_lines = "\n".join(
        f"{FIELD_LABELS.get(k, k)}：{v}" for k, v in fields.items() if v
    )
    prompt = (
        "你是临床病历规范化助手。请对以下问诊字段进行整理，要求：\n"
        "1. 口语转书面医学语言\n"
        "2. 去除重复信息（如同一数值在结构化行和自由文本中重复出现）\n"
        "3. 格式规范，符合医疗文书标准\n"
        "4. 不添加任何未提及的内容，不编造信息\n"
        "5. 每个字段独立整理，保持原有信息量\n\n"
        f"需整理的字段：\n{field_lines}\n\n"
        "请只输出JSON对象，key为字段名（英文），value为整理后的文本：\n"
        '{"chief_complaint": "...", "physical_exam": "...", ...}\n'
        "只输出本次传入的字段，不要输出未传入的字段。"
    )

    try:
        model_options = get_model_options("generate")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务（若有）、
        # 只读事务、把连接还回池，避免长 await 期间白占一条池连接。
        await db.commit()
        content = await llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            **(model_options or {}),
        )
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return {"fields": fields}
        result = json.loads(match.group())
        return {"fields": {k: result[k] for k in fields if k in result and result[k]}}
    except Exception as exc:
        logger.exception("ai.normalize: failed err=%s", exc)
        return {"fields": fields}  # 失败时原样返回，不阻塞保存
