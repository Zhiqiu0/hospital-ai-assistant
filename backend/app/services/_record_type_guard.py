# -*- coding: utf-8 -*-
"""文书类型与就诊类型的相容性守卫（services/_record_type_guard.py）

2026-09-01 住院支线端到端实测新增。

**为什么需要它**：门诊 / 急诊 / 住院三个工作台共用同一个 activeEncounterStore，
切换系统时不清当前接诊，而住院页的 visitTypeFilter 只用于**续接诊列表筛选**，
不校验当前接诊。实测走法很自然：在急诊签发完一份病历、不做任何清理，直接访问
/inpatient——住院工作台就把那个 visit_type=emergency 的接诊当住院病人显示，
标成「住院 #xxx」，还给它算「入院记录剩余 19.4 小时」的住院文书时效。

此时医生若在住院工作台继续操作，就会给一个**急诊接诊**挂上 admission_note /
course_record 这类住院文书。而后端此前对此**没有任何校验**——
`_is_inpatient()` 只用来决定"能否有多份同类型文书"，不管类型对不对。

一旦落库，后果是连锁的：病案首页与归档口径错乱、HIS 回写会把一份"入院记录"
推给一个急诊 visit_id、质控会拿住院评分标准去判一份急诊病历。

生产库当前实测无错配（6 组 record_type × visit_type 全部相容），所以这是
"尚未发生但路径已通"的缺口——按本项目「病历不能出问题」的铁律先堵上。
"""
from fastapi import HTTPException

# 就诊类型 → 允许的文书类型。
# 与 models/medical_record.py 的 record_type 枚举一一对应（那份枚举同时是
# HIS 回写的取值，改动须同步规范）。
ALLOWED_RECORD_TYPES: dict[str, set[str]] = {
    "outpatient": {"outpatient"},
    "emergency": {"emergency"},
    # 住院一次接诊天然有多种文书
    "inpatient": {
        "admission_note",
        "first_course_record",
        "course_record",
        "senior_round",
        "pre_op_summary",
        "op_record",
        "post_op_record",
        "discharge_record",
    },
}

_LABEL = {"outpatient": "门诊", "emergency": "急诊", "inpatient": "住院"}


def assert_record_type_matches(visit_type: str | None, record_type: str) -> None:
    """校验文书类型与就诊类型相容，不相容即 400。

    Args:
        visit_type: 接诊的就诊类型；None / 未知值一律放行（不给历史数据添堵）。
        record_type: 待写入的文书类型。

    Raises:
        HTTPException 400: 类型不相容，报文里点明两边的类型，便于医生自查。
    """
    allowed = ALLOWED_RECORD_TYPES.get(visit_type or "")
    if not allowed or record_type in allowed:
        return
    raise HTTPException(
        status_code=400,
        detail=(
            f"文书类型与就诊类型不符：这是一次{_LABEL.get(visit_type, visit_type)}"
            f"接诊，不能写入「{record_type}」类文书。"
            "请确认是否停留在了别的工作台——住院文书要从病区列表选择住院患者后书写。"
        ),
    )
