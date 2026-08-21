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
# 全部合法角色（2026-08-21 阶段0 收口）：此前角色枚举散落 4 处各写各的，
# radiologist 就曾三次漏同步（建号被拒/列表显示英文原文）。本集合是唯一
# 权威——管理端建号校验（_user_authz.VALID_ROLES）从这里引用；新增角色
# （如后续的科室质控员 qc_officer）只改这里 + 各消费点的注释指引。
ALL_ROLES = {"doctor", "nurse", "radiologist", *ADMIN_ROLES}


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


async def assert_patient_write_access(db: AsyncSession, patient_id: str, user) -> None:
    """患者档案**写**操作的归属校验（2026-08-14 第六轮审计修复）。

    与 assert_patient_access 的差别只有一点：**radiologist 不直通**。

    assert_patient_access 把 radiologist 放进直通名单，是为了让影像科医生能看
    影像与对应患者信息；但那个函数同时被患者档案的写端点复用，于是影像科医生
    可以改任意患者的过敏史/既往史——这些是临床用药依据，不该由不接诊的角色改动。
    读放行、写按归属，两件事分开判。
    """
    role = getattr(user, "role", "")
    if role in ADMIN_ROLES:
        return
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
        raise HTTPException(
            status_code=403,
            detail="无权修改该患者的档案（只能修改你接诊过的患者）",
        )


# 可以书写/签发病历的角色（2026-08-14 第六轮审计修复）
#
# 医院给的硬要求是「病历上写的名字必须都是本人（医生）」。而原先所有病历写端点
# 只用 get_current_user（要求登录），nurse 与 doctor 权限完全等同——护士能自建
# 接诊、写病历、签发，签发还会自动回写 HIS，署名落到护士头上。
# radiologist 同理：影像科医生不书写门急诊/住院病历。
# 管理员保留（他们要做病历修订与后台维护）。
RECORD_WRITE_ROLES = {"doctor", *ADMIN_ROLES}


def assert_can_write_record(user) -> None:
    """校验当前用户是否有权书写/签发病历。

    Raises:
        HTTPException(403): 角色不允许书写病历（如 nurse / radiologist）。
    """
    role = getattr(user, "role", "")
    if role not in RECORD_WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="当前角色无权书写或签发病历（病历署名须为接诊医生本人）",
        )
