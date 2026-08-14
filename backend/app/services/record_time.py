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


def is_late_entry(
    recorded_at: Optional[datetime], created_at: Optional[datetime]
) -> bool:
    """这份文书是否属于「补记」。

    Args:
        recorded_at: 医生填写的记录时间（临床相关时点）；未填时不算补记。
        created_at:  系统录入时间（不可改）。

    Returns:
        True 表示记录时间明显早于系统录入时间，按规范应标注为补记。
    """
    if recorded_at is None or created_at is None:
        return False
    return (created_at - recorded_at) >= LATE_ENTRY_THRESHOLD


def describe_record_time(
    recorded_at: Optional[datetime], created_at: Optional[datetime]
) -> dict:
    """给前端的记录时间三元组：记录时间 / 系统录入时间 / 是否补记。

    前端据此展示——补记时两个时间都要露出来，这正是规范要求的
    「明确标注为补记、原记录保持可见」。
    """
    return {
        "recorded_at": recorded_at.isoformat() if recorded_at else None,
        "entered_at": created_at.isoformat() if created_at else None,
        "is_late_entry": is_late_entry(recorded_at, created_at),
    }
