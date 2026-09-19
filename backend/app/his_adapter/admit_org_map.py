# -*- coding: utf-8 -*-
"""HIS 接诊推送·科室与医生映射（his_adapter/admit_service.py 三拆之一，2026-09-19）。

纯机械搬移，零逻辑改动。本模块管"这单派到哪个科、哪位医生"：dept_code
映射（缺失回落医生编制科室）、doctor_code 经 doctor_codes 表找真身账号。
被 admit_service.process_admit 调用；admit_service 保留同名 re-export。
"""
import logging

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.his_adapter.admit_types import AdmitError, AdmitResult  # noqa: F401

logger = logging.getLogger(__name__)


async def _resolve_department(
    db: AsyncSession, dept_code: Optional[str], dept_name: Optional[str],
    fallback_department_id: Optional[str], *, visit_id: str = "",
) -> Optional[str]:
    """把 HIS 推来的挂号科室解析成我方 department_id（2026-08-14 修复）。

    为什么必须用挂号科室而不是医生编制科室：
      规范 3.1 对 dept_code 的说明是「本次接诊/挂号的科室，**非医生编制科室**」，
      并要求厂商去科室表取「本地ID」列（如 1230024）推给我们。但代码原先
      直接用 doctor.department_id —— 恰恰是规范明确排除的那个。
      本院医生存在**跨科室坐班**的情况，那时病历上的科室就是错的。

    为什么按 code 自动建档而不是维护映射表：
      附录 B 已确认「无需提供科室字典——科室编码+名称随接诊推送成对下发」。
      既然每次推送都带着 code+name，再维护一张要人工同步的映射表只会引入
      「HIS 加了新科室但我方没同步」的故障点。第一次见到就落一条，之后按
      code 复用；科室名变了就跟着更新。

    Args:
        dept_code: HIS 科室编码（科室表「本地ID」列）
        dept_name: HIS 科室名称
        fallback_department_id: 解析不出时的兜底（医生编制科室）
        visit_id: 就诊流水号，仅用于告警日志定位是哪条推送没带科室

    Returns:
        我方 department_id；dept_code 为空时返回兜底值。
    """
    from app.models.user import Department

    code = (dept_code or "").strip()
    if not code:
        # 厂商没推科室：退回医生编制科室（总比没有强），并留痕便于联调排查。
        # visit_id 必须真带上（2026-08-15 第十轮审计修复）：原先这里硬编码空串，
        # 日志恒为 `visit_no=`，联调时知道"有推送没带科室"却查不到是哪一条。
        logger.warning(
            "his_admit.dept: 推送未带 dept_code，回退医生编制科室 visit_no=%s",
            visit_id,
        )
        return fallback_department_id

    # 列宽预检（2026-08-29 第五轮 HIS 契约审计）：Department.code String(50)/
    # name String(100)，超长直插会 DataError 打挂整条接诊（与已修的姓名超长
    # 同形态）。code 是匹配键，查找与落库用同一截断值保证自洽。
    if len(code) > 50:
        logger.warning("his_admit.dept: dept_code 超列宽截断 len=%d visit_no=%s",
                       len(code), visit_id)
        code = code[:50]

    dept = (await db.execute(
        select(Department).where(Department.code == code)
    )).scalar_one_or_none()

    name = (dept_name or "").strip() or f"HIS科室{code}"
    if len(name) > 100:
        logger.warning("his_admit.dept: dept_name 超列宽截断 len=%d visit_no=%s",
                       len(name), visit_id)
        name = name[:100]
    if dept is None:
        # 首次见到该科室：自动落一条（见上方"为什么不维护映射表"）
        dept = Department(name=name, code=code, is_active=True)
        db.add(dept)
        await db.flush()
        logger.info("his_admit.dept: 自动建科室 code=%s name=%s", code, name)
    elif dept_name and dept.name != name:
        # HIS 侧改了科室名，跟着更新（code 才是身份，name 只是展示）
        logger.info("his_admit.dept: 科室名更新 code=%s %s→%s", code, dept.name, name)
        dept.name = name
    return dept.id


