"""
AI 快捷接口 - 无需预建接诊记录，直接从问诊信息流式生成病历
"""
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.security import get_current_user
from app.database import get_db
from app.models.medical_record import AITask
from app.models.config import PromptTemplate
from app.services.ai.llm_client import llm_client
from app.services.rule_engine.completeness_rules import check_completeness
from app.services.rule_engine.insurance_rules import check_insurance_risk


async def _log_task(task_type: str, token_input: int = 0, token_output: int = 0):
    """Log an AI task call to the ai_tasks table using its own DB session."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        task = AITask(
            task_type=task_type,
            status='done',
            token_input=token_input,
            token_output=token_output,
            model_name=llm_client.model,
        )
        db.add(task)
        try:
            await db.commit()
        except Exception:
            pass


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

router = APIRouter()


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


RECORD_TYPE_MAP = {
    "outpatient": "门诊病历",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
    "course_record": "日常病程记录",
    "senior_round": "上级医师查房记录",
    "discharge_record": "出院记录",
}

# ── 门诊病历生成 ──────────────────────────────────────────
OUTPATIENT_GENERATE_PROMPT = """你是一名专业的临床病历书写助手。根据以下问诊信息，生成规范的门诊病历草稿。

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

请直接输出病历文本（不要JSON）：

【主诉】
（规范化主诉，症状+时间，20字以内，原则上不用诊断名称）

【现病史】
（口语转书面医学语言，包含：发病情况、症状特点及演变、诊治经过、一般情况）

【既往史】
（含重要脏器疾病史、手术史、食物/药物过敏史）

【个人史】
（个人史及生活习惯）

【体格检查】
（体格检查结果）

【初步诊断】
（规范中文诊断，主要诊断放首位）

要求：口语转书面医学语言，时间线清晰，符合医疗文书规范，禁止编造未提及的症状。"""


# ── 入院记录生成（依据浙江省2021版标准，含全部8个评分项）──────────
ADMISSION_NOTE_PROMPT = """你是临床病历书写专家。根据以下问诊信息，严格按照《浙江省住院病历质量检查评分表（2021版）》生成规范的入院记录。

患者基本信息：
姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史/用药史：{allergy_history}
个人史/附加信息：{personal_history}
体格检查：{physical_exam}
入院诊断：{initial_impression}

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

【月经史】（若为女性患者）
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


async def _stream_text(prompt: str, task_type: str = "generate"):
    """流式输出文本，完成后记录 token 用量到独立 DB 会话"""
    yield "data: {\"type\":\"start\"}\n\n"
    messages = [{"role": "user", "content": prompt}]
    async for chunk in llm_client.stream(messages):
        payload = json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    yield f"data: {{\"type\":\"done\"}}\n\n"
    # Log token usage after stream completes (uses its own DB session)
    usage = llm_client._last_usage
    await _log_task(
        task_type,
        token_input=usage.prompt_tokens if usage else 0,
        token_output=usage.completion_tokens if usage else 0,
    )


_PROMPT_MAP = {
    "outpatient": OUTPATIENT_GENERATE_PROMPT,
    "admission_note": ADMISSION_NOTE_PROMPT,
    "first_course_record": FIRST_COURSE_PROMPT,
    "course_record": COURSE_RECORD_PROMPT,
    "senior_round": SENIOR_ROUND_PROMPT,
    "discharge_record": DISCHARGE_RECORD_PROMPT,
}


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
    prompt = template.format(
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
    )
    return StreamingResponse(_stream_text(prompt, task_type="generate"), media_type="text/event-stream")


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


CONTINUE_PROMPT = """你是临床病历书写助手。医生已经写了部分病历，请根据问诊信息续写未完成的部分。

病历类型：{record_type}

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
    initial_impression: Optional[str] = ""
    record_type: Optional[str] = "outpatient"


SUPPLEMENT_PROMPT = """你是临床病历书写专家。根据质控发现的缺失项，为病历补充缺失内容。

病历类型：{record_type}

问诊信息（参考）：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

当前病历内容：
{current_content}

质控发现的问题（需要补充的内容）：
{qc_issues}

请根据问诊信息，只针对上述质控问题中缺失的内容进行补充。
输出格式：直接输出补充内容（带字段标题，如【既往史】），不要重复已有内容，不要编造未提及的信息。"""


@router.post("/quick-supplement")
async def quick_supplement(
    req: SupplementRequest,
    current_user=Depends(get_current_user),
):
    if not req.qc_issues:
        return StreamingResponse(
            iter(["data: {\"type\":\"done\"}\n\n"]),
            media_type="text/event-stream"
        )
    record_type = RECORD_TYPE_MAP.get(req.record_type, "门诊病历")
    issues_text = "\n".join(
        f"- [{item.get('risk_level','').upper()}] {item.get('issue_description', '')}（建议：{item.get('suggestion', '')}）"
        for item in req.qc_issues
    )
    prompt = SUPPLEMENT_PROMPT.format(
        record_type=record_type,
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content[:1200] if req.current_content else "（空）",
        qc_issues=issues_text,
    )
    return StreamingResponse(_stream_text(prompt, task_type="generate"), media_type="text/event-stream")


@router.post("/quick-continue")
async def quick_continue(
    req: ContinueRequest,
    current_user=Depends(get_current_user),
):
    record_type = RECORD_TYPE_MAP.get(req.record_type, "门诊病历")
    prompt = CONTINUE_PROMPT.format(
        record_type=record_type,
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content or "（暂无内容）",
    )
    return StreamingResponse(_stream_text(prompt, task_type="generate"), media_type="text/event-stream")


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
    prompt = template.format(content=req.content)
    return StreamingResponse(_stream_text(prompt, task_type="polish"), media_type="text/event-stream")


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
      "options": ["选项1", "选项2", "选项3"]
    }}
  ]
}}

硬性规则：
- known_info 中列出的内容，绝对不能出现在 suggestions 的问题里
- suggestions 必须4-6条，每条 options 必须2-4个，与该病情直接相关
- 禁止出现"您的主要症状是什么""症状持续多久了"这类对已明确诊断的患者毫无意义的通用问题"""


