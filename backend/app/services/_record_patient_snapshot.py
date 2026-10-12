"""签发时冻结病案首页；保留原首签语义、查询顺序及所有哈希输入字段。"""
from sqlalchemy import select


async def freeze_patient_snapshot(db, record, encounter, doctor_id):
    # ── 病案首页快照（合规要求，2026-05-16 加）─────────────────────────
    # 签发瞬间把患者完整身份字段 + 接诊信息（医生、科室、就诊时间）冻结到
    # patient_snapshot，未来 patient 表更新不再影响已签发病历的展示。
    # 未签发病历的首页由前端实时从 patient store 读取，已签发的从这个 snapshot 读。
    if encounter:
        from app.models.patient import Patient as PatientModel
        from app.models.user import User as UserModel, Department as DeptModel
        patient_r = await db.execute(
            select(PatientModel).where(PatientModel.id == encounter.patient_id)
        )
        patient = patient_r.scalar_one_or_none()
        doctor_r = await db.execute(
            select(UserModel.real_name).where(UserModel.id == doctor_id)
        )
        doctor_row = doctor_r.one_or_none()
        doctor_name = doctor_row[0] if doctor_row else None

        # 科室取**本次接诊的科室**，不是医生编制科室（2026-08-14 用户决策）。
        #
        # 原先这里 join 的是 users.department_id —— 医生的编制科室。
        # 但医生跨科室坐班时（本院确实存在），病历首页上的科室就是错的：
        # 人在外科坐班，病历却写着他编制所在的内科。
        # encounter.department_id 现在由接诊推送的挂号科室解析而来
        # （见 his_adapter/admit_service._resolve_department），
        # 手工建的接诊则沿用建档时选的科室——两条路都是"这次就诊的科室"。
        # 接诊没有科室时（老数据/未填）回退医生编制科室，总比空着强。
        dept_name = None
        if encounter.department_id:
            dept_name = (await db.execute(
                select(DeptModel.name).where(DeptModel.id == encounter.department_id)
            )).scalar_one_or_none()
        if dept_name is None:
            dept_name = (await db.execute(
                select(DeptModel.name)
                .join(UserModel, UserModel.department_id == DeptModel.id)
                .where(UserModel.id == doctor_id)
            )).scalar_one_or_none()
        # 患者快照同样只冻结一次：它也是 sign_hash 的输入，重写会让历史
        # 签发版本的哈希全部失效（理由同上方 submitted_at）。快照的语义本就是
        # "签发瞬间冻结"，二次签发时重新冻结反而违背它自己的设计。
        if patient and record.patient_snapshot is None:
            record.patient_snapshot = {
                # 身份信息（来自 patient 表）
                "name": patient.name,
                "gender": patient.gender,
                "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
                "patient_no": patient.patient_no,
                "id_card": patient.id_card,
                "phone": patient.phone,
                "address": patient.address,
                "ethnicity": patient.ethnicity,
                "marital_status": patient.marital_status,
                "occupation": patient.occupation,
                "workplace": patient.workplace,
                "contact_name": patient.contact_name,
                "contact_phone": patient.contact_phone,
                "contact_relation": patient.contact_relation,
                "blood_type": patient.blood_type,
                # 接诊信息（来自 encounter / user / department）
                # 注意：Encounter 模型字段叫 visited_at（接诊开始时间）；
                # InquiryInput.visit_time 是医生手填的"就诊时间字符串"。这里取
                # visited_at 作为快照里的就诊时间——它是签发那一刻的真实接诊起点。
                "visit_type": encounter.visit_type,
                "visit_time": encounter.visited_at.isoformat() if encounter.visited_at else None,
                "bed_no": encounter.bed_no,
                "doctor_name": doctor_name,
                "doctor_id": doctor_id,
                "department_name": dept_name,
                # 就诊号（2026-08-31 导出产物审计）：法定病历文书的定位键，
                # 病案室按它归档。此前快照与打印首页都没有，只有患者编号。
                "visit_no": encounter.visit_no,
            }
