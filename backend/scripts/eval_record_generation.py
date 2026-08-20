# -*- coding: utf-8 -*-
"""整份病历生成回归评测（scripts/eval_record_generation.py）

背景（2026-08-19）：生成提示词已按濮氏医院 6 份真实病历校准（住院 PR#158、
门诊 PR#159、主诉 PR#160）。校准效果只存在于提示词文案里，任何后续改动都可能
悄悄改坏——本脚本把真实病例的"医生录入 → AI 生成 → 规则引擎打分"整条链路
固化下来，改完生成相关代码手动跑一遍，几分钟内知道有没有劣化。

不是单元测试（调真 LLM、花钱、有随机性），与 eval_cc_rewrite.py（主诉专项）
配套，用法：
    cd backend && venv/Scripts/python scripts/eval_record_generation.py

断言只写事实类的保守检查（分数下限 / 扣分码白名单 / 必须出现的数值与章节 /
禁止出现的口语与编造证候），措辞好坏仍需人眼扫输出。
病例数据改编自濮氏真实病历（已去除患者身份信息）。
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.ai_request import GradeScoreRequest, QuickGenerateRequest  # noqa: E402
from app.services.ai._qc_ops import run_grade_score  # noqa: E402
from app.services.ai.llm_client import llm_client  # noqa: E402
from app.services.ai.model_options import get_model_options  # noqa: E402
from app.services.ai.record_prompts import build_record_prompt  # noqa: E402
from app.services.ai.record_renderer import render_record  # noqa: E402

# 打分伪影：GradeScoreRequest 不带患者姓名/性别/年龄（工作台真实链路会带），
# 该扣分码在本评测中始终豁免
ARTIFACT_CODES = {"OP-BASIC-INFO-01"}

# ── 病例 1：75 岁女性胸骨体骨折（住院，口语速记录入）────────────────
FRACTURE_TERSE = dict(
    patient_name="患者", patient_gender="女", patient_age="75",
    visit_time="2025-12-09 19:10", onset_time="5天前", history_informant="患者本人",
    chief_complaint="胸口被压到疼了5天，昨天摔了下更疼了",
    history_present_illness="5天前搬重物压伤前胸，痛得厉害不能动，休息好点，没昏迷没胸闷，门诊CT说胸骨体骨折，回家保守。昨天坐下时又摔到前胸，复查CT胸骨体骨折、两侧胸腔积液、左肺感染，收住院。吃饭大小便都正常。",
    past_history="高血压几年，吃药控制。其他没有。没做过手术没输过血。",
    allergy_history="没有过敏",
    personal_history="农民，安吉本地人，不抽烟不喝酒",
    menstrual_history="50岁绝经，以前月经正常",
    marital_history="22岁结婚，1儿2女都健康",
    family_history="父母去世原因不清楚，兄弟姐妹健康，家里没肿瘤没遗传病",
    temperature="36.3", pulse="101", respiration="19",
    bp_systolic="151", bp_diastolic="72", height="165", weight="44.5",
    physical_exam="神清，强迫体位。前胸右胸稍肿，没青紫，没连枷胸，压痛叩痛阳性，胸廓挤压征阳性。肺叩清，没反常呼吸。腰活动欠佳。下肢不麻。舌红苔薄脉弦涩。",
    auxiliary_exam="门诊胸部CT：胸骨体骨折，两侧胸腔积液，左肺感染",
    initial_impression="骨折病 气滞血瘀证；胸骨体骨折，两侧胸腔积液，左肺感染，老年性骨质疏松，高血压病",
)

# ── 病例 2：69 岁男性肋骨骨折（门诊骨伤科，口语速记录入）─────────────
RIB_TERSE = dict(
    patient_name="患者", patient_gender="男", patient_age="69",
    visit_time="2026-02-23 12:58", onset_time="10天前", is_first_visit=True,
    chief_complaint="左边胸口肋骨痛10来天",
    history_present_illness="10天前撞到左胸，当时就痛，没胸闷心慌喘不上气，没咳血没头晕。最近搬东西痛得更厉害了，来看中医。吃饭睡觉一般，大小便正常。",
    past_history="身体一般，没大毛病，没传染病，没做过手术没输过血",
    allergy_history="没有",
    family_history="家里没遗传病没传染病",
    temperature="36.8", pulse="88", respiration="20", bp_systolic="135", bp_diastolic="82",
    physical_exam="左胸肋那里一按就痛，挤压试验阳性，有点肿，没皮下气肿，两肺呼吸音清，心率齐。肚子软不痛。",
    tcm_inspection="神清，精神还行，胸廓对称，左胸壁有点肿，皮肤没破，呼吸有点浅",
    tcm_auscultation="说话声音平稳，呼吸浅，不咳嗽不喘",
    tongue_coating="舌暗红苔薄白",
    pulse_condition="脉弦涩",
    auxiliary_exam="肋骨CT：左边第4-5肋不全性骨折。右肺中叶膨胀不全，心脏增大，冠脉主动脉钙化，可能有肝囊肿",
    western_diagnosis="肋骨骨折，胸壁挫伤",
    tcm_disease_diagnosis="骨折病",
    tcm_syndrome_diagnosis="气滞血瘀证",
    treatment_method="活血化瘀理气止痛续筋接骨",
    treatment_plan="醋氯芬酸分散片，骨肽片，三七伤药胶囊，中药7贴",
    followup_advice="7天后复诊，不舒服随时来",
    precautions="卧床少动，别咳嗽别深呼吸别翻身太猛，别负重，保暖，吃清淡点多补钙，胸闷气短咳血马上来",
)

# 速记录入里根本没说过的经典证候/阴性症状——辨证分析不得为了套路编出来。
# 注："拒按"不在此列：两个病例录入里都有压痛（"一按就痛/压痛叩痛阳性"），
# "拒按"是有依据的辨证转写（首轮评测曾误报，人工判定为检查器过严）
FABRICATED_TCM = ["痛有定处", "固定不移", "入夜尤甚", "无放射痛"]
# 口语残留（叙述性字段必须书面化；不含主诉——主诉规范化由 eval_cc_rewrite 专测）
COLLOQUIAL = ["痛得厉害", "1儿2女", "家里没", "别咳嗽", "不舒服随时来", "吃饭大小便", "有点肿", "没青紫"]

# ── 病例 3：39 岁男性痛风复诊（门诊复诊，改编自濮氏真实复诊病历）──────
# 考察点（2026-08-20 修复项）：①previous_record 沿用（既往史/过敏史从上次病历带出）
# ②现病史"病史同前"式衔接 ③"开了药"不得具体化成"中药/西药"
# ④复诊诊断式主诉不因"无持续时间"被扣（法定"复诊可用诊断代替"豁免）
# previous_record 用**完整渲染形态**（含 [未填写，需补充] 占位行）——生产实测
# 干净的短基线会侥幸通过，完整病历里模型曾放弃沿用改写占位符（2026-08-20 走查）
GOUT_REVISIT_PREV = """就诊时间：2026-08-03 15:06　病发时间：2026-08-02 20:00

