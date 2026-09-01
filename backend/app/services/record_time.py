"""病历记录时间与补记判定（services/record_time.py）

2026-08-14 第八轮审计后新增，依据三方规范：

  · HL7 FHIR — 文档创建时刻（DocumentReference.date）与临床相关时间
    （context.period）必须是两个字段，不能混用。
  · 《病历书写基本规范》 — 病程记录"首先标明记录时间"，具体到分钟；
    修改须保留原记录清楚可辨，注明修改时间与修改人。
  · 医法实务（AHIMA 等） — **绝不允许回填过去时间**。补记应带当前日期、
    明确标注为补记、原记录保持可见；电子病历有审计轨迹，事后改时间线一查即知，
    未标注的补记在医疗纠纷中会被当作可疑证据。

本模块把上面第三条落成代码：系统**不阻止**医生记录较早的诊疗时点（住院补写
前一天的病程是正当且必要的），但**一定把它标出来**——差异达到阈值即判为补记，
前端必须显式展示「补记」标识与两个时间，而不是让它看起来像当场写的。
"""

from datetime import datetime, timedelta
from typing import Optional

# 记录时间与系统录入时间相差多久就算「补记」。
#
# 取 12 小时而不是"跨天"：夜班医生 23:50 记录当天 20:00 的查房属正常书写，
# 不该被标补记；而隔了大半天以上再补的，按规范就该让人看见。
LATE_ENTRY_THRESHOLD = timedelta(hours=12)


# 出院之后落笔仍算「当场书写」的文书类型。
#
# 出院记录天然在出院之后写（规范给的就是「出院后 24 小时内完成」），把它算成
# 补记是误标。其余住院文书没有这个豁免——见 is_late_entry 里的说明。
POST_DISCHARGE_EXEMPT_TYPES: frozenset[str] = frozenset({"discharge_record"})


def is_late_entry(
    recorded_at: Optional[datetime],
    created_at: Optional[datetime],
    *,
    discharged_at: Optional[datetime] = None,
    record_type: Optional[str] = None,
    visit_type: Optional[str] = None,
) -> bool:
    """这份文书是否属于「补记」。

    两条判据，命中任一即是：

    ① 记录时点明显早于系统录入时点（差值达到 LATE_ENTRY_THRESHOLD）。
       典型场景：医生今天补写昨天的查房。

    ② 住院文书的记录时点晚于出院时点（出院记录除外）。
       2026-09-02 住院支线实测补的盲区：患者出院后，医生新建一份「日常病程」
       或「手术记录」补齐遗漏——补齐本身合法且临床常见，不该拦。但这份文书的
       recorded_at 兜底取的是**落笔当下**，于是 created_at 与它几乎相等，判据 ①
       算出来差值为 0，系统认定它是「当场书写」，纸面上与真正当场写的完全一样。
       而患者那一刻已经不在院，该次诊疗不可能正在发生——这份文书按定义就是
       事后补的。实测：一份出院后 2 分钟新建的日常病程，is_late_entry 为 False。
       出院记录豁免，因为它本就该在出院之后写。
       限住院：门急诊签发时也会写 completed_at（见 _medical_record_sign），
       不限定的话每一份门诊病历都会被这条误伤。

    Args:
        recorded_at:   医生填写的记录时间（临床相关时点）；未填时不算补记。
        created_at:    系统录入时间（不可改）。
        discharged_at: 出院时点（encounters.completed_at），住院才有意义。
        record_type:   文书类型，用于豁免出院记录。
        visit_type:    接诊类型，判据 ② 仅对 'inpatient' 生效。

    Returns:
        True 表示按规范应标注为补记。
    """
    if recorded_at is None or created_at is None:
        return False
    if (created_at - recorded_at) >= LATE_ENTRY_THRESHOLD:
        return True
    return (
        visit_type == "inpatient"
        and discharged_at is not None
        and record_type not in POST_DISCHARGE_EXEMPT_TYPES
        and recorded_at > discharged_at
    )


def describe_record_time(
    recorded_at: Optional[datetime],
    created_at: Optional[datetime],
    *,
    discharged_at: Optional[datetime] = None,
    record_type: Optional[str] = None,
    visit_type: Optional[str] = None,
) -> dict:
    """给前端的记录时间三元组：记录时间 / 系统录入时间 / 是否补记。

    前端据此展示——补记时两个时间都要露出来，这正是规范要求的
    「明确标注为补记、原记录保持可见」。
    """
    return {
        "recorded_at": recorded_at.isoformat() if recorded_at else None,
        "entered_at": created_at.isoformat() if created_at else None,
        "is_late_entry": is_late_entry(
            recorded_at, created_at,
            discharged_at=discharged_at, record_type=record_type, visit_type=visit_type,
        ),
    }
