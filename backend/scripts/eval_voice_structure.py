# -*- coding: utf-8 -*-
"""语音结构化回归评测（scripts/eval_voice_structure.py）

背景（2026-08-20）：医生实际用得最多的录入方式是语音（转写→结构化拆字段→生成），
但此前所有校准都测的打字录入。本脚本用 3 段带陷阱的医生口述转写稿走真实
结构化链路（VOICE_STRUCTURE_PROMPT_* → LLM），机械断言字段路由与真实性：
  - 生命体征只进 vital_signs 结构体、不混进体格检查文字
  - 患者转述的外院诊断进病史、不进本次诊断字段
  - 口误自我修正（"右边…不对左边"）取修正值
  - 患者自报药名归长期用药；"开了药"不得具体化
  - 婚育/月经/家族/疼痛评分/宗教各归各字段
  - 增量基线：已有内容不重复输出

不是单元测试（调真 LLM、花钱、有随机性），与 eval_cc_rewrite.py /
eval_record_generation.py 配套，改语音结构化提示词后手动跑：
    cd backend && venv/Scripts/python scripts/eval_voice_structure.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai.llm_client import llm_client  # noqa: E402
from app.services.ai.model_options import get_model_options  # noqa: E402
from app.services.ai.prompts import (  # noqa: E402
    VOICE_STRUCTURE_PROMPT_INPATIENT,
    VOICE_STRUCTURE_PROMPT_OUTPATIENT,
)

# ── 病例 1：门诊初诊·肋骨外伤（口水话 + 口误修正 + 体征口述 + 舌脉） ──
T1 = """医生：嗯，哪里不舒服啊？
患者：大夫，我这个左边胸口，肋骨这里痛，有十来天了。那个，十天前搬东西撞到的。
医生：撞到之后一直痛吗？有没有胸闷心慌，喘不上气？
患者：没有没有，就是搬重东西的时候更痛。
医生：我看一下啊。右边……不对，是左边胸口这里，一按就痛是吧，挤压试验阳性。有一点点肿，皮肤没破。
医生：来量个血压。血压135的82，体温36度8，脉搏88，呼吸20。
医生：舌头伸出来看看。嗯，舌质暗红，苔薄白。把个脉……脉弦涩。
患者：严重吗医生？
医生：门诊拍的CT说是左侧第4、第5肋不全性骨折。问题不大，给你开点药，注意别负重，别做扩胸运动，一周以后过来复查。"""

# ── 病例 2：门诊复诊·痛风（增量基线 + 患者转述外院诊断 + 自报药名） ──
BASELINE2 = """【主诉】
左足踇趾肿痛反复发作3年，加重1日

【现病史】
患者3年前出现左足踇趾反复肿痛，1日前饮酒后加重，今来我院要求进一步检查。

