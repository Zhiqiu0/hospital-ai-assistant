# -*- coding: utf-8 -*-
"""黄金病例集·补充病例（scripts/eval_golden_cases.py，2026-08-24 阶段扩容）。

eval_record_generation.py 原有 4 例只覆盖 3 个 record_type（入院/首程/门诊）。
本模块把覆盖面补到全部 10 类：急诊 + 日常病程/上级查房/出院/术前/手术/术后。
病例改编自濮氏真实病历（已去身份化：姓名一律"患者"，删地址/证件/工号），
原始材料存 D:/文件/项目数据/MediScribe/濮氏医院甲级病历样本（PHI 不入 git）。

病程类核心考点与门诊不同：生产链路里病程类共用**入院问诊载荷**
（pickInpatientInquiry，无"当日专项录入"字段），所以术中细节/当日化验
LLM 拿不到——评测重点是**不得编造**（手术经过/出血量/化验值必须占位或留白），
而不是内容全。

数据形状 = (名字, record_type, 录入 dict, 最低分, 扣分码白名单, 必须出现, 禁止出现)，
与 eval_record_generation.CASES 完全一致。
"""

# ── 病例 5：50 岁女性头痛颈痛（急诊，改编自濮氏内科门诊真实病历）────────
# 考察点：急诊模板（生命体征整行必填/处置/去向）；辅检"已开单未回报"不得编造结果
HEADACHE_EMERGENCY = dict(
    patient_name="患者", patient_gender="女", patient_age="50",
    visit_time="2026-08-19 08:17", onset_time="1月前",
    chief_complaint="右边头痛带着脖子痛一个多月，今天痛得厉害来急诊",
    history_present_illness="一个月前右颞顶部开始痛，一阵一阵的加重，右边脖子也痛，自己吃了布洛芬缓释胶囊0.3g没明显好转，今天早上痛得厉害过来。没发热没呕吐没手麻没走路不稳。",
    past_history="植物神经紊乱好几年，平时断断续续吃谷维素片，具体剂量疗程说不清。没高血压糖尿病，没传染病，没开过刀没输过血。50岁未绝经，月经还规律。",
    allergy_history="没有发现过敏",
    temperature="36.6", pulse="78", respiration="19",
    bp_systolic="140", bp_diastolic="80",
    physical_exam="神清，精神一般，头颅没畸形，两瞳孔等大对光灵敏，脖子软，生理弧度消失，两肺呼吸音清，心率78律齐没杂音，腹软，肝脾没摸到，神经系统没查出异常",
    auxiliary_exam="头颅MRI+MRA、颈椎间盘CT刚开单还没做，抽血报告没出",
    # 急诊请求块读 initial_impression 作诊断（生产 pickEmergencyInquiry 同口径），
    # 不读 western_diagnosis——首跑用错字段导致诊断落占位（我的病例 bug 非系统 bug）
    initial_impression="混合型颈椎病，偏头痛",
    treatment_plan="先做检查，痛得厉害可以临时用布洛芬",
    followup_advice="报告出来复诊，不适随诊",
    patient_disposition="回家观察",
)

# ── 病例 6-10 共用：66 岁男性电锯伤右手（骨伤/手外科，改编自濮氏真实住院病历）──
# 入院速记（口语）。病程类五个 record_type 共用本录入（与生产载荷形状一致）。
HAND_TERSE = dict(
    patient_name="患者", patient_gender="男", patient_age="66",
    visit_time="2026-01-03 19:40", onset_time="1小时前", history_informant="患者本人",
    chief_complaint="电锯锯到右手，痛出血动不了1个多小时",
    history_present_illness="1小时前干活时右手被电锯锯到，马上就痛得动不了，先去了外面医院看了下具体不清楚，过来我们急诊，看到右手指开放性伤口，马上包扎止血。没头晕没恶心没乏力，受伤后没吃没喝，大小便没事。",
    past_history="身体底子差，小肠疝气开过刀6年了，40年前割过阑尾，高血压15年，半个月前左脚息肉切掉。没肝炎结核，没糖尿病冠心病，没输过血，没过敏。",
    personal_history="安吉本地人，没工作，高中文化，不抽烟不喝酒",
    marital_history="25岁结婚，老婆健在，1个儿子身体好",
    family_history="父母都不在了原因不清楚，2个哥哥2个妹妹都健康，家里没遗传病没肿瘤",
    temperature="36", pulse="75", respiration="19",
    bp_systolic="165", bp_diastolic="99", height="170", weight="60",
    physical_exam="神清，精神软。右拇指近节指腹一块2cm*3cm皮肤缺损，里面肌腱部分断裂露出来，末节指头麻，创缘挫烂，出血活跃，伤口污染重，右示指中指近节指腹有裂伤缝合创面。舌质淡苔薄白，脉弦。",
    auxiliary_exam="右手正斜位片：右手小指远侧指间关节屈曲改变，右手第2-5指远侧指间关节退变",
    initial_impression="伤筋 气滞血瘀证；右手切割伤：右拇、示指尺侧指神经断裂，右拇指近节指腹皮肤缺损，右中指皮肤裂伤",
    # 拟手术信息（术前小结/手术记录场景由医嘱层带入）
    treatment_plan="急诊完善术前检查，拟臂丛麻醉下行清创、右拇示指尺侧指神经吻合、右拇指局部转移皮瓣修复、前臂取皮植皮术，术后克林霉素抗感染补液对症",
    pain_assessment="6", vte_risk="低危", nutrition_assessment="营养良好",
    psychology_assessment="良好", rehabilitation_assessment="无",
)
