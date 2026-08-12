"""
业务授权辅助（core/authz.py）

目前只做一件事：校验当前医生对指定接诊的访问权。

规则：
  - super_admin / hospital_admin / dept_admin 直通
  - 其他角色必须是该 Encounter 的 doctor_id 本人
  - 接诊不存在返回 404（不泄露存在性差异）
  - 无权返回 403

使用示例：
    from app.core.authz import assert_encounter_access
    await assert_encounter_access(db, encounter_id, current_user)

这个 helper 不做 dependency injection，由路由函数显式 await 调用，
调用点清晰，不会被 Depends 链路藏起来。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter as EncounterModel


ADMIN_ROLES = {"super_admin", "hospital_admin", "dept_admin"}
PACS_WRITE_ROLES = {"radiologist", *ADMIN_ROLES}


async def assert_encounter_access(
    db: AsyncSession,
    encounter_id: str,
    user,
) -> EncounterModel:
    """校验 user 对 encounter 的读写权限。成功返回 Encounter 对象供复用。"""
    enc = await db.get(EncounterModel, encounter_id)
    if not enc:
        raise HTTPException(status_code=404, detail="接诊不存在")

    role = getattr(user, "role", "")
    if role in ADMIN_ROLES:
        return enc

    if str(getattr(enc, "doctor_id", "")) != str(getattr(user, "id", "")):
        raise HTTPException(status_code=403, detail="无权访问该接诊")

    return enc


def assert_pacs_write(user) -> None:
    """PACS 写操作（上传/分析/发布报告）只允许影像科医生 + 管理员。

    临床医生不能直接调 PACS 写接口，看影像应走自己接诊范围内的只读路径。
    """
    role = getattr(user, "role", "")
    if role not in PACS_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="仅影像科医生可操作 PACS")


async def assert_patient_access(db: AsyncSession, patient_id: str, user) -> None:
    """校验 user 对 patient 的访问权。

    规则：
      - admin 三角色 / radiologist 直通
      - 其他角色（doctor/nurse）必须对该 patient 有过接诊关系（doctor_id 匹配）
    """
    role = getattr(user, "role", "")
    if role in PACS_WRITE_ROLES:
        return
    # 反查：该医生是否曾给该患者接诊
    stmt = (
        select(EncounterModel.id)
        .where(
            EncounterModel.patient_id == patient_id,
            EncounterModel.doctor_id == getattr(user, "id", ""),
        )
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=403, detail="无权访问该患者的病历档案（只能查看你接诊过的患者）")