【主诉】
左足踇趾肿痛反复发作3年，加重1日

【现病史】
患者3年前出现左足踇趾反复肿痛，曾在外院就诊，诊断为痛风，对症治疗后好转，1日前饮酒后加重，今来我院要求进一步检查。

【既往史】
既往体质健康，否认心脑血管、肝、肾、内分泌重大疾病史，否认传染病史，否认外伤、手术、输血史。

【过敏史】
未发现

【个人史】
[未填写，需补充]

【家族史】
[未填写，需补充]

【体格检查】
T:36.6℃ P:78次/分 R:19次/分 BP:125/94mmHg
望诊：[未填写，需补充]
闻诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]
切诊·脉象：[未填写，需补充]
其余阳性体征：左足大踇趾红肿，关节活动可

【辨证分析】
[未填写，需补充]

【辅助检查】
肾功能：尿酸542.5μmol/L；血脂：总胆固醇7.26mmol/L，甘油三酯11.91mmol/L

【诊断】
中医诊断：[未填写，需补充]
西医诊断：混合性高脂血症，痛风

【治疗意见及措施】
治则治法：[未填写，需补充]
处理意见：秋水仙碱、非布司他、非诺贝特口服
复诊建议：2周后空腹复查肝功能、血脂
注意事项：低盐低脂饮食，多饮水"""

GOUT_REVISIT = dict(
    patient_name="患者", patient_gender="男", patient_age="39",
    is_first_visit=False, visit_time="2026-08-12 09:10",
    # onset_time = 复诊开始时前端自动同步带入（2026-08-20 走查后的真实请求形状：
    # 延续性字段沿用由数据链路保证——"复制上次诊断"是确定性任务，不交给 LLM；
    # 下方 western_diagnosis 同理视为自动同步带入）
    onset_time="2026-08-02 20:00",
    # past_history = 复诊时患者档案卡带出（真实请求形状）
    past_history="既往体质健康，否认心脑血管、肝、肾、内分泌重大疾病史，否认传染病史，否认外伤、手术、输血史。",
    chief_complaint="痛风、高脂血症治疗后来复查",
    history_present_illness="病史同前，上次开了药吃了，症状比之前好转，今天来复查血。",
    physical_exam="神清，精神一般，心肺听诊没什么问题",
    temperature="36.6", pulse="78", respiration="19", bp_systolic="125", bp_diastolic="80",
    auxiliary_exam="今日开单复查：肝功能、血脂、肾功能、血常规、血糖",
    western_diagnosis="痛风，混合性高脂血症",
    treatment_plan="开检查单复查",
    followup_advice="7日复诊，不适随诊",
    previous_record=GOUT_REVISIT_PREV,
)

# (名字, record_type, 录入, 最低分, 扣分码白名单, 必须出现, 禁止出现)
CASES = [
    ("住院入院记录·速记", "admission_note", FRACTURE_TERSE, 96,
     {"IP-ADMISSION-ASSESS-01", "IP-ADMISSION-ASSESS-02", "IP-ADMISSION-ASSESS-03",
      "IP-ADMISSION-ASSESS-04", "IP-ADMISSION-ASSESS-05", "IP-ADMISSION-ASSESS-06",
      "IP-ADMISSION-ASSESS-07", "IP-ADMISSION-EXAM-01"},
     ["【专科检查】", "T:36.3", "151/72", "【入院诊断】", "骨折病", "高血压"],
     COLLOQUIAL),
    ("住院首次病程·速记", "first_course_record", dict(FRACTURE_TERSE, record_type="first_course_record"), 98,
     {"IP-FIRST-COURSE-02"},
     ["【病例特点】", "【初步诊断】", "【中医辨证依据】", "【拟诊讨论】", "【诊疗计划】",
      "气滞血瘀", "弦涩"],
     FABRICATED_TCM),
    ("门诊病历·速记", "outpatient", dict(RIB_TERSE, record_type="outpatient"), 96,
     {"OP-PRESENT-ILLNESS-02"},
     ["【家族史】", "【辨证分析】", "T:36.8", "135/82", "骨折病 — 气滞血瘀证",
      "醋氯芬酸分散片", "第4-5肋"],
     COLLOQUIAL + FABRICATED_TCM),
    # 复诊：四诊/中医诊断医生未录（对照医院真实复诊现状），相应扣分属如实反映 → 白名单
    ("门诊复诊·痛风复查", "outpatient", GOUT_REVISIT, 74,
     {"OP-PHYSICAL-EXAM-01", "OP-PHYSICAL-EXAM-02", "OP-PHYSICAL-EXAM-03",
      "OP-PHYSICAL-EXAM-04", "OP-DIAGNOSIS-01", "OP-TREATMENT-02"},
     # "西医诊断：混合性高脂血症" = 诊断沿用断言（本次未录诊断必须照抄上次，
     # 2026-08-20 生产实锤模型曾写占位符放弃沿用）
     ["病史同前", "好转", "既往体质健康", "西医诊断：痛风，混合性高脂血症", "125/80"],
     # 中药/西药/输液 = 药物具体化编造；"上次开了药" = 口语残留
     ["中药", "西药", "输液", "上次开了药"]),
]


async def run_case(name, record_type, payload, min_score, allowed, must, banned) -> bool:
    req = QuickGenerateRequest(**dict(payload, record_type=record_type))
    prompt = build_record_prompt(record_type, req)
    opts = get_model_options("generate")
    result = await llm_client.chat_json_stream(
        [{"role": "user", "content": prompt}],
        temperature=opts["temperature"], max_tokens=opts["max_tokens"],
        model_name=opts["model_name"],
    )
    text = render_record(record_type, result, visit_time=req.visit_time,
                         onset_time=req.onset_time, patient_gender=req.patient_gender)
    score = await run_grade_score(None, GradeScoreRequest(
        content=text, record_type=record_type,
        is_first_visit=payload.get("is_first_visit", True)))

    problems: list[str] = []
    codes = {i.get("rule_code") for i in score["issues"]} - ARTIFACT_CODES
    if score["grade_score"] < min_score:
        problems.append(f"评分 {score['grade_score']:.0f} < 下限 {min_score}")
    unexpected = codes - allowed
    if unexpected:
        problems.append(f"新增扣分码 {sorted(unexpected)}")
    problems += [f"缺'{m}'" for m in must if m not in text]
    problems += [f"含禁'{b}'" for b in banned if b in text]
    # 生命体征编造守卫：录入外的体温值不得出现
    for t in re.findall(r"T:(\d+\.?\d*)", text):
        if t not in (payload.get("temperature"), ""):
            problems.append(f"体温 {t} 非录入值")
    flag = "✓" if not problems else "✗ " + "；".join(problems)
    print(f"{flag}  {name}  {score['grade_score']:.0f}分")
    if problems:
        print(text)
    return not problems


async def main() -> None:
    results = [await run_case(*c) for c in CASES]
    print(f"\n{sum(results)}/{len(results)} 通过")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
