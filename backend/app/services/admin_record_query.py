"""管理端病历列表查询：先按姓名、医生及签发状态筛选，再计数和分页。"""
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User


async def list_all_records(
    db: AsyncSession,
    page: int,
    page_size: int,
    doctor_id: str | None = None,
    search: str | None = None,
) -> dict:
    """管理员分页查询所有已签发病历，可按医生筛选。

    联表查询：MedicalRecord → Encounter → Patient / User，一次获取完整信息。

    Args:
        page: 页码（从 1 开始）。
        page_size: 每页条数。
        doctor_id: 按医生 UUID 筛选，None 则返回所有医生的病历。
        search: 患者或医生姓名，忽略首尾空白，通配符按字面量匹配。

    Returns:
        {"total": 总数, "items": [病历摘要字典, ...]}，按签发时间倒序。
    """
    offset = (page - 1) * page_size

    # 构建基础查询（联表获取接诊医生 + 患者 + 科室信息）
    # outerjoin Department 是因为历史用户可能没填科室，避免漏数据
    # 注意：Department 模型在 app.models.user 里定义（项目早期约定）
    from app.models.user import Department

    base = (
        select(MedicalRecord, Encounter, Patient, User, Department)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .join(User, Encounter.doctor_id == User.id)
        .outerjoin(Department, User.department_id == Department.id)
        .where(MedicalRecord.status == "submitted")
    )
    if doctor_id:
        base = base.where(Encounter.doctor_id == doctor_id)

    # 姓名搜索先于计数和分页；contains 自动绑定参数并转义 SQL 通配符。
    keyword = (search or "").strip()
    if keyword:
        base = base.where(or_(
            Patient.name.contains(keyword, autoescape=True),
            User.real_name.contains(keyword, autoescape=True),
        ))

    # 先统计总数（用于分页）
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询，按签发时间倒序
    q = base.order_by(desc(MedicalRecord.submitted_at)).offset(offset).limit(page_size)
    rows = (await db.execute(q)).all()

    # ── 批量取本页每份病历的最新版本正文（2026-08-14 第七轮审计修复）──────
    #
    # 原先是在下面的 for 里逐行查一次最新版本 —— 一页 100 条就是 100 次
    # 往返查询。改成两步聚合：先一次拿到每份病历的最大 version_no，
    # 再一次把这些版本行取回来，总共 2 次查询，且写法在 PG / SQLite 都成立。
    record_ids = [record.id for record, *_ in rows]
    latest_content: dict[str, str] = {}
    if record_ids:
        max_ver_rows = (await db.execute(
            select(
                RecordVersion.medical_record_id,
                func.max(RecordVersion.version_no).label("max_no"),
            )
            .where(RecordVersion.medical_record_id.in_(record_ids))
            .group_by(RecordVersion.medical_record_id)
        )).all()
        if max_ver_rows:
            pairs = {(rid, no) for rid, no in max_ver_rows}
            ver_rows = (await db.execute(
                select(
                    RecordVersion.medical_record_id,
                    RecordVersion.version_no,
                    RecordVersion.content,
                ).where(
                    RecordVersion.medical_record_id.in_([r for r, _ in pairs])
                )
            )).all()
            for rid, no, content in ver_rows:
                if (rid, no) not in pairs:
                    continue  # 不是该病历的最新版本
                latest_content[rid] = (
                    content.get("text", "") if isinstance(content, dict) else ""
                )

    items = []
    for record, encounter, patient, doctor, dept in rows:
        content_text = latest_content.get(record.id, "")
        items.append({
            "id": record.id,
            "record_type": record.record_type,
            "status": record.status,
            "submitted_at": record.submitted_at,
            "patient_name": patient.name,
            "patient_gender": patient.gender,
            "doctor_name": doctor.real_name,
            "doctor_id": doctor.id,
            "encounter_id": encounter.id,
            "content_preview": content_text[:100] + "..." if len(content_text) > 100 else content_text,
            "content": content_text,
            # ── 病案首页快照（2026-05-16 加）─────────────────────────────
            # 优先用 patient_snapshot（签发那一刻冻结的身份信息）；为空（旧记录）
            # 才回落到当前 patient 实时字段。前端 RecordViewModal/导出/打印用它
            # 渲染顶部首页。
            "patient_snapshot": record.patient_snapshot,
            # 顺便补全当前 patient 字段做 fallback（前端 PatientSnapshot 字段为空时用）
            "patient_phone": patient.phone,
            "patient_id_card": patient.id_card,
            "patient_address": patient.address,
            "patient_ethnicity": patient.ethnicity,
            "patient_marital_status": patient.marital_status,
            "patient_occupation": patient.occupation,
            "patient_workplace": patient.workplace,
            "patient_contact_name": patient.contact_name,
            "patient_contact_phone": patient.contact_phone,
            "patient_contact_relation": patient.contact_relation,
            "patient_blood_type": patient.blood_type,
            "patient_birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
            "visit_type": encounter.visit_type,
            # Encounter.visited_at = 接诊开始时间（DateTime）；不是 InquiryInput.visit_time
            "visit_time": encounter.visited_at.isoformat() if encounter.visited_at else None,
            "bed_no": encounter.bed_no,
            "department_name": dept.name if dept else None,
        })

    return {"total": total, "items": items}
