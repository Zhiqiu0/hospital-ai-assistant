"""
AI 快捷接口 - 无需预建接诊记录，直接从问诊信息流式生成病历
"""
import base64
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, Query, Request
from fastapi import UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import get_current_user
from app.database import get_db
from app.models.medical_record import AITask, QCIssue, MedicalRecord
from app.models.config import PromptTemplate, ModelConfig
from app.models.voice_record import VoiceRecord
from app.services.ai.llm_client import llm_client
from app.services.rule_engine.completeness_rules import check_completeness
from app.services.rule_engine.insurance_rules import check_insurance_risk
from app.models.base import generate_uuid


def _safe_format(template: str, **kwargs) -> str:
    """Safely format a template with user-provided values.
    Escapes { and } in values to prevent KeyError when content contains curly braces."""
    safe_kwargs = {k: str(v).replace("{", "{{").replace("}", "}}") for k, v in kwargs.items()}
    return template.format(**safe_kwargs)


async def _log_task(task_type: str, token_input: int = 0, token_output: int = 0) -> str:
    """Log an AI task call to the ai_tasks table using its own DB session. Returns the task id."""
    from app.database import AsyncSessionLocal
    task_id = generate_uuid()
    async with AsyncSessionLocal() as db:
        task = AITask(
            id=task_id,
            task_type=task_type,
            status='done',
            token_input=token_input,
            token_output=token_output,
            model_name=llm_client.model,
        )
        db.add(task)
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"_log_task db commit failed: {e}")
    return task_id


async def _save_qc_issues(task_id: str, issues: list[dict], encounter_id: Optional[str] = None) -> None:
    """Persist QC issues to the qc_issues table. Runs in its own DB session."""
    if not issues:
        return
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Try to find a MedicalRecord for the encounter
        medical_record_id: Optional[str] = None
        if encounter_id:
            result = await db.execute(
                select(MedicalRecord)
                .where(MedicalRecord.encounter_id == encounter_id)
                .order_by(MedicalRecord.created_at.desc())
                .limit(1)
            )
            rec = result.scalar_one_or_none()
            if rec:
                medical_record_id = rec.id
        for issue in issues:
            qc = QCIssue(
                ai_task_id=task_id,
                medical_record_id=medical_record_id,
                issue_type=issue.get("issue_type") or "quality",
                risk_level=issue.get("risk_level") or "medium",
                field_name=issue.get("field_name"),
                issue_description=issue.get("issue_description") or "",
                suggestion=issue.get("suggestion"),
                source="ai" if not issue.get("issue_type") else "rule",
            )
            db.add(qc)
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"_save_qc_issues db commit failed: {e}")


async def _get_active_prompt(db: AsyncSession, scene: str) -> Optional[str]:
    """Return the active DB prompt template for a scene, or None if not found."""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.scene == scene,
            PromptTemplate.is_active == True,
        ).order_by(PromptTemplate.created_at.desc()).limit(1)
    )
    tpl = result.scalar_one_or_none()
    return tpl.content if tpl else None


async def _get_model_options(db: AsyncSession, scene: str) -> dict:
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.scene == scene,
            ModelConfig.is_active == True,
        ).limit(1)
    )
    config = result.scalar_one_or_none()
    return {
        "model_name": config.model_name if config else llm_client.model,
        "temperature": config.temperature if config else 0.3,
        "max_tokens": config.max_tokens if config else 4096,
    }

from app.core.rate_limit import ai_limiter

def _ai_rate_limit(request: Request):
    ai_limiter.check(request)

router = APIRouter(dependencies=[Depends(_ai_rate_limit)])


class QuickGenerateRequest(BaseModel):
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    personal_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""
    record_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""
    # Inpatient-specific assessment fields
    history_informant: Optional[str] = ""
    marital_history: Optional[str] = ""
    menstrual_history: Optional[str] = ""
    family_history: Optional[str] = ""
    current_medications: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    religion_belief: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    # 门诊中医四诊
    tcm_inspection: Optional[str] = ""
    tcm_auscultation: Optional[str] = ""
    tongue_coating: Optional[str] = ""
    pulse_condition: Optional[str] = ""
    # 门诊诊断细化
    western_diagnosis: Optional[str] = ""
    tcm_disease_diagnosis: Optional[str] = ""
    tcm_syndrome_diagnosis: Optional[str] = ""
    # 治疗意见
    treatment_method: Optional[str] = ""
    treatment_plan: Optional[str] = ""
    followup_advice: Optional[str] = ""
    precautions: Optional[str] = ""
    # 急诊附加
    observation_notes: Optional[str] = ""
    patient_disposition: Optional[str] = ""
    # 就诊性质
    is_first_visit: Optional[bool] = True
    visit_type_detail: Optional[str] = "outpatient"
    # 时间
    visit_time: Optional[str] = ""
    onset_time: Optional[str] = ""


class VoiceStructureRequest(BaseModel):
    transcript: str = ""
    transcript_id: Optional[str] = None
    visit_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""
    existing_inquiry: Optional[dict] = None


VOICE_STRUCTURE_PROMPT_OUTPATIENT = """你是一名临床门诊病历助手。请根据以下医患对话转写内容，提炼出结构化问诊信息，并生成一份逻辑清晰的门诊病历草稿。

患者信息：
姓名：{patient_name}
性别：{patient_gender}
年龄：{patient_age}

现有问诊信息（如有）：
{existing_inquiry}

对话转写：
{transcript}

请输出 JSON：
{{
  "transcript_summary": "对本次对话的简要概括，1-2句话",
  "speaker_dialogue": [
    {{"speaker": "doctor", "text": "医生说的话"}},
    {{"speaker": "patient", "text": "患者说的话"}},
    {{"speaker": "uncertain", "text": "无法确定归属的话"}}
  ],
  "inquiry": {{
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查（一般体征）",
    "tcm_inspection": "望诊内容（神色形态）",
    "tcm_auscultation": "闻诊内容（声音气味）",
    "tongue_coating": "舌象（舌质+舌苔，如：舌淡红苔薄白）",
    "pulse_condition": "脉象（如：脉弦细）",
    "western_diagnosis": "西医诊断",
    "tcm_disease_diagnosis": "中医疾病诊断（如：眩晕病）",
    "tcm_syndrome_diagnosis": "中医证候诊断（如：肝阳上亢证）",
    "treatment_method": "治则治法（如：平肝潜阳）",
    "treatment_plan": "处理意见（用药/治疗方案）",
    "followup_advice": "复诊建议",
    "initial_impression": "初步印象（补充）"
  }},
  "draft_record": "按【主诉】【现病史】【既往史】【过敏史】【个人史】【体格检查（含中医四诊、舌象脉象）】【辅助检查】【诊断（中医诊断含疾病+证候，西医诊断）】【治疗意见及措施（治则治法、处理意见、复诊建议）】输出的中医门诊病历草稿"
}}

要求：
- 只基于对话内容提炼，不得虚构
- 医生提问与患者回答混杂时，优先抽取患者已明确表达的事实
- 尽量区分 doctor / patient / uncertain 三类说话人；无法确定时标 uncertain
- 字段没有提到就输出空字符串
- 语言要书面化、时间线清晰、适合直接进入门诊病历编辑"""


VOICE_STRUCTURE_PROMPT_INPATIENT = """你是一名住院病历助手。请根据以下医患对话转写内容，提炼结构化入院问诊信息，并生成一份逻辑清晰的入院记录草稿。

患者信息：
姓名：{patient_name}
性别：{patient_gender}
年龄：{patient_age}

现有问诊信息（如有）：
{existing_inquiry}

对话转写：
{transcript}

请输出 JSON：
{{
  "transcript_summary": "对本次对话的简要概括，1-2句话",
  "speaker_dialogue": [
    {{"speaker": "doctor", "text": "医生说的话"}},
    {{"speaker": "patient", "text": "患者说的话"}},
    {{"speaker": "uncertain", "text": "无法确定归属的话"}}
  ],
  "inquiry": {{
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查",
    "initial_impression": "入院诊断或初步印象",
    "history_informant": "病史陈述者",
    "marital_history": "婚育史",
    "menstrual_history": "月经史",
    "family_history": "家族史",
    "current_medications": "当前用药",
    "rehabilitation_assessment": "康复需求评估",
    "religion_belief": "宗教信仰或饮食禁忌",
    "pain_assessment": "疼痛评分",
    "vte_risk": "VTE风险",
    "nutrition_assessment": "营养评估",
    "psychology_assessment": "心理评估",
    "auxiliary_exam": "辅助检查",
    "admission_diagnosis": "入院诊断"
  }},
  "draft_record": "按【主诉】【现病史】【既往史】【个人史】【婚育史】【月经史】【家族史】【专项评估】【体格检查】【辅助检查】【入院诊断】输出的入院记录草稿"
}}

要求：
- 只基于对话内容提炼，不得虚构
- 未提及字段输出空字符串
- 尽量区分 doctor / patient / uncertain 三类说话人；无法确定时标 uncertain
- 若未提及明确评分，不要编造数值
- 输出语言规范、条理清晰，适合住院病历整理"""


