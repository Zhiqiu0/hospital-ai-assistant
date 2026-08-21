# -*- coding: utf-8 -*-
"""住院文书法定书写时限——全系统唯一真相源（2026-08-21 阶段0 收口）。

此前时限知识散落三处、各写各的：
  · api/v1/inpatient_compliance.py 的 _COMPLIANCE_RULES（工作台时效卡）——
    只有入院记录/首程，缺出院记录，起算点硬编码入院时刻
  · services/admin_stats_service.py 的 _TIMELINESS_HOURS 等三个私有常量
    （后台达标率统计）——有出院记录 24h 且起算点按类型区分
  · frontend recordTypes.ts 的 whenHint 纯文案
两处后端口径已经不一致（工作台不显示出院倒计时、后台却按 24h 考核），
再各改各的必然出现"工作台说还剩 3 小时、看板说已超时"。收口后本模块是
唯一改动点，工作台与统计天然同口径。

依据：病历书写基本规范 + 濮氏医院病案首页质控方案（出院 24h 内完成填报）。
"""

# 各类文书的书写时限与起算点。
#   start_field: 起算点取 Encounter 的哪个时间字段——
#     visited_at   = 入院/接诊时刻
#     completed_at = 出院时刻（未办出院时为 NULL → 该文书的倒计时不该显示/统计，
#                    绝不能拿 now() 兜底，那会让住院中的病人恒显超时）
RECORD_DEADLINES: list[dict] = [
    {
        "record_type": "admission_note",
        "label": "入院记录",
        "deadline_hours": 24,
        "start_field": "visited_at",
        "required": True,
    },
    {
        "record_type": "first_course_record",
        "label": "首次病程记录",
        "deadline_hours": 8,
        "start_field": "visited_at",
        "required": True,
    },
    {
        "record_type": "discharge_record",
        "label": "出院记录",
        "deadline_hours": 24,
        "start_field": "completed_at",
        "required": True,
    },
]

# 暂不纳入时效考核的类型及原因（写在这里而不是删掉，避免下次有人"顺手补回去"）
DEADLINE_EXCLUDED: dict[str, str] = {
    # 手术记录法定要求是"术后 24 小时内"，但系统未记录手术时刻。
    # 要纳入需先在住院模块增加手术时间字段，届时再加进 RECORD_DEADLINES。
    "op_record": "系统未记录手术时刻，无法确定起算点",
}

# 统计侧便捷视图（{record_type: hours} / {record_type: start_field}）
DEADLINE_HOURS: dict[str, int] = {r["record_type"]: r["deadline_hours"] for r in RECORD_DEADLINES}
DEADLINE_START_FIELD: dict[str, str] = {
    r["record_type"]: r["start_field"] for r in RECORD_DEADLINES
}
