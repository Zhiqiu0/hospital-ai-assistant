"""批量开户服务（services/user_bulk_import.py，2026-08-13）

按医院信息科提供的人员名单一次性建医生账号。

设计要点：
  1. **一账号多工号**——同一医生因「门诊/住院」「本人/助理」被分配多个 HIS 工号
     （安吉濮氏名单实例：汪来煜 6069 本人门诊 / 16029 本人住院 / 16039 助理）。
     全部工号挂到同一账号，HIS 推任一工号都映射到本人，病历署名恒为本人姓名，
     自动满足医院硬要求「病历上不能出现助理名字」。
  2. **统一初始密码 + 强制首登改密**——名单上百人，逐个分发不同密码不现实；
     未改密账号在 get_current_user 处被硬拦（除改密/登出/查自己外一律 403），
     所以"知道工号就能用初始密码登进别人账号"的风险被消除。
  3. **幂等**——用户名已存在则跳过（不覆盖既有账号与密码）；工号已被别的账号
     占用则报 code_conflict 并跳过，绝不把工号从别人名下抢走。
  4. dry_run=True 只校验不落库，导入前可先预览。
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password_async
from app.models.user import Department, DoctorCode, User
from app.schemas.user import (
    BulkImportRequest,
    BulkImportResponse,
    BulkImportResultItem,
)
from app.services.audit_service import log_action


async def bulk_import_doctors(
    db: AsyncSession,
    data: BulkImportRequest,
    current_user,
) -> BulkImportResponse:
    """执行批量开户，返回逐条结果供前端展示报表。"""
    results: list[BulkImportResultItem] = []
    created = skipped = failed = 0

    # 统一哈希一次：bcrypt 单次约 200ms，上百人逐个哈希会把请求拖到几十秒
    pwd_hash = await hash_password_async(data.initial_password)

    # 科室名 → id（名单里的"部门"多为病区/职能科室，匹配不上就留空，不阻断开户）
    dept_rows = (await db.execute(select(Department))).scalars().all()
    dept_map = {d.name: d.id for d in dept_rows}

    # 本批内部去重用：同一工号在名单里出现两次时，第二条应报冲突而不是插入重复
    batch_codes: set[str] = set()
    batch_usernames: set[str] = set()

    for item in data.items:
        # 行内去重（2026-08-13 第三轮审计修复）：门诊/住院工号填成同一个是 Excel
        # 复制粘贴的常见手误，原先会给同一账号连插两条相同 code，撞唯一索引后
        # IntegrityError 未捕获 → 500，整个事务回滚，前面上百条全丢、报表也拿不到。
        # dict.fromkeys 去重同时保持顺序（第一个仍是主工号）。
        codes = list(dict.fromkeys(c.strip() for c in item.codes if c and c.strip()))
        username = (item.username or (codes[0] if codes else "")).strip()
        entry = BulkImportResultItem(
            real_name=item.real_name, username=username, codes=codes, status="error"
        )

        if not username or not codes:
            entry.message = "缺少工号"
            failed += 1
            results.append(entry)
            continue

        # 用户名已存在（库里或本批内）→ 跳过，幂等：重复导入不会覆盖在用账号的密码
        exists = (
            await db.execute(select(User).where(User.username == username))
        ).scalars().first()
        if exists is not None or username in batch_usernames:
            # 账号已存在时**补挂缺失的工号**（2026-08-13 第三轮审计修复）。
            # 原先整条跳过，而全系统只有本函数会写 doctor_codes——联调期手工建的
            # 试点账号永远补不上「本人住院/助理」那几个工号，HIS 用它们推接诊会
            # 直接 ack 40007 接诊进不来，正是本功能要解决的原始故障。
            # 只做"补缺"：不动账号本身、不碰密码、不抢别人名下的工号。
            added: list[str] = []
            if exists is not None and not data.dry_run:
                for code in codes:
                    taken = (await db.execute(
                        select(DoctorCode).where(DoctorCode.code == code)
                    )).scalars().first()
                    if taken is None:
                        db.add(DoctorCode(user_id=exists.id, code=code, note="补挂工号"))
                        added.append(code)
                        batch_codes.add(code)
            entry.status = "skipped_exists"
            entry.message = (
                f"账号已存在（未改动），补挂工号：{','.join(added)}" if added
                else "该用户名已存在，未改动"
            )
            batch_usernames.add(username)
            skipped += 1
            results.append(entry)
            continue

        # 工号被别的账号占用 → 跳过，绝不从别人名下抢工号（会导致病历张冠李戴）
        taken = (
            await db.execute(select(DoctorCode).where(DoctorCode.code.in_(codes)))
        ).scalars().all()
        dup_in_batch = [c for c in codes if c in batch_codes]
        if taken or dup_in_batch:
            occupied = [t.code for t in taken] + dup_in_batch
            entry.status = "code_conflict"
            entry.message = f"工号已被占用：{','.join(sorted(set(occupied)))}"
            skipped += 1
            results.append(entry)
            continue

        if data.dry_run:
            # 预览模式也要占位，否则名单里的重复项在预览时全显示成功、真跑才报错
            batch_usernames.add(username)
            batch_codes.update(codes)
            entry.status = "created"
            entry.message = "预览（未落库）"
            created += 1
            results.append(entry)
            continue

        user = User(
            username=username,
            password_hash=pwd_hash,
            real_name=item.real_name,
            role=item.role or "doctor",
            department_id=dept_map.get(item.department_name or ""),
            employee_no=codes[0],       # 主工号，后台列表展示用
            phone=item.phone,
            is_active=True,
            must_change_password=True,  # 首登强改，未改前服务端只放行改密端点
        )
        db.add(user)
        await db.flush()  # 拿到 user.id 才能挂工号
        for idx, code in enumerate(codes):
            db.add(
                DoctorCode(
                    user_id=user.id,
                    code=code,
                    note="主工号" if idx == 0 else "附加工号（住院/助理）",
                )
            )
        batch_usernames.add(username)
        batch_codes.update(codes)
        entry.status = "created"
        created += 1
        results.append(entry)

    if not data.dry_run:
        # 兜底捕获（2026-08-13 第三轮审计修复）：即便上面逐条查过重，仍可能因
        # 并发导入等原因在 commit 时撞约束。原先未捕获会 500，管理员既看不到
        # 逐条报表、也不知道是哪一行的问题。这里转成可读错误。
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="导入未生效：存在冲突的用户名或工号，请核对名单后重试",
            ) from exc
        await log_action(
            action="bulk_import_users",
            user_id=current_user.id,
            user_name=getattr(current_user, "real_name", None) or current_user.username,
            user_role=current_user.role,
            resource_type="user",
            detail=f"批量开户：成功 {created} 跳过 {skipped} 失败 {failed}",
        )

    return BulkImportResponse(
        total=len(data.items),
        created=created,
        skipped=skipped,
        failed=failed,
        initial_password=data.initial_password,
        items=results,
    )