async def _map_doctor(db: AsyncSession, doctor_code: Optional[str]) -> User:
    """HIS 工号 → 系统医生账号。

    匹配顺序（2026-08-13 改为多工号）：
      1. doctor_codes 表——一位医生名下可挂多个工号（本人门诊/本人住院/助理），
         这是主通道。医院名单证实同一医生有 2~3 个工号，HIS 推任一个都要认得。
      2. users.employee_no——存量主工号（迁移已回填进 doctor_codes，这里兜底）
      3. users.username——批量开户约定「用户名=工号」时的兜底

    **助理工号命中的也是本人账号**，因此签发病历署名恒为本人（医院硬要求：
    病历上不能出现助理名字）。
    """
    from app.core.authz import RECORD_WRITE_ROLES
    from app.models.user import DoctorCode

    code = (doctor_code or "").strip()
    if not code:
        raise AdmitError(40007, "接诊推送缺少医生工号（doctor_code）")

    # 角色约束（2026-08-14 第八轮审计）：三条兜底查询原先都只过滤 is_active，
    # 不看 role。而医院给的人员名单**是全院名单不是医生名单**——里面混着
    # 自助机、护工、财务这类条目，批量开户时只要有一条角色判成了非临床角色，
    # HIS 推来对应工号，接诊就被静默派给它，doctor_id 落到一个不该署名的账号上，
    # 之后该账号对这条接诊的一切写操作都被 assert_encounter_access 放行。
    # 「谁能当接诊医生」这个不变量，quick-start 与 POST /encounters 都已用
    # assert_can_write_record 强制，这里是第三处、也是唯一的自动化入口。
    role_ok = User.role.in_(tuple(RECORD_WRITE_ROLES))

    # 归属先于状态（2026-08-31 权限状态变迁审计 H1·高危）：三级兜底原先
    # 全带 is_active 过滤，导致「A 离职→工号落到同名 username 的新人 B→
    # A 被重新启用→工号又跳回 A」——归属随一个与工号无关的开关来回翻转，
    # 接诊派错人、病历署错名。改为先不看状态定位归属：doctor_codes 里
    # 挂着谁就是谁，停用了就明确报错，绝不静默换人。
    owner = (await db.execute(
        select(User)
        .join(DoctorCode, DoctorCode.user_id == User.id)
        .where(DoctorCode.code == code)
    )).scalars().all()
    if len(owner) > 1:
        raise AdmitError(40007, f"工号 {code} 挂在多个账号下，请联系管理员清理后重试")
    if owner:
        _o = owner[0]
        if not _o.is_active:
            raise AdmitError(
                40007, f"工号 {code} 对应的账号已停用，请联系管理员改派或启用")
        if _o.role not in RECORD_WRITE_ROLES:
            raise AdmitError(
                40007, f"工号 {code} 对应的账号不是临床医生角色，请联系管理员核对")
        return _o

    doctor = None
    if doctor is None:
        # 多行命中显式报错（2026-08-28 完整性审计）：users.employee_no 无唯一
        # 约束（历史工号可能重复，不宜硬加 DB 约束），原 .first() 会按执行计划
        # 任意取一个——接诊派错人、病历署错名。兜底命中 >1 行时拒绝并让厂商
        # ack 可见，逼出数据治理而不是静默错派。
        rows = (await db.execute(
            select(User).where(
                User.employee_no == code, User.is_active.is_(True), role_ok
            )
        )).scalars().all()
        if len(rows) > 1:
            raise AdmitError(40007, f"工号 {code} 对应多个账号，请联系管理员清理后重试")
        doctor = rows[0] if rows else None
    if doctor is None:
        rows = (await db.execute(
            select(User).where(
                User.username == code, User.is_active.is_(True), role_ok
            )
        )).scalars().all()
        if len(rows) > 1:
            raise AdmitError(40007, f"工号 {code} 对应多个账号，请联系管理员清理后重试")
        doctor = rows[0] if rows else None
    if doctor is None:
        # 区分「查无此工号」与「工号对应的账号不是临床角色」——后者在联调现场
        # 光看 40007 会以为是没开户，实际是角色配错，能省下大量排查时间。
        exists_any = (await db.execute(
            select(User.id)
            .outerjoin(DoctorCode, DoctorCode.user_id == User.id)
            .where(
                (DoctorCode.code == code)
                | (User.employee_no == code)
                | (User.username == code)
            )
            .limit(1)
        )).scalar_one_or_none()
        if exists_any is not None:
            raise AdmitError(
                40007,
                f"工号 {code} 对应的账号不是可书写病历的角色（或已停用），"
                f"接诊不予派发——请核对该账号角色",
            )
        raise AdmitError(40007, f"医生工号 {code} 未在 MediScribe 注册或已停用")
    return doctor