RECORD_TYPE_MAP = {
    "outpatient": "门诊病历",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
    "course_record": "日常病程记录",
    "senior_round": "上级医师查房记录",
    "discharge_record": "出院记录",
}

# ── 门诊病历生成 ──────────────────────────────────────────
OUTPATIENT_GENERATE_PROMPT = """你是一名专业的临床病历书写助手。根据以下问诊信息，按照《浙江省中医门、急诊病历评分标准》生成规范的中医{visit_nature}病历草稿。

患者信息：姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}
就诊类型：{visit_type_label}　就诊性质：{visit_nature}
就诊时间：{visit_time}　病发时间：{onset_time}

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查（一般体征）：{physical_exam}
辅助检查（真实数据，若有则原样写入，不得编造）：{auxiliary_exam}

中医四诊：
  望诊：{tcm_inspection}
  闻诊：{tcm_auscultation}
  舌象：{tongue_coating}
  脉象：{pulse_condition}

诊断信息（医生录入）：
  西医诊断：{western_diagnosis}
  中医疾病诊断：{tcm_disease_diagnosis}
  中医证候诊断：{tcm_syndrome_diagnosis}
  初步印象（补充）：{initial_impression}

治疗意见（医生录入）：
  治则治法：{treatment_method}
  处理意见：{treatment_plan}
  复诊建议：{followup_advice}
  注意事项：{precautions}
{emergency_section}
请直接输出病历文本（不要JSON），第一行必须按如下格式输出就诊信息行：
就诊时间：{visit_time}　病发时间：{onset_time}

【主诉】
（规范化主诉，主要症状/体征+持续时间，20字以内，原则上不用诊断名称；复诊可用诊断名称代替）

【现病史】
（口语转书面医学语言，包含：①本次起病的主要症状、体征及持续时间；②发病以来的主要诊治经过及结果；{revisit_note}④一般情况：饮食、精神、睡眠、二便）

【既往史】
（重要既往病史、传染病史、手术史、家族史、长期用药史；育龄期女性必须记录月经史及生育史）

【过敏史】
（食物/药物过敏史，无则写"否认药物及食物过敏史"）

【个人史】
（个人史及生活习惯）

【体格检查】
（必须包含中医四诊内容：
望诊：直接使用医生录入的望诊内容；若字段为空则写"[未填写，需补充]"，不得自行编写
闻诊：直接使用医生录入的闻诊内容；若字段为空则写"[未填写，需补充]"，不得自行编写
切诊·舌象：直接照抄医生录入的舌象内容；若字段为空则写"[未填写，需补充]"
切诊·脉象：直接照抄医生录入的脉象内容；若字段为空则写"[未填写，需补充]"
其余阳性体征：原样整理医生填写的体格检查内容）

【辅助检查】
（若有真实检查数据则如实写入；若无则写"暂无"，不得编造数值）

【诊断】
中医诊断：严格照抄医生录入的中医疾病诊断和证候诊断，格式：疾病名 — 证候名；若字段为空则写"[未填写，需补充]"，绝对不得自行推断或补全
西医诊断：严格照抄医生录入的西医诊断；若字段为空则写"[未填写，需补充]"

【治疗意见及措施】
治则治法：严格照抄医生录入的治则治法；若字段为空则写"[未填写，需补充]"，不得根据诊断自行推断
处理意见：严格照抄医生录入的处理意见；若字段为空则写"[未填写，需补充]"
复诊建议：严格照抄医生录入的复诊建议；若字段为空则写"[未填写，需补充]"
{precautions_section}
{emergency_record_section}
【核心要求】
1. 诊断、治则治法、舌象、脉象、中医证候——这五项必须严格使用医生录入的原文，禁止根据症状自行推断或补全
2. 若以上任一字段为空，直接输出"[未填写，需补充]"，不得写任何推测性内容（如"待明确""根据症状推断"等）
3. 禁止编造未提及的症状、体征或诊断
4. 使用规范中医及西医术语，时间线清晰，符合医疗文书规范"""


# ── 入院记录生成（依据浙江省2021版标准，含全部8个评分项）──────────
ADMISSION_NOTE_PROMPT = """你是临床病历书写专家。根据以下问诊信息，严格按照《浙江省住院病历质量检查评分表（2021版）》生成规范的入院记录。

患者基本信息：
姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史/用药史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
辅助检查（入院前）：{auxiliary_exam}
入院诊断：{initial_impression}
专项评估数据：{assessment_info}

请直接输出入院记录全文（不要JSON），严格包含以下所有章节：

【主诉】
（简明扼要，能导出第一诊断，症状+持续时间，20字以内，原则不用诊断名称）

【现病史】
（必须包含以下5个要素：
1. 发病时间、地点、起病缓急及可能原因；
2. 主要症状的部位、性质、持续时间、程度、演变过程及伴随症状；
3. 入院前诊治经过及效果（检查项目、用药情况）；
4. 发病以来一般情况（饮食、精神、睡眠、大小便）；
5. 其他需治疗的疾病情况）

【既往史】
（包含：一般健康情况；心脑血管、肺、肝、肾、内分泌系统重要疾病史；
手术史、外伤史、传染病史、输血史、预防接种史、用药史；
食物/药物过敏史——此项缺失按规定扣2分，必须填写）

【个人史】
（出生地及长期居留地、生活习惯及嗜好、职业与工作条件、
毒物/粉尘/放射性物质接触史、冶游史）

【婚育史】
（婚姻状况、结婚年龄、配偶及子女健康状况）

【月经史】（仅女性患者填写，男性患者此章节不得出现）
（初潮年龄、行经期天数/间隔天数、末次月经时间或闭经年龄、月经量、痛经及生育情况）

【家族史】
（父母、兄弟、姐妹健康状况，有无遗传倾向疾病）

【专项评估】
（依据评分标准，以下7项必须评估，缺1项扣1分：
· 当前用药：……
· 疼痛评估（NRS评分）：……
· 康复需求：……
· 心理状态：……
· 营养风险：……
· VTE风险：……
· 宗教信仰/饮食禁忌：……）

【体格检查】
（按以下顺序逐系统书写，缺少任一系统将影响评分：
T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg；
一般情况：发育、营养、神志、体位、面容、步态；
皮肤黏膜：色泽、皮疹、出血点、水肿、黄染；
全身浅表淋巴结：颈部、腋窝、腹股沟等主要部位；
头颈部：头颅、眼耳鼻口腔、颈软/气管/甲状腺/颈静脉；
胸部（肺）：胸廓、叩诊、呼吸音、啰音；
胸部（心脏）：心率、心律、心音、杂音；
腹部：腹软/硬、肝脾、压痛/反跳痛、肠鸣音；
脊柱四肢：形态、关节活动、肌力肌张力、有无水肿；
神经系统：生理反射、病理反射；
专科检查：含鉴别诊断相关体征，肿瘤患者须记录相关区域淋巴结）

【辅助检查（入院前）】
（记录与本次疾病相关的主要检查及结果；
他院检查须注明机构名称和检查时间）

【入院诊断】
（规范中文诊断术语，主要诊断放首位，排序合理，诊断全面）

要求：书面化医学语言，内容与问诊信息一致，禁止编造未提及内容。"""


# ── 首次病程记录生成（入院8小时内完成，依据2021版标准）──────────
FIRST_COURSE_PROMPT = """你是临床病历书写专家。根据以下问诊信息，生成规范的首次病程记录。
依据《浙江省住院病历质量检查评分表（2021版）》：首次病程记录须在入院8小时内完成。

患者：{patient_name}，{patient_gender}，{patient_age}岁

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史/过敏史：{past_history} / {allergy_history}
体格检查：{physical_exam}
个人史及专项评估：{personal_history}
入院诊断：{initial_impression}

请直接输出首次病程记录全文（不要JSON）：

首次病程记录
（书写时间：入院后__小时内完成）

【病例特点】
（对病史、体格检查和辅助检查进行全面分析、归纳，写出本病例特点——禁止直接复制现病史）

【拟诊讨论】
（根据病例特点，逐项分析诊断依据：
1. 主要诊断依据：……
2. 鉴别诊断（至少列举2个需要鉴别的疾病，说明鉴别要点）：……）

【诊疗计划】
（提出具体的检查及治疗措施，包括：
1. 进一步完善的辅助检查：……
2. 治疗方案：……
3. 病情观察要点：……）

要求：病例特点必须是归纳总结，不得照抄现病史；鉴别诊断需针对具体病情展开分析。"""


# ── 日常病程记录生成 ──────────────────────────────────────
COURSE_RECORD_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的日常病程记录。
依据标准：病情稳定至少每3天记录1次，病重至少每2天1次，病危每天至少1次。

患者：{patient_name}，{patient_gender}，{patient_age}岁
主诉：{chief_complaint}
入院诊断：{initial_impression}
体格检查基线：{physical_exam}
个人史/评估信息：{personal_history}
既往用药/过敏：{past_history} / {allergy_history}

请直接输出日常病程记录（不要JSON）：

____年__月__日 __:__ 病程记录

