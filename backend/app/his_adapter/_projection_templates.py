"""规范正文的逐字段契约；None 表示已知全文专属章节，不扩展厂商字段。"""

# 与既有 v1.4 回写字段保持一致；全量文书快照中的空值必须显式清空。
VISIT_FIELDS = (
    "chief_complaint", "onset_time", "history_present_illness", "past_history",
    "allergy_history", "personal_history", "current_medications", "history_informant",
    "family_history", "marital_history", "menstrual_history", "physical_exam",
    "auxiliary_exam", "tcm_inspection", "tcm_auscultation", "tongue_coating",
    "pulse_condition", "treatment_method", "treatment_plan", "followup_advice",
    "precautions", "observation_notes", "patient_disposition",
)
VITAL_FIELDS = ("temperature", "pulse", "respiration", "bp_systolic", "bp_diastolic", "spo2", "height", "weight")
HISTORY = {
    "主诉": "chief_complaint", "现病史": "history_present_illness", "既往史": "past_history",
    "过敏史": "allergy_history", "个人史": "personal_history", "家族史": "family_history",
    "月经史": "menstrual_history", "婚育史": "marital_history", "当前用药": "current_medications",
    "病史陈述者": "history_informant", "辅助检查": "auxiliary_exam", "体格检查": "@exam",
}
TEMPLATES = {
    "outpatient": {**HISTORY, "辨证分析": None, "诊断": "@diagnoses", "治疗意见及措施": "@treatment"},
    "emergency": {**HISTORY, "诊断": "@diagnoses", "急诊处置": "treatment_plan",
                  "患者去向": "patient_disposition", "急诊留观记录": "observation_notes"},
    "admission_note": {**HISTORY, "辅助检查（入院前）": "auxiliary_exam", "专科检查": None,
                       "专项评估": "@assessment", "入院诊断": "@diagnoses"},
    "first_course_record": {"病例特点": None, "初步诊断": "@diagnoses", "中医辨证依据": None,
                            "拟诊讨论": None, "诊疗计划": "treatment_plan"},
    "course_record": {"患者病情记录": None, "查体": "physical_exam", "辅助检查结果回报": "auxiliary_exam",
                      "病情分析": None, "诊疗措施及调整": "treatment_plan", "注意事项": "precautions"},
    "senior_round": {"患者病史补充": None, "病情分析": None, "诊疗意见": "treatment_plan"},
    "discharge_record": {"主诉": "chief_complaint", "入院情况": None, "入院诊断": None,
                         "诊疗经过": None, "出院情况": None, "出院诊断": "@diagnoses", "出院医嘱": "treatment_plan"},
    "pre_op_summary": {"病历摘要": None, "术前诊断": "@diagnoses", "手术指征": None,
                       "拟施手术名称及方式": None, "拟施麻醉方式": None, "手术组成员": None,
                       "术前准备情况": None, "术中术后预计情况及预防处理措施": None, "上级医师意见": None},
    "op_record": {"手术日期": None, "手术开始时间": None, "手术结束时间": None,
                  "术前诊断": None, "术后诊断": "@diagnoses", "手术名称": None,
                  "手术医师": None, "麻醉": None, "护士": None, "手术经过": None, "术中情况": None},
    "post_op_record": {"患者主诉": "chief_complaint", "查体": "physical_exam", "辅助检查结果回报": "auxiliary_exam",
                       "病情分析及术后恢复情况评估": None, "诊疗措施": "treatment_plan", "注意事项及下一步计划": None},
}
# 签名和时点行仅保留全文；按文书限定，不能把任意正文当页眉吞掉。
FOOTERS = {
    "senior_round": ("查房医师签名",),
    "pre_op_summary": ("上级医师签字", "经治医师签字", "记录日期"),
    "op_record": ("术者签名", "记录医师", "记录日期"),
    "post_op_record": ("记录医师",),
}
TITLES = {"first_course_record": "首次病程记录", "discharge_record": "出院记录",
          "pre_op_summary": "术前小结", "op_record": "手术记录"}