【既往史】
既往体质健康，否认手术史、输血史。"""

T2 = """医生：吃了药感觉怎么样？
患者：好多了，脚不怎么痛了。我现在一直在吃非布司他，一天一片。
医生：嗯，那个，当时是哪里看的说是痛风？
患者：三年前在外面医院看的，说是痛风。
医生：行。今天复查个血，看看尿酸降没降。量个血压，125的80。
患者：要紧吗？
医生：不要紧，先复查。少喝酒，管住嘴，两个礼拜后再过来。"""

# ── 病例 3：住院入院·女性（婚育/月经/家族/疼痛评分/宗教路由） ──
T3 = """医生：老人家，哪里不舒服？
患者：胸口痛，五天前搬重物压到的，昨天坐下去的时候又摔了一下，更痛了。
医生：疼得厉害吗？十分制的话有几分？
患者：有七分吧，晚上睡不好。
医生：以前有什么毛病吗？
患者：有高血压，吃药控制着。没开过刀没输过血。
医生：家里人身体怎么样？
患者：老伴走得早，有一个儿子两个女儿，都健康。爸妈也都不在了，什么原因不清楚。
医生：月经方面呢？
患者：五十岁就绝经了，年轻时候正常的。
医生：吃东西有什么忌口吗？信什么教吗？
患者：不信教，不忌口。
医生：体温36度3，血压151的72，心率101。"""


def _vital(inq: dict, key: str) -> str:
    return str(((inq.get("vital_signs") or {}).get(key)) or "").strip()


async def structure(template: str, transcript: str, baseline: str, gender: str, age: str) -> dict:
    prompt = template.format(
        patient_name="患者", patient_gender=gender, patient_age=age,
        existing_baseline=baseline or "（无）", transcript=transcript,
    )
    opts = get_model_options("generate")
    result = await llm_client.chat_json_stream(
        [{"role": "system", "content": "你是临床病历整理助手，只输出合法 JSON，禁止输出解释说明。"},
         {"role": "user", "content": prompt}],
        temperature=opts["temperature"], max_tokens=opts["max_tokens"],
        model_name=opts["model_name"],
    )
    return result.get("inquiry") or {}


def check(name: str, inq: dict, rules: list) -> bool:
    """rules: (说明, callable(inq)->bool)"""
    problems = [desc for desc, ok in ((d, f(inq)) for d, f in rules) if not ok]
    flag = "✓" if not problems else "✗ " + "；".join(problems)
    print(f"{flag}  {name}")
    if problems:
        print(json.dumps(inq, ensure_ascii=False, indent=1)[:1500])
    return not problems


async def main() -> None:
    results = []

    inq = await structure(VOICE_STRUCTURE_PROMPT_OUTPATIENT, T1, "", "男", "69")
    results.append(check("门诊初诊·肋骨外伤", inq, [
        ("主诉含左侧与时间", lambda q: "左" in str(q.get("chief_complaint")) and ("10天" in str(q.get("chief_complaint")) or "十" in str(q.get("chief_complaint"))) ),
        ("口误修正取左侧（体检无'右'）", lambda q: "右" not in str(q.get("physical_exam"))),
        ("体检文字不混体征数值", lambda q: all(x not in str(q.get("physical_exam")) for x in ("135", "36.8", "36度8", "88"))),
        ("血压路由", lambda q: _vital(q, "bp_systolic") == "135" and _vital(q, "bp_diastolic") == "82"),
        ("体温路由", lambda q: _vital(q, "temperature") in ("36.8", "36.80")),
        ("舌象", lambda q: "暗红" in str(q.get("tongue_coating"))),
        ("脉象", lambda q: "弦涩" in str(q.get("pulse_condition"))),
        ("辅检含CT结论", lambda q: "肋" in str(q.get("auxiliary_exam")) and "CT" in str(q.get("auxiliary_exam")).upper()),
        ("注意事项路由", lambda q: "负重" in (str(q.get("precautions")) + str(q.get("followup_advice")) + str(q.get("treatment_plan")))),
        ("药物不具体化", lambda q: all(x not in json.dumps(q, ensure_ascii=False) for x in ("中药", "西药"))),
    ]))

    inq = await structure(VOICE_STRUCTURE_PROMPT_OUTPATIENT, T2, BASELINE2, "男", "39")
    results.append(check("门诊复诊·痛风（增量基线）", inq, [
        ("外院诊断不进本次诊断字段", lambda q: "痛风" not in str(q.get("western_diagnosis"))),
        ("自报药名归长期用药", lambda q: "非布司他" in str(q.get("current_medications"))),
        ("现病史为增量不复述基线", lambda q: "3年前" not in str(q.get("history_present_illness")) and "饮酒" not in str(q.get("history_present_illness"))),
        ("血压路由", lambda q: _vital(q, "bp_systolic") == "125" and _vital(q, "bp_diastolic") == "80"),
        ("基线已有的既往史不重复", lambda q: "输血" not in str(q.get("past_history"))),
    ]))

    inq = await structure(VOICE_STRUCTURE_PROMPT_INPATIENT, T3, "", "女", "75")
    results.append(check("住院入院·女性（字段路由）", inq, [
        ("婚育史路由", lambda q: "儿" in str(q.get("marital_history")) or "女" in str(q.get("marital_history"))),
        ("月经史路由", lambda q: "绝经" in str(q.get("menstrual_history"))),
        ("家族史路由", lambda q: "父母" in str(q.get("family_history")) or "爸妈" in str(q.get("family_history"))),
        ("疼痛评分路由", lambda q: "7" in str(q.get("pain_assessment")) or "七" in str(q.get("pain_assessment"))),
        ("宗教/忌口路由", lambda q: str(q.get("religion_belief")).strip() != ""),
        ("既往史高血压", lambda q: "高血压" in str(q.get("past_history"))),
        ("体征路由", lambda q: _vital(q, "temperature") == "36.3" and _vital(q, "bp_systolic") == "151"),
        ("体检文字不混数值", lambda q: all(x not in str(q.get("physical_exam")) for x in ("151", "36.3", "101"))),
        ("婚育不塞个人史", lambda q: "儿" not in str(q.get("personal_history"))),
    ]))

    print(f"\n{sum(results)}/{len(results)} 通过")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