患者病情记录：（记录患者当前主诉、症状变化）

查体：（记录当日体征，T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg；专科体征变化）

辅助检查结果回报：（记录最新化验/检查结果及分析，异常结果须有处理记录）

病情分析：（分析病情演变、当前诊断是否需修正或补充）

诊疗措施及调整：（记录当日医嘱调整情况及依据）

注意事项：（下一步观察要点）

记录医师：____

要求：内容具体，病情变化有分析，重要诊疗措施调整须记录依据。"""


# ── 上级医师查房记录生成 ──────────────────────────────────
SENIOR_ROUND_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的上级医师查房记录。
依据标准：主治以上医师首次查房须在入院48小时内完成；每周至少3次查房记录；
每周至少2次副高以上医师查房记录，危重患者必须有查房记录。

患者：{patient_name}，{patient_gender}，{patient_age}岁
主诉：{chief_complaint}
入院诊断：{initial_impression}
现病史要点：{history_present_illness}
体格检查：{physical_exam}
既往史/过敏史：{past_history} / {allergy_history}

请直接输出上级医师查房记录（不要JSON）：

____年__月__日 __:__ 上级医师查房记录

查房医师：____（主治/副主任/主任医师）职称：____

患者病史补充：（查房医师对病史、查体有无补充及修正）

病情分析：（上级医师对病情的分析判断，包括：
1. 目前诊断是否成立，依据是否充分；
2. 鉴别诊断意见；
3. 病情评估及预后判断）

诊疗意见：（具体的检查和治疗意见，包括：
1. 需要完善的检查；
2. 治疗方案调整意见；
3. 注意事项及观察要点）

查房医师签名：____

要求：必须体现上级医师的分析意见，内容具体，不能流于形式。"""


# ── 出院记录生成 ──────────────────────────────────────────
DISCHARGE_RECORD_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的出院记录。
依据标准：出院记录须在患者出院后24小时内完成，内容必须包含规定项目。

患者：{patient_name}，{patient_gender}，{patient_age}岁
主诉：{chief_complaint}
入院诊断：{initial_impression}
现病史要点：{history_present_illness}
体格检查基线：{physical_exam}
专项评估信息：{personal_history}
既往史/过敏史：{past_history} / {allergy_history}

请直接输出出院记录（不要JSON）：

出院记录

【主诉】
（与入院记录一致）

【入院情况】
（患者入院时的主要症状、体征及辅助检查结果）

【入院诊断】
（入院时的初步诊断）

【诊疗经过】
（住院期间完成的主要检查、确诊过程、治疗方案及效果，
包括用药情况、手术情况（如有）、病情变化及处理经过）

【出院情况】
（出院时患者症状、体征改善情况，出院时一般状态）

【出院诊断】
（最终诊断，规范中文术语，主要诊断放首位）

【出院医嘱】
（具体详细的出院注意事项，包括：
1. 带药医嘱（药名、剂量、用法、疗程）；
2. 饮食及生活注意事项；
3. 随访时间及复查项目；
4. 如有异常及时就医的指征）

签名医师（主治及以上）：____

要求：出院医嘱必须具体，不能笼统；诊疗经过须与住院记录一致。"""

POLISH_PROMPT = """你是临床病历规范化专家。请对以下病历内容进行润色：
1. 口语转书面医学语言
2. 消除重复内容
3. 优化时间顺序
4. 保持医学术语准确性
5. 禁止添加原文未提及的内容

原始病历：
{content}

