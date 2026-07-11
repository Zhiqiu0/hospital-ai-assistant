"""病历签发 mixin（services/_medical_record_sign.py）

从 medical_record_service 拆出（Round 5: 超标文件拆分）。含 quick_save 签发：
保存最终内容 + 冻结病案首页快照 + 按门诊/住院策略关闭接诊 + 失效缓存 + 埋点。
由 MedicalRecordService 组合，依赖宿主类提供 self.db。
"""
import logging
from datetime import datetime

from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion

# 模块级 logger：病历签发是核心业务里程碑，单独 INFO 级埋点便于运维复盘
logger = logging.getLogger(__name__)


class MedicalRecordSignMixin:
    """病历签发（依赖宿主类提供 self.db）。"""

    async def quick_save(self, encounter_id: str, record_type: str, content: str, doctor_id: str) -> MedicalRecord:
        """签发病历：保存最终内容并将接诊状态标记为已完成。

        "签发"是医生确认本次接诊处理完毕的动作，触发后：
          1. 病历状态变为 submitted（不可继续编辑）
          2. 接诊状态变为 completed（从"进行中"列表消失）

        内容格式：以 {"text": content} 存储（quick_save 简化格式），
        读取时由 encounter_service.get_workspace_snapshot() 统一做格式兼容解包。

        并发安全：with_for_update() 防止同一接诊的两次并发签发请求产生重复病历。

        Args:
            encounter_id: 接诊 ID（不直接传入 record_id，由本方法查找或创建病历）。
            record_type:  病历类型（"outpatient" / "emergency" / "inpatient" 等）。
            content:      病历最终文本内容。
            doctor_id:    签发医生 ID，写入版本的 triggered_by 字段。

        Returns:
            签发后的 MedicalRecord ORM 对象（已 commit 并 refresh）。
        """
        # 加锁查找同接诊同类型的病历（防止并发重复签发）
        # 注意：(encounter_id, record_type) 无唯一约束，历史上可能存在多行
        # （create() 无条件新建、并发首存各插一条），故用 order_by+first() 取最新一条，
        # 与 auto_save_draft 保持一致；不能用 scalar_one_or_none()——多行会抛
        # MultipleResultsFound 导致病历永远签发不出去（500）。
        result = await self.db.execute(
            select(MedicalRecord).where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            ).order_by(MedicalRecord.updated_at.desc()).with_for_update()
        )
        record = result.scalars().first()
        if not record:
            # 首次签发，病历记录尚未创建（极少数情况：直接签发跳过了 AI 生成步骤）
            record = MedicalRecord(encounter_id=encounter_id, record_type=record_type)
            self.db.add(record)
            await self.db.flush()  # 获取数据库生成的 id，后续 RecordVersion 需要引用

        # 创建签发版本（source='doctor_signed' 标记为医生签发，区别于 'doctor_edited'）
        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},    # quick_save 统一用 {"text": ...} 格式
            source="doctor_signed",
            triggered_by=doctor_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "submitted"
        record.submitted_at = datetime.now()

        # 接诊关闭策略：
        #   - 门诊/急诊：一次接诊 = 一份病历，签发即结束 → 关闭接诊
        #   - 住院：一次住院会有多份病历（入院记录/病程/查房/出院小结...），
        #     签发一份不代表出院，接诊状态保持 in_progress；将来由
        #     专门的"办理出院"动作关闭接诊。
        enc_result = await self.db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = enc_result.scalar_one_or_none()
        encounter_closed = False
        if encounter and encounter.visit_type != "inpatient":
            encounter.status = "completed"
            encounter_closed = True

        # ── 病案首页快照（合规要求，2026-05-16 加）─────────────────────────
        # 签发瞬间把患者完整身份字段 + 接诊信息（医生、科室、就诊时间）冻结到
        # patient_snapshot，未来 patient 表更新不再影响已签发病历的展示。
        # 未签发病历的首页由前端实时从 patient store 读取，已签发的从这个 snapshot 读。
        if encounter:
            from app.models.patient import Patient as PatientModel
            from app.models.user import User as UserModel, Department as DeptModel
            patient_r = await self.db.execute(
                select(PatientModel).where(PatientModel.id == encounter.patient_id)
            )
            patient = patient_r.scalar_one_or_none()
            # 一次 join 拿到医生名 + 科室名（doctor 没填科室时 dept_name 为 None，下游兜底）
            doctor_r = await self.db.execute(
                select(UserModel.real_name, DeptModel.name)
                .outerjoin(DeptModel, UserModel.department_id == DeptModel.id)
                .where(UserModel.id == doctor_id)
            )
            doctor_row = doctor_r.one_or_none()
            doctor_name = doctor_row[0] if doctor_row else None
            dept_name = doctor_row[1] if doctor_row else None
            if patient:
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
                }

        await self.db.commit()
        await self.db.refresh(record)
        # 失效缓存：snapshot 一定要失效（病历内容变了）；
        # my_encounters 列表缓存只在接诊真的关闭时才失效
        from app.services.encounter_service import (
            invalidate_encounter_snapshot,
            invalidate_my_encounters,
        )
        await invalidate_encounter_snapshot(encounter_id)
        if encounter_closed:
            await invalidate_my_encounters(encounter.doctor_id)
        # 业务里程碑：签发完成后埋点（不含病历正文，仅 ID/类型/接诊关闭状态）
        logger.info(
            "record.sign: submitted record_id=%s encounter_id=%s type=%s closed_encounter=%s",
            record.id, encounter_id, record_type, encounter_closed,
        )
        return record
