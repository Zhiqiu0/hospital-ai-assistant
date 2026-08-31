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
# 科室质控员（2026-08-21 阶段4）：只读复核通道，绝不进 ADMIN_ROLES /
# RECORD_WRITE_ROLES（不能写病历、不能进 admin 后台——权限走 /qc/* 专属路由树）
ALL_ROLES = {"doctor", "nurse", "radiologist", "qc_officer", *ADMIN_ROLES}


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


async def assert_patient_write_access(db: AsyncSession, patient_id: str, user) -> None:
    """患者档案**写**操作的归属校验（2026-08-14 第六轮审计修复）。

    要点：**radiologist 不直通**（读走 PACS 自有端点，写档案不属其职责）。

    历史：旧的 assert_patient_access（读写混用，radiologist 直通）曾被写端点
    复用，影像科医生可改任意患者的过敏史/既往史——这些是临床用药依据，
    不该由不接诊的角色改动。读放行（开放读+审计）、写按归属，两件事分开判。
    旧函数已于 2026-08-29 第七轮审计删除（生产零调用的死码）。
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


# ── 患者 PHI 读取角色（2026-09-01 数据边界审计）──────────────────────────
# 背景：patients.py 的三个读端点注释一直写「任意登录**医生**可读，靠审计留痕
# 追责」，实现却只挂了 get_current_user——**任意登录角色**都能按姓名批量浏览
# 全院患者的身份证、住址、紧急联系人、过敏史。完全同款的问题
# （注释说医生、实现放行全角色）2026-08-29 已在 medical_records 的 by-patient
# 端点修过，patients.py 没有同步。
#
# "全院共享不拦读"这个设计取舍本身是成立的，但它的论证前提是**面向医生**：
# 代班、转诊、复诊换医生都是常态，拦读会挡住正常诊疗。这个论证不适用于
# qc_officer（本该被 /qc/* 的 _dept_scope 限在本科室）和 nurse（无病历读写职责）。
PATIENT_READ_ROLES = {"doctor", *ADMIN_ROLES}
# 影像科额外保留**列表**权限：PACS 工作台上传影像时要在下拉里选患者
# （frontend/src/pages/PacsWorkbenchPage.tsx）。列表项不含身份证/住址，
# 只有姓名性别年龄这类选人必需的最小字段；详情与纵向档案仍不对它开放。
PATIENT_LIST_ROLES = PATIENT_READ_ROLES | {"radiologist"}


def assert_can_read_patient(user, *, list_only: bool = False) -> None:
    """患者 PHI 读取守卫。

    Args:
        user: 当前登录用户。
        list_only: True 表示这是列表端点（影像科选患者需要）。

    Raises:
        HTTPException 403: 角色不在白名单内。
    """
    allowed = PATIENT_LIST_ROLES if list_only else PATIENT_READ_ROLES
    if getattr(user, "role", None) not in allowed:
        raise HTTPException(status_code=403, detail="无权查阅患者信息")