请直接输出润色后的病历文本，格式与原文保持一致。"""


async def _stream_text(prompt: str, task_type: str = "generate", model_options: Optional[dict] = None):
    """流式输出文本，完成后记录 token 用量到独立 DB 会话"""
    yield "data: {\"type\":\"start\"}\n\n"
    messages = [{"role": "user", "content": prompt}]
    options = model_options or {}
    try:
        async for chunk in llm_client.stream(
            messages,
            temperature=options.get("temperature", 0.3),
            max_tokens=options.get("max_tokens", 4096),
            model_name=options.get("model_name"),
        ):
            payload = json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
    except Exception as e:
        logger.error(f"_stream_text LLM error: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    yield f"data: {{\"type\":\"done\"}}\n\n"
    # Log token usage after stream completes (uses its own DB session)
    usage = llm_client._last_usage
    await _log_task(
        task_type,
        token_input=usage.prompt_tokens if usage else 0,
        token_output=usage.completion_tokens if usage else 0,
    )


@router.post("/voice-records/upload")
async def upload_voice_record(
    file: UploadFile = File(...),
    encounter_id: Optional[str] = Form(None),
    visit_type: Optional[str] = Form("outpatient"),
    transcript: Optional[str] = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 按接诊 ID 分目录存储，便于归档和清理
    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    rel_dir = Path("voice_records") / (encounter_id or "no_encounter")
    (uploads_root / rel_dir).mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "recording.webm").suffix or ".webm"
    file_name = f"{generate_uuid()}{suffix}"
    rel_path = rel_dir / file_name          # 存相对路径，跨机器不失效
    (uploads_root / rel_path).write_bytes(await file.read())
    audio_bytes = (uploads_root / rel_path).read_bytes()

    # 浏览器端 SpeechRecognition 实时转写优先；若为空则用 Qwen-Audio 兜底
    asr_transcript = transcript or ""
    from app.config import settings as _settings
    if _settings.aliyun_api_key and not asr_transcript.strip():
        try:
            import httpx as _httpx
            audio_b64 = base64.b64encode(audio_bytes).decode()
            suffix = Path(file.filename or "recording.webm").suffix.lstrip(".") or "webm"
            # m4a 需要用 mp4 MIME 类型，API 不识别 audio/m4a
            _mime_map = {"m4a": "mp4", "mp3": "mpeg"}
            audio_mime = f"audio/{_mime_map.get(suffix, suffix)}"
            async with _httpx.AsyncClient(timeout=90) as _client:
                _resp = await _client.post(
                    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                    headers={"Authorization": f"Bearer {_settings.aliyun_api_key}", "Content-Type": "application/json"},
                    json={
                        "model": "qwen-audio-turbo",
                        "input": {
                            "messages": [{"role": "user", "content": [
                                {"audio": f"data:{audio_mime};base64,{audio_b64}"},
                                {"text": "请转录这段中文医患录音，只输出转录文字，不添加任何解释或标注。"},
                            ]}]
                        },
                    },
                )
            if _resp.status_code == 200:
                _data = _resp.json()
                _content = _data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", [])
                if isinstance(_content, list):
                    asr_transcript = " ".join(
                        item["text"] for item in _content if isinstance(item, dict) and "text" in item
                    ).strip()
                elif isinstance(_content, str):
                    asr_transcript = _content.strip()
            else:
                logger.warning("Qwen-Audio 转写失败: HTTP %s — %s", _resp.status_code, _resp.text[:200])
        except Exception as _e:
            logger.warning("Qwen-Audio 转写异常: %s", _e)

    record = VoiceRecord(
        encounter_id=encounter_id,
        doctor_id=current_user.id,
        visit_type=visit_type or "outpatient",
        raw_transcript=asr_transcript,
        audio_file_path=str(rel_path),      # 存相对路径
        mime_type=file.content_type or "application/octet-stream",
        status="uploaded",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {
        "voice_record_id": record.id,
        "status": record.status,
        "has_audio": True,
        "transcript": asr_transcript,
    }


@router.get("/voice-records/{voice_record_id}/audio")
async def get_voice_audio(
    voice_record_id: str,
    token: str = Query(..., description="JWT token for auth"),
    db: AsyncSession = Depends(get_db),
):
    """播放音频文件，通过 query param 传 token（audio 标签不支持自定义 header）"""
    from app.core.security import settings
    from jose import JWTError, jwt
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = payload.get("sub")
        role = payload.get("role", "doctor")
        if not user_id:
            raise HTTPException(status_code=401, detail="无效 token")
    except JWTError:
        raise HTTPException(status_code=401, detail="无效 token")

    query = select(VoiceRecord).where(VoiceRecord.id == voice_record_id)
    if role not in ("admin", "super_admin"):
        query = query.where(VoiceRecord.doctor_id == user_id)
    result = await db.execute(query)
    record = result.scalar_one_or_none()
    if not record or not record.audio_file_path:
        raise HTTPException(status_code=404, detail="音频文件不存在")

    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    audio_path = uploads_root / record.audio_file_path   # 相对路径拼成绝对路径
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频文件已被清理")

    mime = record.mime_type or "audio/webm"
    return FileResponse(audio_path, media_type=mime, filename=audio_path.name)


@router.delete("/voice-records/{voice_record_id}")
async def delete_voice_record(
    voice_record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除语音记录及音频文件（仅本人可删除）"""
    result = await db.execute(
        select(VoiceRecord).where(
            VoiceRecord.id == voice_record_id,
            VoiceRecord.doctor_id == current_user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="语音记录不存在")

    # 删除磁盘上的音频文件
    if record.audio_file_path:
        uploads_root = Path(__file__).resolve().parents[3] / "uploads"
        audio_path = uploads_root / record.audio_file_path
        if audio_path.exists():
            audio_path.unlink()

    await db.delete(record)
    await db.commit()
    return {"success": True}


@router.post("/voice-structure")
async def voice_structure(
    req: VoiceStructureRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    transcript = (req.transcript or "").strip()
    if not transcript:
        return {"transcript_summary": "", "inquiry": {}, "draft_record": ""}

    voice_record = None
    if req.transcript_id:
        voice_result = await db.execute(
            select(VoiceRecord).where(VoiceRecord.id == req.transcript_id, VoiceRecord.doctor_id == current_user.id)
        )
        voice_record = voice_result.scalar_one_or_none()
        if not voice_record:
            raise HTTPException(status_code=404, detail="语音记录不存在")

    visit_type = req.visit_type or "outpatient"
    prompt_template = VOICE_STRUCTURE_PROMPT_INPATIENT if visit_type == "inpatient" else VOICE_STRUCTURE_PROMPT_OUTPATIENT
    model_options = await _get_model_options(db, "generate")
    prompt = prompt_template.format(
        patient_name=req.patient_name or "未提供",
        patient_gender=req.patient_gender or "未提供",
        patient_age=req.patient_age or "未提供",
        existing_inquiry=json.dumps(req.existing_inquiry or {}, ensure_ascii=False),
        transcript=transcript,
    )

    messages = [
        {
            "role": "system",
            "content": "你是临床病历整理助手，只输出合法 JSON，禁止输出解释说明。",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task(
            "generate",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )
        speaker_dialogue = result.get("speaker_dialogue", [])
        if voice_record:
            voice_record.raw_transcript = transcript
            voice_record.transcript_summary = result.get("transcript_summary", "")
            voice_record.speaker_dialogue = json.dumps(speaker_dialogue, ensure_ascii=False)
            voice_record.structured_inquiry = json.dumps(result.get("inquiry", {}), ensure_ascii=False)
            voice_record.draft_record = result.get("draft_record", "")
            voice_record.status = "structured"
            await db.commit()
        return {
            "transcript_id": voice_record.id if voice_record else req.transcript_id,
            "transcript_summary": result.get("transcript_summary", ""),
            "speaker_dialogue": speaker_dialogue,
            "inquiry": result.get("inquiry", {}),
            "draft_record": result.get("draft_record", ""),
        }
    except Exception as e:
        logger.error(f"analyze_voice failed: {e}", exc_info=True)
        return {"transcript_id": req.transcript_id, "transcript_summary": "", "speaker_dialogue": [], "inquiry": {}, "draft_record": ""}


@router.post("/quick-generate")
async def quick_generate(
    req: QuickGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    record_type = req.record_type or "outpatient"
    # Check DB for admin-configured prompt override (scene = record_type, e.g. "admission_note")
    db_prompt = await _get_active_prompt(db, record_type)
    template = db_prompt or _PROMPT_MAP.get(record_type, OUTPATIENT_GENERATE_PROMPT)
    model_options = await _get_model_options(db, "generate")
    # Build assessment_info string from inpatient-specific fields
    pain_score = req.pain_assessment or "0"
    assessment_parts = [
        f"病史陈述者：{req.history_informant}" if req.history_informant else "",
        f"婚育史：{req.marital_history}" if req.marital_history else "",
        f"月经史：{req.menstrual_history}" if req.menstrual_history else "",
        f"家族史：{req.family_history}" if req.family_history else "",
        f"当前用药：{req.current_medications}" if req.current_medications else "",
        f"疼痛评分（NRS）：{pain_score}分",
        f"VTE风险：{req.vte_risk}" if req.vte_risk else "",
        f"营养评估：{req.nutrition_assessment}" if req.nutrition_assessment else "",
        f"心理评估：{req.psychology_assessment}" if req.psychology_assessment else "",
        f"康复需求：{req.rehabilitation_assessment}" if req.rehabilitation_assessment else "",
        f"宗教信仰/饮食禁忌：{req.religion_belief}" if req.religion_belief else "",
    ]
    assessment_info = "\n".join(p for p in assessment_parts if p) or "未提供"
    visit_type_label = {"outpatient": "门诊", "emergency": "急诊", "inpatient": "住院"}.get(req.visit_type_detail or "outpatient", "门诊")
    visit_nature = "初诊" if req.is_first_visit else "复诊"
    revisit_note = "③复诊患者需记录治疗后症状改变情况；" if not req.is_first_visit else ""
    is_emergency = (req.visit_type_detail or "outpatient") == "emergency"
    emergency_section = (
        f"\n急诊附加：\n  急诊生命体征：{req.physical_exam or '见体格检查'}\n  留观记录：{req.observation_notes or '未提供'}\n  患者去向：{req.patient_disposition or '未提供'}"
        if is_emergency else ""
    )
    emergency_record_section = (
        "\n【急诊留观记录】\n（记录留观期间病情变化、处理措施及患者去向）"
        if is_emergency else ""
    )
    precautions_val = req.precautions or ""
    precautions_section = f"注意事项：{precautions_val}" if precautions_val else ""
    fmt_kwargs: dict = dict(
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        patient_name=req.patient_name or "患者",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        assessment_info=assessment_info,
        visit_type_label=visit_type_label,
        visit_nature=visit_nature,
        revisit_note=revisit_note,
        tcm_inspection=req.tcm_inspection or "未提供",
        tcm_auscultation=req.tcm_auscultation or "未提供",
        tongue_coating=req.tongue_coating or "未提供",
        pulse_condition=req.pulse_condition or "未提供",
        western_diagnosis=req.western_diagnosis or req.initial_impression or "待明确",
        tcm_disease_diagnosis=req.tcm_disease_diagnosis or "待明确",
        tcm_syndrome_diagnosis=req.tcm_syndrome_diagnosis or "待明确",
        treatment_method=req.treatment_method or "未提供",
        treatment_plan=req.treatment_plan or "未提供",
        followup_advice=req.followup_advice or "未提供",
        precautions=precautions_val or "未提供",
        emergency_section=emergency_section,
        emergency_record_section=emergency_record_section,
        precautions_section=precautions_section,
        visit_time=req.visit_time or "未记录",
        onset_time=req.onset_time or "未记录",
    )
    if "{auxiliary_exam}" in template:
        fmt_kwargs["auxiliary_exam"] = req.auxiliary_exam or "未提供"
    try:
        prompt = template.format(**fmt_kwargs)
    except KeyError:
        # 如果模板不含新字段（如自定义 prompt），回退到旧格式
        prompt = template.format(
            chief_complaint=fmt_kwargs["chief_complaint"],
            history_present_illness=fmt_kwargs["history_present_illness"],
            past_history=fmt_kwargs["past_history"],
            allergy_history=fmt_kwargs["allergy_history"],
            personal_history=fmt_kwargs["personal_history"],
            physical_exam=fmt_kwargs["physical_exam"],
            initial_impression=fmt_kwargs["initial_impression"],
            patient_name=fmt_kwargs["patient_name"],
            patient_gender=fmt_kwargs["patient_gender"],
            patient_age=fmt_kwargs["patient_age"],
            assessment_info=fmt_kwargs["assessment_info"],
            auxiliary_exam=fmt_kwargs.get("auxiliary_exam", "未提供"),
        )
    return StreamingResponse(_stream_text(prompt, task_type="generate", model_options=model_options), media_type="text/event-stream")


class ContinueRequest(BaseModel):
    current_content: str = ""
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    personal_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""
    record_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""


CONTINUE_PROMPT = """你是临床病历书写助手。医生已经写了部分病历，请根据问诊信息续写未完成的部分。

患者信息：姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}
病历类型：{record_type}

【性别约束—必须严格遵守】
- 若患者性别为男性（male/男），严禁出现月经史、末次月经、生育史、妇科等女性特有内容
- 若患者性别为女性（female/女），月经史/生育史为必填项
- 若性别未知，不得编造任何性别特异性内容

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

已有病历内容：
{current_content}

请分析已有内容，找出缺失的部分，只输出需要补充的内容（不要重复已有内容）。
输出格式：直接输出补充的病历段落，格式与已有内容保持一致。
禁止编造未提及的症状或信息。"""


class SupplementRequest(BaseModel):
    current_content: str = ""
    qc_issues: Optional[list] = []
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""
    record_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""


SUPPLEMENT_PROMPT = """你是临床病历书写专家。根据质控发现的缺失项，对病历进行修正，输出完整的修正后病历。

患者信息：姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}
病历类型：{record_type}

【核心原则—必须严格遵守】
1. 当前病历内容是事实基准——病历中已有的所有信息（症状、体征、诊断、检验值等）必须原样保留，不得修改、替换或与之矛盾
2. 若当前病历中已记录某项内容，禁止用不同的值覆盖（如已有体温36.5℃，不得改为37.2℃）
3. 辅助检查等具体数值必须与病历现有内容保持一致，不得自行编造

【性别约束—必须严格遵守】
- 若患者性别为男性（male/男），严禁出现月经史、末次月经、生育史、妇科等女性特有内容
- 若患者性别为女性（female/女），月经史/生育史为必填项
- 若性别未知，不得编造任何性别特异性内容

当前病历内容（基准，必须保留所有已有信息）：
{current_content}

问诊信息（仅用于补充病历中尚未记录的内容）：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
体格检查：{physical_exam}
辅助检查：{auxiliary_exam}
初步印象：{initial_impression}

质控发现的问题（需要修复的内容）：
{qc_issues}

请输出**完整的修正后病历**（保留已有内容，仅补充质控发现的缺失章节）。
要求：
1. 已有内容原样保留，只新增缺失的章节或字段
2. 新增内容必须与已有内容（症状、体征、诊断等）保持一致，不得相悖
3. 输出完整病历正文，不加说明前缀"""


@router.post("/quick-supplement")
async def quick_supplement(
    req: SupplementRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not req.qc_issues:
        return StreamingResponse(
            iter(["data: {\"type\":\"done\"}\n\n"]),
            media_type="text/event-stream"
        )
    record_type_key = cast(str, req.record_type or "outpatient")
    record_type = RECORD_TYPE_MAP.get(record_type_key, "门诊病历")
    issues_text = "\n".join(
        f"- [{item.get('risk_level','').upper()}] {item.get('issue_description', '')}（建议：{item.get('suggestion', '')}）"
        for item in req.qc_issues
    )
    prompt = SUPPLEMENT_PROMPT.format(
        record_type=record_type,
        patient_name=req.patient_name or "未知",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        auxiliary_exam=req.auxiliary_exam or "无",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content[:1500] if req.current_content else "（空）",
        qc_issues=issues_text,
    )
    model_options = await _get_model_options(db, "generate")
    return StreamingResponse(_stream_text(prompt, task_type="generate", model_options=model_options), media_type="text/event-stream")


@router.post("/quick-continue")
async def quick_continue(
    req: ContinueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    record_type_key = cast(str, req.record_type or "outpatient")
    record_type = RECORD_TYPE_MAP.get(record_type_key, "门诊病历")
    prompt = CONTINUE_PROMPT.format(
        record_type=record_type,
        patient_name=req.patient_name or "未知",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content or "（暂无内容）",
    )
    model_options = await _get_model_options(db, "generate")
    return StreamingResponse(_stream_text(prompt, task_type="generate", model_options=model_options), media_type="text/event-stream")


class PolishRequest(BaseModel):
    content: str = ""


class InquirySuggestionsRequest(BaseModel):
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    initial_impression: Optional[str] = ""


@router.post("/quick-polish")
async def quick_polish(
    req: PolishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_prompt = await _get_active_prompt(db, "polish")
    template = db_prompt or POLISH_PROMPT
    model_options = await _get_model_options(db, "polish")
    prompt = _safe_format(template, content=req.content)
    return StreamingResponse(_stream_text(prompt, task_type="polish", model_options=model_options), media_type="text/event-stream")


INQUIRY_SUGGESTIONS_PROMPT = """你是一名临床医生，请严格按照以下步骤为患者生成追问问题，必须输出完整JSON。

患者信息：
主诉：{chief_complaint}
现病史：{history}
诊断：{initial_impression}

第一步：分析已知信息（在 known_info 字段中列出）
第二步：判断病情类型（在 condition_type 字段中填写）
第三步：根据病情类型生成专项追问（在 suggestions 中输出，严禁重复已知信息）

病情类型与对应追问方向（必须按此执行）：
- 皮肤外伤（擦伤/裂伤/挫伤）→ 受伤经过、伤口污染程度、有无异物、破伤风接种史、有无皮肤过敏/糖尿病影响愈合
- 骨关节外伤（骨折/扭伤/脱位）→ 受伤机制、能否负重行走、有无麻木感、末梢血运情况、X线是否已拍
- 内科急症（胸痛/腹痛/头痛等）→ 起病时间地点、疼痛性质、加重缓解因素、伴随症状、既往类似发作
- 感染（发热/炎症）→ 体温峰值、热型、感染接触史、近期用药、疫苗接种情况
- 慢性病急性加重 → 基础疾病控制情况、近期用药规律性、急性诱因

输出格式（必须完整填写所有字段）：
{{
  "known_info": ["已知信息1（如：部位=腿部外侧）", "已知信息2（如：类型=擦伤）"],
  "condition_type": "病情类型（如：皮肤外伤-擦伤）",
  "suggestions": [
    {{
      "text": "问题（简洁，不超过20字）",
      "priority": "high/medium/low",
      "is_red_flag": true/false,
      "category": "受伤机制/伤口情况/危险信号/功能评估/既往信息",
      "option_type": "single或multi",
      "options": ["选项1", "选项2", "选项3"]
    }}
  ]
}}

option_type判断规则（必须逐题判断，不能统一填同一个值）：
- single：该题的选项之间逻辑上互斥，患者只能属于其中一种情况（如评分区间、程度分级、单一原因、时间节点等）
- multi：该题的选项可以同时成立，患者可能符合多个（如伴随症状、过敏药物、慢性病史等）
- 判断依据是选项语义，而非题目类型；如疼痛评分区间→single，伴随症状→multi

硬性规则：
- known_info 中列出的内容，绝对不能出现在 suggestions 的问题里
- suggestions 必须4-6条，每条 options 必须2-4个，与该病情直接相关
- 禁止出现"您的主要症状是什么""症状持续多久了"这类对已明确诊断的患者毫无意义的通用问题
- options中禁止出现"有"/"无"、"是"/"否"、"正常"/"异常"等互斥对立选项；选项均为正向具体描述，患者不勾选即代表阴性"""


@router.post("/inquiry-suggestions")
async def inquiry_suggestions(
    req: InquirySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_prompt = await _get_active_prompt(db, "inquiry")
    template = db_prompt or INQUIRY_SUGGESTIONS_PROMPT
    prompt = _safe_format(
        template,
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "暂未填写",
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是临床问诊专家，只输出JSON对象，包含known_info、condition_type、suggestions三个字段。"
                "known_info：列出已知信息要点的字符串数组。"
                "condition_type：病情类型字符串。"
                "suggestions：追问问题数组，每项含text、priority、is_red_flag、category、options，"
                "其中text不得重复known_info中已有的内容，options为2-4个专业具体选项。"
                "对于擦伤/外伤等已明确诊断的病例，禁止生成询问症状类型、持续时间等基础问题。"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        model_options = await _get_model_options(db, "inquiry")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task("inquiry",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception as e:
        logger.error(f"inquiry_suggestions failed: {e}", exc_info=True)
        return {"suggestions": []}


# ─── 检查建议 ──────────────────────────────────────────────
class ExamSuggestionsRequest(BaseModel):
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    initial_impression: Optional[str] = ""
    department: Optional[str] = ""


EXAM_SUGGESTIONS_PROMPT = """你是临床检查建议助手。根据患者信息，提供合理的辅助检查建议。

主诉：{chief_complaint}
现病史：{history_present_illness}
初步印象：{initial_impression}
科室：{department}

【重要限制】本院现有检查设备如下，只能从以下范围内推荐，不得推荐不在列表中的检查：
影像类：CT、核磁（MRI）、DR（数字X光）、B超（超声）、骨密度仪
心电类：心电图、动态心电图（Holter）、动态血压监测
内镜类：胃镜、肠镜
呼气试验：碳14呼气试验（幽门螺杆菌检测）
化验类：血常规、尿常规、便常规、肝功能、肾功能、血糖、血脂、电解质、凝血功能、甲状腺功能、肿瘤标志物、感染指标（CRP/PCT/ESR）、心肌酶、BNP、D-二聚体、血型、传染病筛查及其他常规化验

请输出JSON格式，3-6条建议：
{{
  "suggestions": [
    {{
      "exam_name": "检查名称（必须在上述范围内）",
      "category": "basic",
      "reason": "推荐理由（结合患者具体症状说明）"
    }}
  ]
}}

category说明：basic（基础必查）/ differential（鉴别诊断）/ high_risk（高风险补充）
要求：仅做建议，不替代医生决策，不编造未提及的信息，严格只推荐本院现有设备能完成的检查。"""


@router.post("/exam-suggestions")
async def exam_suggestions(
    req: ExamSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_prompt = await _get_active_prompt(db, "exam")
    template = db_prompt or EXAM_SUGGESTIONS_PROMPT
    prompt = _safe_format(
        template,
        chief_complaint=req.chief_complaint or "未填写",
        history_present_illness=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        department=req.department or "未知",
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        model_options = await _get_model_options(db, "exam")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task("exam",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception as e:
        logger.error(f"exam_suggestions failed: {e}", exc_info=True)
        return {"suggestions": []}


# ─── AI 质控 ──────────────────────────────────────────────
class QuickQCRequest(BaseModel):
    content: str = ""
    record_type: Optional[str] = "outpatient"
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    encounter_id: Optional[str] = None
    # 住院病历专项评估字段（用于规则引擎完整性检查）
    marital_history: Optional[str] = ""
    family_history: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    current_medications: Optional[str] = ""
    religion_belief: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    admission_diagnosis: Optional[str] = ""
    # 门诊中医四诊及治疗字段（用于中医强制规则检查）
    tcm_inspection: Optional[str] = ""
    tcm_auscultation: Optional[str] = ""
    tongue_coating: Optional[str] = ""
    pulse_condition: Optional[str] = ""
    western_diagnosis: Optional[str] = ""
    tcm_disease_diagnosis: Optional[str] = ""
    tcm_syndrome_diagnosis: Optional[str] = ""
    treatment_method: Optional[str] = ""
    treatment_plan: Optional[str] = ""
    followup_advice: Optional[str] = ""
    precautions: Optional[str] = ""
    # 就诊性质（复诊需检查治疗后症状变化）
    is_first_visit: Optional[bool] = True
    # 时间（病发时间必填检查）
    onset_time: Optional[str] = ""


QC_PROMPT = """你是病历质控专家，依据《浙江省住院病历质量检查评分表（2021版）》对病历进行全面质控评分。

病历类型：{record_type}
病历内容：
{content}

请严格按照以下评分标准逐项检查，输出JSON格式：
{{
  "issues": [
    {{
      "risk_level": "high/medium/low",
      "field_name": "字段名称",
      "issue_description": "问题描述（具体指出哪里有问题）",
      "suggestion": "修改建议",
      "score_impact": "影响分值说明"
    }}
  ],
  "summary": "总体评价（1-2句话，描述主要问题和改进方向，不要包含分数估计）",
  "pass": true/false
}}

【检查标准（依据浙江省2021版评分表，总分100分，90分以上甲级，80-89乙级，80分以下丙级）】
【特别要求】正式出具病历要求质控达到满分100分，任何扣分项均须明确列出。

一、主诉（2分）
- 是否简明扼要，能导出第一诊断
- 原则上不用诊断名称（病理确诊、再入院除外）
- 是否有持续时间描述；是否有近况描述
- 风险：主要症状未写或不能导出第一诊断 → high（扣1分）；持续时间不准确或无近况描述 → medium（各扣0.5分）

二、现病史（6分）
- ① 是否记录发病时间、起病缓急及可能原因
- ② 是否按时间顺序描述主要症状的部位、性质、持续时间、程度、演变及伴随症状
- ③ 是否记录入院前检查、治疗经过及效果
- ④ 是否记录发病以来一般情况（饮食、精神、睡眠、大小便）——此项常被遗漏
- ⑤ 是否记录与本次疾病虽无紧密关系但仍需治疗的其他疾病情况
- ⑥【复诊专项】若为复诊病历，必须记录上次治疗后症状的改变情况（好转/无变化/加重）——缺失直接扣2分（high）
- 风险：①②④缺失 → medium（各扣0.5分）；完全缺失某项 → high；复诊缺治疗后症状变化记录 → high（扣2分）

三、既往史（2分）
- 是否记录心脑血管、肺、肝、肾、内分泌系统重要疾病史
- 是否明确记录食物/药物过敏史——缺失按规定直接扣2分（high）
- 是否记录手术史、外伤史、传染病史、输血史、预防接种史、用药史
- 风险：缺过敏史 → high（扣2分）；缺重要脏器疾病史 → medium（扣0.5分/项）

四、个人史/婚育史/月经史/家族史（3分）
- 是否记录个人史（出生地、生活习惯、职业、毒物/粉尘/放射性物质接触史）
- 是否记录婚育史
- 女性患者是否记录月经史（初潮年龄、行经期/间隔天数、末次月经或闭经年龄、月经量、痛经、生育情况）
- 是否记录家族史（父母、兄弟、姐妹健康状况，有无遗传倾向疾病）
- 风险：完全缺失某项 → high（扣1分/项）；记录不规范 → medium（扣0.5分/项）

五、专项评估（3分）——此项容易漏评，缺1项扣1分
必须评估以下7项，每项缺失扣1分：
- 当前用药评估
- 疼痛评估（NRS评分）
- 康复需求评估
- 心理状态评估
- 营养风险评估
- VTE（静脉血栓栓塞）风险评估
- 宗教信仰/饮食特殊要求
- 风险：缺任一项 → high（扣1分/项）；评估不规范 → medium（扣0.5分/项）

六、体格检查（2分）
- 是否填写完整（生命体征T/P/R/BP）、准确、规范
- 是否记录专科检查及鉴别诊断相关体检内容
- 肿瘤患者或有鉴别诊断意义者是否记录相关区域淋巴结
- 风险：记录与患者实际情况不符 → high（扣1分/项）；缺项或专科检查不全面 → medium（扣0.5分/项）

七、辅助检查（2分）
- 是否记录入院前与本次疾病相关的主要检查及结果
- 他院检查是否注明该机构名称和检查时间
- 风险：缺辅助检查记录 → medium（扣0.5分/项）；他院检查记录不规范 → low

八、诊断（4分）
- 初步诊断是否准确、合理、全面，与病史记录相一致
- 诊断名称是否使用规范中文医学术语（不用非通用中文或英文简称）
- 主要诊断是否放在首位，诊断排序是否合理
- 风险：诊断错误（部位、疾病名称错误）→ high（单项否决，扣10分）；诊断不全面或排序有缺陷 → medium（扣1分/项）

九、首次病程记录（若为首次病程记录类型，6分）
- 病例特点是否归纳全面，禁止直接复制现病史（复制则单项否决）
- 是否有拟诊讨论及鉴别诊断分析
- 诊疗计划是否提出具体检查和治疗措施
- 风险：直接复制现病史 → high（单项否决）；缺鉴别诊断 → high（扣1分）；诊疗计划不具体 → medium

十、书写规范（4分）
- 是否使用书面化医学语言
- 主诉、现病史、既往史逻辑是否一致，时间描述是否清晰
- 是否有内容相互矛盾（严重矛盾为单项否决）
- 是否存在不合理复制现象
- 风险：严重矛盾或不合理复制 → high；表述不规范 → low

【中医病历专项强制检查】（门诊中医病历额外要求）
若病历含有中医诊断、中医治疗、中药处方、针灸等内容，必须逐一检查以下项，缺失直接标记 high：
- 体格检查中是否包含完整舌象（舌质+舌苔，如"舌淡红苔薄白"）——缺失扣2分（high）
- 体格检查中是否包含脉象（如"脉弦细"）——缺失扣2分（high）
- 是否有明确的中医疾病诊断（如"眩晕病"）——缺失扣1分（high）
- 是否有明确的中医证候诊断（如"肝阳上亢证"）——缺失扣2分（high）
- 治疗意见中是否有治则治法（如"平肝潜阳"）——缺失扣1分（high）
- 体格检查是否包含望诊内容（神色形态）——缺失扣0.5分（medium）
- 体格检查是否包含闻诊内容（声音气味）——缺失扣0.5分（medium）
以上任一缺失均须在 issues 中单独列出并标注对应 field_name（tongue_coating / pulse_condition / tcm_disease_diagnosis / tcm_syndrome_diagnosis / treatment_method / tcm_inspection / tcm_auscultation）。

risk_level说明：
- high：单项否决（计10分）或本项扣分≥2分的严重问题
- medium：扣0.5-1分的一般问题
- low：书写不规范等轻微问题（扣0.5分以下）

如病历内容完整规范无任何扣分项，issues为空数组，pass为true（满分100分）。
pass=false 表示存在任何扣分项（未达满分100分）。"""

RECORD_TYPE_LABELS = {
    "outpatient": "门诊病历",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
    "course_record": "日常病程记录",
    "senior_round": "上级医师查房记录",
    "discharge_record": "出院记录",
    "pre_op_summary": "术前小结",
    "op_record": "手术记录",
    "post_op_record": "术后病程记录",
}


# ── 术前小结生成 ──────────────────────────────────────────
PRE_OP_SUMMARY_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的术前小结。
依据标准：术前小结须在手术前完成，经治医师书写，上级医师审签。

患者：{patient_name}，{patient_gender}，{patient_age}岁
主诉：{chief_complaint}
入院诊断：{initial_impression}
现病史要点：{history_present_illness}
体格检查：{physical_exam}
既往史/过敏史：{past_history} / {allergy_history}
专项评估：{personal_history}

请直接输出术前小结（不要JSON）：

术前小结

【病历摘要】
（简述患者姓名、性别、年龄、主诉、入院经过、主要体征及辅助检查结果）

【术前诊断】
（规范中文诊断术语，主要诊断放首位）

【手术指征】
（具体说明手术适应证，说明为何需要手术治疗）

【拟施手术名称及方式】
（具体手术名称及手术方式）

【拟施麻醉方式】
（麻醉方式）

【手术组成员】
术者：____  一助：____  二助：____

【术前准备情况】
（术前检查完善情况、特殊准备情况）

【术中术后预计情况及预防处理措施】
（可能出现的并发症及预防措施）

【上级医师意见】
（上级医师对手术必要性、方案的审核意见）

上级医师签字：____
经治医师签字：____
记录日期：____年__月__日 __时__分

要求：手术指征须具体充分，术中术后注意事项须有针对性。"""


# ── 手术记录生成 ──────────────────────────────────────────
OP_RECORD_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的手术记录模板。
依据标准：手术记录须在手术后24小时内完成，由术者或第一助手书写，术者审签。

患者：{patient_name}，{patient_gender}，{patient_age}岁
术前诊断：{initial_impression}
主诉：{chief_complaint}
既往史/过敏史：{past_history} / {allergy_history}

请直接输出手术记录（不要JSON）：

手术记录

手术日期：____年__月__日
手术开始时间：____时____分
手术结束时间：____时____分
术前诊断：（与术前小结一致）
术后诊断：（手术探查后明确的诊断）
手术名称：（规范手术名称）
手术医师：术者：____  一助：____  二助：____
麻醉方式：____  麻醉医师：____
巡回护士：____  器械护士：____

【手术经过】
1. 麻醉生效后，患者取____体位，常规消毒铺巾；
2. 手术切口部位及长度：____；
3. 逐层切开皮肤、皮下组织，显露____；
4. 手术操作步骤（详细描述主要操作步骤）：……
5. 术中所见：（描述病变性质、大小、位置、与周围组织关系）
6. 止血、冲洗、缝合情况：……
7. 标本处置：（是否送病理检查）
8. 术毕患者情况：清醒/麻醉中，安全返回病房/转入ICU；

【术中情况】
出血量：____ml  输血量：____ml（血型：____）
输液量：____ml  尿量：____ml
特殊情况：（若无填"无特殊情况"）

术者签名：____
记录医师：____
记录日期：____年__月__日

要求：手术经过须详细真实，与病理标本及术前谈话一致。"""


# ── 术后病程记录生成 ──────────────────────────────────────
POST_OP_RECORD_PROMPT = """你是临床病历书写专家。根据以下患者信息，生成规范的术后病程记录。
依据标准：术后即刻记录须在麻醉清醒/返回病房后立即完成；术后24小时内须有主刀医师或主治医师查房记录。

患者：{patient_name}，{patient_gender}，{patient_age}岁
主诉：{chief_complaint}
术前/术后诊断：{initial_impression}
体格检查基线：{physical_exam}
既往史/过敏史：{past_history} / {allergy_history}

请直接输出术后病程记录（不要JSON）：

____年__月__日 __:__  术后病程记录（术后第__天）

查房医师：____（主治/主任医师）

【患者主诉】
（患者当前主诉，如疼痛程度、部位，有无发热、恶心呕吐等不适）

【查体】
T:__℃  P:__次/分  R:__次/分  BP:__/__mmHg
伤口情况：（伤口敷料、渗出、红肿情况）
专科体征：（与手术相关的专科体征）

【辅助检查结果回报】
（术后化验、检查结果及分析，异常结果须有处理说明）

【病情分析及术后恢复情况评估】
（评估术后恢复情况，是否符合预期，有无并发症迹象）

【诊疗措施】
（当前医嘱执行情况、调整情况及依据）
1. 抗感染治疗：……
2. 止痛治疗：……
3. 其他：……

【注意事项及下一步计划】
（下一步观察重点及处理计划）

记录医师：____

要求：术后病程须记录伤口情况，用药须与医嘱一致。"""


_PROMPT_MAP = {
    "outpatient": OUTPATIENT_GENERATE_PROMPT,
    "admission_note": ADMISSION_NOTE_PROMPT,
    "first_course_record": FIRST_COURSE_PROMPT,
    "course_record": COURSE_RECORD_PROMPT,
    "senior_round": SENIOR_ROUND_PROMPT,
    "discharge_record": DISCHARGE_RECORD_PROMPT,
    "pre_op_summary": PRE_OP_SUMMARY_PROMPT,
    "op_record": OP_RECORD_PROMPT,
    "post_op_record": POST_OP_RECORD_PROMPT,
}


def _calc_grade_score(issues: list[dict]) -> tuple[int, str]:
    """
    根据质控问题列表计算甲级评分（满分100分）及病历等级。
    - 高风险（high）: 每项扣3分（单项否决类扣10分）
    - 中风险（medium）: 每项扣1.5分
    - 低风险（low）: 每项扣0.5分
    等级：≥90甲级，75-89乙级，<75丙级
    """
    score = 100.0
    for issue in issues:
        risk = issue.get("risk_level", "low")
        desc = issue.get("issue_description", "")
        # 单项否决（关键错误）
        if "单项否决" in desc or "否决" in desc:
            score -= 10
        elif risk == "high":
            score -= 3
        elif risk == "medium":
            score -= 1.5
        else:
            score -= 0.5
    score = max(0.0, score)
    score_int = int(score)
    if score_int >= 90:
        level = "甲级"
    elif score_int >= 75:
        level = "乙级"
    else:
        level = "丙级"
    return score_int, level


# ─── 诊断建议 ──────────────────────────────────────────────
class DiagnosisSuggestionRequest(BaseModel):
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    inquiry_answers: Optional[list] = []   # [{"question": "...", "answer": "..."}]
    initial_impression: Optional[str] = ""


DIAGNOSIS_SUGGESTION_PROMPT = """你是一名经验丰富的临床医生助手。根据以下问诊信息和追问结果，给出3-5个可能的初步诊断建议。

主诉：{chief_complaint}
现病史：{history}
已有初步印象：{initial_impression}

追问记录：
{inquiry_answers}

请输出JSON格式：
{{
  "diagnoses": [
    {{
      "name": "诊断名称（规范医学术语）",
      "confidence": "high/medium/low",
      "reasoning": "简要说明依据（1-2句话）",
      "next_steps": "建议下一步（检查或处理）"
    }}
  ]
}}

要求：
- confidence=high 表示高度符合当前症状
- 诊断名称使用规范中文医学术语
- 按可能性从高到低排列
- 不要编造未提及的症状或病史"""


@router.post("/diagnosis-suggestion")
async def diagnosis_suggestion(
    req: DiagnosisSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    answers_text = "\n".join(
        f"- {item.get('question', '')}: {item.get('answer', '')}"
        for item in (req.inquiry_answers or [])
    ) or "（暂无追问记录）"

    prompt = _safe_format(
        DIAGNOSIS_SUGGESTION_PROMPT,
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        inquiry_answers=answers_text,
    )
    messages = [
        {
            "role": "system",
            "content": "你是临床诊断助手，只输出JSON，diagnoses数组中每项必须包含name、confidence、reasoning、next_steps字段。",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        model_options = await _get_model_options(db, "inquiry")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task("inquiry",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception as e:
        logger.error(f"diagnosis_suggestion failed: {e}", exc_info=True)
        return {"diagnoses": []}


# ─── QC 修复建议 ──────────────────────────────────────────────
class QCFixRequest(BaseModel):
    field_name: Optional[str] = ""
    issue_description: Optional[str] = ""
    suggestion: Optional[str] = ""
    current_record: Optional[str] = ""
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""


QC_FIX_PROMPT = """你是临床病历书写专家。根据以下质控问题，生成具体的修复文本，供医生直接写入病历。

质控问题：
字段：{field_name}
问题描述：{issue_description}
修改建议：{suggestion}

当前病历相关内容：
{current_record}

患者信息参考：
主诉：{chief_complaint}
现病史：{history}

请直接输出可以写入"{field_name}"字段的修复文本（不要包含字段名称标签，不要解释，直接给出内容）。
如果字段为空或无内容，请根据病历上下文生成合适内容。
输出格式：纯文本，简洁规范，符合医疗文书标准。"""


@router.post("/qc-fix")
async def qc_fix(
    req: QCFixRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prompt = _safe_format(
        QC_FIX_PROMPT,
        field_name=req.field_name or "未知字段",
        issue_description=req.issue_description or "",
        suggestion=req.suggestion or "",
        current_record=req.current_record[:800] if req.current_record else "（空）",
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        model_options = await _get_model_options(db, "qc")
        content = await llm_client.chat(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task("qc",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return {"fix_text": content.strip()}
    except Exception as e:
        logger.error(f"qc_fix failed: {e}", exc_info=True)
        return {"fix_text": req.suggestion or ""}


class NormalizeFieldsRequest(BaseModel):
    fields: dict  # {field_name: value}


@router.post("/normalize-fields")
async def normalize_fields(
    req: NormalizeFieldsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将修改的问诊字段规范化（口语→书面，去重，格式统一），返回整理后的字段值。"""
    if not req.fields:
        return {"fields": {}}

    FIELD_LABEL = {
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

    field_lines = "\n".join(
        f"{FIELD_LABEL.get(k, k)}：{v}"
        for k, v in req.fields.items() if v
    )

    prompt = f"""你是临床病历规范化助手。请对以下问诊字段进行整理，要求：
1. 口语转书面医学语言
2. 去除重复信息（如同一数值在结构化行和自由文本中重复出现）
3. 格式规范，符合医疗文书标准
4. 不添加任何未提及的内容，不编造信息
5. 每个字段独立整理，保持原有信息量

需整理的字段：
{field_lines}

请只输出JSON对象，key为字段名（英文），value为整理后的文本：
{{"chief_complaint": "...", "physical_exam": "...", ...}}
只输出本次传入的字段，不要输出未传入的字段。"""

    try:
        model_options = await _get_model_options(db, "generate")
        content = await llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            **(model_options or {}),
        )
        # 提取 JSON
        import re
        m = re.search(r'\{[\s\S]*\}', content)
        if not m:
            return {"fields": req.fields}
        result = json.loads(m.group())
        # 只返回传入的字段，忽略 AI 额外添加的
        return {"fields": {k: result[k] for k in req.fields if k in result and result[k]}}
    except Exception as e:
        logger.error(f"normalize_fields failed: {e}", exc_info=True)
        return {"fields": req.fields}  # 失败时原样返回，不阻塞保存


@router.post("/quick-qc")
async def quick_qc(
    req: QuickQCRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not req.content.strip():
        return {"issues": [], "summary": "病历内容为空", "pass": False, "grade_score": 0, "grade_level": "丙级"}

    is_inpatient = (req.record_type or "outpatient") not in ("outpatient",)

    # Run rule-based checks（只基于病历文本，不依赖输入字段）
    rule_issues = check_completeness(
        record_text=req.content,
        is_inpatient=is_inpatient,
        is_first_visit=req.is_first_visit if req.is_first_visit is not None else True,
    )
    insurance_issues = check_insurance_risk(req.content)

    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    db_prompt = await _get_active_prompt(db, "qc")
    template = db_prompt or QC_PROMPT
    prompt = _safe_format(template, record_type=record_type_label, content=req.content)
    messages = [{"role": "user", "content": prompt}]
    try:
        model_options = await _get_model_options(db, "qc")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        task_id = await _log_task("qc",
                                   token_input=usage.prompt_tokens if usage else 0,
                                   token_output=usage.completion_tokens if usage else 0)
        # Merge rule-based issues (prepend, deduplicate by field_name for completeness;
        # insurance issues always included since they target content not fields)
        if rule_issues or insurance_issues:
            llm_fields = {i.get("field_name") for i in result.get("issues", [])}
            extra_completeness = [r for r in rule_issues if r.get("field_name") not in llm_fields]
            result["issues"] = extra_completeness + insurance_issues + result.get("issues", [])
            if extra_completeness or insurance_issues:
                result["pass"] = False
        await _save_qc_issues(task_id, result.get("issues", []), encounter_id=req.encounter_id)
        # Calculate grade score
        grade_score, grade_level = _calc_grade_score(result.get("issues", []))
        result["grade_score"] = grade_score
        result["grade_level"] = grade_level
        issues = result.get("issues", [])
        high_count = sum(1 for i in issues if i.get("risk_level") == "high")
        result["summary"] = (
            f"预估评分 {grade_score} 分（{grade_level}），共发现 {len(issues)} 个质控问题"
            + (f"，其中高风险 {high_count} 个" if high_count else "")
        )
        if grade_score >= 100:
            result["pass"] = True
        return result
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)[:200]}"
        fallback = rule_issues + insurance_issues
        grade_score, grade_level = _calc_grade_score(fallback)
        if fallback:
            return {
                "issues": fallback,
                "summary": f"LLM质控分析失败（{err_msg}），已返回规则引擎结果",
                "pass": grade_score >= 90,
                "grade_score": grade_score,
                "grade_level": grade_level,
            }
        return {"issues": [], "summary": f"质控分析失败：{err_msg}", "pass": False, "grade_score": 0, "grade_level": "丙级"}


class GradeScoreRequest(BaseModel):
    content: str = ""
    record_type: Optional[str] = "admission_note"
    # 住院问诊字段（用于规则引擎）
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    marital_history: Optional[str] = ""
    family_history: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    current_medications: Optional[str] = ""
    religion_belief: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    admission_diagnosis: Optional[str] = ""


@router.post("/grade-score")
async def grade_score(
    req: GradeScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    独立的甲级病历评分接口。
    返回预估得分（0-100）、病历等级（甲/乙/丙）、各扣分项明细。
    """
    if not req.content.strip():
        return {"grade_score": 0, "grade_level": "丙级", "issues": [], "summary": "病历内容为空，无法评分"}

    is_inpatient = (req.record_type or "admission_note") not in ("outpatient",)

    rule_issues = check_completeness({
        "chief_complaint": req.chief_complaint or "",
        "history_present_illness": req.history_present_illness or "",
        "past_history": req.past_history or "",
        "allergy_history": req.allergy_history or "",
        "physical_exam": req.physical_exam or "",
        "marital_history": req.marital_history or "",
        "family_history": req.family_history or "",
        "pain_assessment": req.pain_assessment or "",
        "vte_risk": req.vte_risk or "",
        "nutrition_assessment": req.nutrition_assessment or "",
        "psychology_assessment": req.psychology_assessment or "",
        "rehabilitation_assessment": req.rehabilitation_assessment or "",
        "current_medications": req.current_medications or "",
        "religion_belief": req.religion_belief or "",
        "auxiliary_exam": req.auxiliary_exam or "",
        "admission_diagnosis": req.admission_diagnosis or "",
    }, is_inpatient=is_inpatient)

    GRADE_SCORE_PROMPT = """你是病历甲级质量评分专家，依据《浙江省住院病历质量检查评分表（2021版）》对以下{record_type}进行逐项精确评分。
总分100分，90分及以上为甲级病历，75-89分为乙级，75分以下为丙级。

病历内容：
{content}

请输出JSON：
{{
  "estimated_score": 88,
  "deductions": [
    {{
      "category": "扣分类别（如：现病史、专项评估等）",
      "field_name": "具体字段",
      "deduct_points": 1.5,
      "risk_level": "high/medium/low",
      "issue_description": "具体问题描述",
      "suggestion": "改进建议"
    }}
  ],
  "strengths": ["病历优点1", "病历优点2"],
  "grade_level": "甲级/乙级/丙级",
  "summary": "综合评价（2-3句话）"
}}

评分维度（请逐项检查）：
- 主诉（2分）：简明扼要、能导出诊断、有时间
- 现病史（6分）：发病情况/症状特点/诊治经过/一般情况/其他疾病
- 既往史（2分）：重要脏器病史/手术外伤/传染病史/过敏史（缺过敏史扣2分）
- 个人史/婚育史/月经史/家族史（3分）：各1分，缺1项扣1分
- 专项评估（3分）：用药/疼痛/康复/心理/营养/VTE/宗教信仰，缺1项扣1分
- 体格检查（2分）：系统完整/生命体征/专科检查
- 辅助检查（2分）：入院前检查记录完整
- 诊断（4分）：准确全面/规范术语/主诊断在首位
- 首次病程记录（6分，若为该类型）：病例特点/鉴别诊断/诊疗计划
- 书写规范（4分）：医学语言/逻辑一致/无矛盾

deductions中列出实际扣分项，strengths列出2-3个优点，estimated_score为最终预估分值。"""

    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "admission_note", "入院记录")
    prompt = GRADE_SCORE_PROMPT.format(record_type=record_type_label, content=req.content)
    messages = [{"role": "user", "content": prompt}]
    try:
        model_options = await _get_model_options(db, "qc")
        llm_result = await llm_client.chat_json_stream(
            messages,
            temperature=0.2,
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await _log_task("qc",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)

        # 合并规则引擎问题到 deductions
        deductions = llm_result.get("deductions", [])
        rule_field_names = {d.get("field_name") for d in deductions}
        for rule_issue in rule_issues:
            if rule_issue.get("field_name") not in rule_field_names:
                deductions.append({
                    "category": "完整性（规则引擎）",
                    "field_name": rule_issue["field_name"],
                    "deduct_points": 2.0 if rule_issue["risk_level"] == "high" else 1.0,
                    "risk_level": rule_issue["risk_level"],
                    "issue_description": rule_issue["issue_description"],
                    "suggestion": rule_issue["suggestion"],
                })
        # 计算综合评分
        estimated = llm_result.get("estimated_score", 100)
        grade_level = llm_result.get("grade_level", "")
        if not grade_level:
            if estimated >= 90:
                grade_level = "甲级"
            elif estimated >= 75:
                grade_level = "乙级"
            else:
                grade_level = "丙级"
        return {
            "grade_score": estimated,
            "grade_level": grade_level,
            "deductions": deductions,
            "strengths": llm_result.get("strengths", []),
            "issues": [
                {
                    "risk_level": d.get("risk_level", "medium"),
                    "field_name": d.get("field_name", ""),
                    "issue_description": d.get("issue_description", ""),
                    "suggestion": d.get("suggestion", ""),
                    "score_impact": f"-{d.get('deduct_points', 0)}分",
                }
                for d in deductions
            ],
            "summary": llm_result.get("summary", ""),
        }
    except Exception as e:
        # 降级：使用规则引擎结果计算
        grade_score_val, grade_level = _calc_grade_score(rule_issues)
        return {
            "grade_score": grade_score_val,
            "grade_level": grade_level,
            "deductions": [],
            "strengths": [],
            "issues": rule_issues,
            "summary": f"AI评分分析失败，已基于规则引擎估算（预估{grade_score_val}分）",
        }