@router.post("/inquiry-suggestions")
async def inquiry_suggestions(
    req: InquirySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    db_prompt = await _get_active_prompt(db, "inquiry")
    template = db_prompt or INQUIRY_SUGGESTIONS_PROMPT
    prompt = template.format(
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
        result = await llm_client.chat_json(messages)
        usage = llm_client._last_usage
        await _log_task("inquiry",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception:
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
    prompt = template.format(
        chief_complaint=req.chief_complaint or "未填写",
        history_present_illness=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        department=req.department or "未知",
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        result = await llm_client.chat_json(messages)
        usage = llm_client._last_usage
        await _log_task("exam",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception:
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
  "summary": "总体评价（1-2句话，包含预估得分范围，满分100分）",
  "pass": true/false
}}

【检查标准（依据浙江省2021版评分表，总分100分，90分以上甲级，80-89乙级，80分以下丙级）】

一、主诉（2分）
- 是否简明扼要，能导出第一诊断
- 原则上不用诊断名称（病理确诊、再入院除外）
- 是否有持续时间描述；是否有近况描述
- 风险：主要症状未写或不能导出第一诊断 → high（扣1分）；持续时间不准确或无近况描述 → medium（各扣0.5分）

二、现病史（6分）
- ① 是否记录发病时间、地点、起病缓急及可能原因
- ② 是否按时间顺序描述主要症状的部位、性质、持续时间、程度、演变及伴随症状
- ③ 是否记录入院前检查、治疗经过及效果
- ④ 是否记录发病以来一般情况（饮食、精神、睡眠、大小便）——此项常被遗漏
- ⑤ 是否记录与本次疾病虽无紧密关系但仍需治疗的其他疾病情况
- 风险：①②④缺失 → medium（各扣0.5分）；完全缺失某项 → high

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

risk_level说明：
- high：单项否决（计10分）或本项扣分≥2分的严重问题
- medium：扣0.5-1分的一般问题
- low：书写不规范等轻微问题（扣0.5分以下）

如病历内容完整规范，issues为空数组，pass为true（预估≥90分）。
pass=false 表示预估低于90分（乙级或丙级病历）。"""

RECORD_TYPE_LABELS = {
    "outpatient": "门诊病历",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
    "course_record": "日常病程记录",
    "senior_round": "上级医师查房记录",
    "discharge_record": "出院记录",
}


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

    prompt = DIAGNOSIS_SUGGESTION_PROMPT.format(
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
        result = await llm_client.chat_json(messages)
        usage = llm_client._last_usage
        await _log_task("inquiry",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return result
    except Exception:
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
    prompt = QC_FIX_PROMPT.format(
        field_name=req.field_name or "未知字段",
        issue_description=req.issue_description or "",
        suggestion=req.suggestion or "",
        current_record=req.current_record[:800] if req.current_record else "（空）",
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        content = await llm_client.chat(messages, temperature=0.2)
        usage = llm_client._last_usage
        await _log_task("qc",
                        token_input=usage.prompt_tokens if usage else 0,
                        token_output=usage.completion_tokens if usage else 0)
        return {"fix_text": content.strip()}
    except Exception:
        return {"fix_text": req.suggestion or ""}


@router.post("/quick-qc")
async def quick_qc(
    req: QuickQCRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not req.content.strip():
        return {"issues": [], "summary": "病历内容为空", "pass": False}

    # Run rule-based checks
    rule_issues = check_completeness({
        "chief_complaint": req.chief_complaint or "",
        "history_present_illness": req.history_present_illness or "",
        "past_history": req.past_history or "",
        "allergy_history": req.allergy_history or "",
        "physical_exam": req.physical_exam or "",
    })
    insurance_issues = check_insurance_risk(req.content)

    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    db_prompt = await _get_active_prompt(db, "qc")
    template = db_prompt or QC_PROMPT
    prompt = template.format(record_type=record_type_label, content=req.content)
    messages = [{"role": "user", "content": prompt}]
    try:
        result = await llm_client.chat_json(messages)
        usage = llm_client._last_usage
        await _log_task("qc",
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
        return result
    except Exception:
        fallback = rule_issues + insurance_issues
        if fallback:
            return {"issues": fallback, "summary": "LLM质控分析失败，已返回规则引擎结果", "pass": False}
        return {"issues": [], "summary": "质控分析失败，请重试", "pass": False}
