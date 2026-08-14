"""接诊取消 + 孤儿患者软删 mixin（services/_encounter_cancel.py）

从 encounter_service 拆出（Round: 超标文件拆分）。取消接诊是软取消
（数据全保留供回溯），并联动软删"这次接诊新建又立即取消"的孤儿患者档案。
由 EncounterService 组合。
"""
import logging
from datetime import datetime as _dt

from fastapi import HTTPException
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.services.encounter_cache import (
    invalidate_encounter_snapshot,
    invalidate_my_encounters,
)

logger = logging.getLogger(__name__)


class EncounterCancelMixin:
    """接诊取消 + 孤儿患者软删（依赖宿主类提供 self.db）。"""

    async def cancel(
        self,
        encounter_id: str,
        operator_doctor_id: str,
        cancel_reason: str,
    ) -> dict:
        """取消接诊（软取消，所有数据保留供回溯）。

        校验：
          - 接诊存在（404）
          - 操作者 = 主治医生（403）
          - 接诊状态 in_progress（已 completed/cancelled 直接幂等返回）
          - 病历未签发（已签发要走"病历作废"流程，Phase 1 不支持，403）

        操作：
          - status='cancelled'
          - cancel_reason / cancelled_at / cancelled_by 记录
          - 失效相关缓存（snapshot + my_encounters + patient_cache）

        Returns: {"ok": True, "encounter_id": ..., "already_cancelled": bool}
        """
        # 取接诊本身
        result = await self.db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise HTTPException(status_code=404, detail="接诊不存在")
        if encounter.doctor_id != operator_doctor_id:
            raise HTTPException(status_code=403, detail="只有主治医生可取消接诊")

        # 已是终态：幂等返回（前端误触双击不报错）
        if encounter.status == "cancelled":
            return {"ok": True, "encounter_id": encounter_id, "already_cancelled": True}
        if encounter.status == "completed":
            raise HTTPException(
                status_code=400,
                detail="接诊已完成，无法取消（如需作废已签发病历请走病历作废流程）",
            )

        # 已签发病历守护：扫一眼该接诊的病历是否含 status='submitted'
        sub_check = await self.db.execute(
            select(MedicalRecord.id)
            .where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.status == "submitted",
            )
            .limit(1)
        )
        if sub_check.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=403,
                detail="本接诊已有签发病历，无法取消（请走病历作废流程）",
            )

        # 软取消
        encounter.status = "cancelled"
        encounter.cancel_reason = cancel_reason
        encounter.cancelled_at = _dt.now()
        encounter.cancelled_by = operator_doctor_id

        # ── 孤儿患者联动软删（2026-05-03 加）─────────────────────────────────
        # 业务规则：这次接诊取消后，如果该患者
        #   1) 没有任何其他 encounter（包括 in_progress / completed / 之前 cancelled）；
        #   2) 不是 HIS 来源（is_from_his=false）——HIS 患者在外部系统也存在，不能删；
        # 则视该档案为"这次接诊新建+又取消"的孤儿数据，连带软删，避免医生
        # 在复诊/初诊查重时再次搜到一个"明明被取消的人"。
        # 老患者复诊取消（满足条件 1 不成立）→ 不动 patient.is_deleted。
        patient_soft_deleted = await self._soft_delete_patient_if_orphan(
            patient_id=encounter.patient_id,
            current_encounter_id=encounter_id,
            operator_doctor_id=operator_doctor_id,
        )

        await self.db.commit()

        # 失效缓存：snapshot + 该医生的进行中列表 + 患者基本信息
        # 患者信息变更（住院状态 / 软删）都要失效搜索缓存，防止前端读到过期列表
        await invalidate_encounter_snapshot(encounter_id)
        await invalidate_my_encounters(operator_doctor_id)
        if encounter.visit_type == "inpatient" or patient_soft_deleted:
            from app.services.patient_service import _invalidate_patient_cache
            await _invalidate_patient_cache(encounter.patient_id)

        return {
            "ok": True,
            "encounter_id": encounter_id,
            "already_cancelled": False,
            "patient_soft_deleted": patient_soft_deleted,
        }

    async def _soft_delete_patient_if_orphan(
        self,
        patient_id: str,
        current_encounter_id: str,
        operator_doctor_id: str,
    ) -> bool:
        """取消接诊后，判断当前患者是否为孤儿档案，是则软删并返回 True。

        判定条件（必须同时满足）：
          1. 该患者除当前正被取消的 encounter 外，没有其他 encounter
             （任何状态都算——in_progress / completed / 历史 cancelled 一个不剩）
          2. is_from_his=False（HIS 同步患者外部仍存在，不允许本地软删）

        孤儿档案才会触发软删；老患者复诊场景下条件 1 不成立，本方法 no-op 返回 False。

        注意：本方法只设字段、不 commit——外层 cancel 方法会一起 commit，
        保证"接诊状态机改 + 患者软删"在同一个事务里要么都成要么都回滚。
        """
        from app.models.patient import Patient

        # 1. 是否还有其他 encounter？只要有一条非当前的就不是孤儿
        other_enc = (await self.db.execute(
            select(Encounter.id)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.id != current_encounter_id,
            )
            .limit(1)
        )).scalar_one_or_none()
        if other_enc is not None:
            return False

        # 1.5 名下还挂着临床数据就不算「孤儿」（2026-08-14 第八轮审计修复）
        #
        # 原先「孤儿」只判「除本接诊外没有别的接诊」。可医生给新病人建档后，
        # 影像科完全可能已经在这次接诊里传了一套 CT 并发布了报告；这时医生发现
        # 患者信息录错、点「取消接诊」，档案就被软删了——而 imaging_studies 那行
        # 仍在、patient_id 指向一个查不到的患者、影像科工作列表照样列出它、
        # Orthanc 里那套带患者姓名的 DICOM 原样保留。更糟的是已发布的 study
        # 禁止删除（pacs_reports 有 409 守卫），这套孤儿影像连影像科都清不掉。
        # 而全仓没有任何一处把 is_deleted 写回 False，也没有"已删档案"列表或
        # 恢复入口——误点一次就永久失联，只能重新建档，老档案带着 PHI 留在库里。
        # 判定收紧：名下有影像/检验/语音任一，就保留档案（不删总比删错强，
        # 空档案顶多是一条无用记录，删掉却不可逆）。
        from app.models.imaging import ImagingStudy
        from app.models.lab_report import LabReport
        from app.models.voice_record import VoiceRecord

        has_imaging = (await self.db.execute(
            select(ImagingStudy.id).where(ImagingStudy.patient_id == patient_id).limit(1)
        )).scalar_one_or_none()
        if has_imaging is not None:
            logger.info(
                "encounter.cancel: 患者名下有影像，保留档案不软删 patient_id=%s",
                patient_id,
            )
            return False

        # 检验/语音挂在接诊维度，本接诊即将取消，查的是它名下的
        has_clinical = (await self.db.execute(
            select(LabReport.id)
            .where(LabReport.encounter_id == current_encounter_id)
            .limit(1)
        )).scalar_one_or_none() or (await self.db.execute(
            select(VoiceRecord.id)
            .where(VoiceRecord.encounter_id == current_encounter_id)
            .limit(1)
        )).scalar_one_or_none()
        if has_clinical is not None:
            logger.info(
                "encounter.cancel: 接诊名下有检验/语音，保留患者档案 patient_id=%s",
                patient_id,
            )
            return False

        # 2. 取患者本体，校验来源 + 标软删
        patient = (await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),  # 已软删则跳过（幂等）
            )
        )).scalar_one_or_none()
        if patient is None:
            return False  # 患者不存在或已软删，no-op
        if patient.is_from_his:
            return False  # HIS 来源，外部仍有效，不动

        patient.is_deleted = True
        patient.deleted_at = _dt.now()
        patient.deleted_by = operator_doctor_id
        # 软删患者留痕（2026-08-13 第二轮审计修复）：取消接诊会联动软删刚建的
        # 孤儿患者档案，原先零审计——档案从列表消失后无从追溯是谁、何时、
        # 因哪次取消而删。等保 2.0 要求 PHI 生命周期可追溯。
        from app.services.audit_service import log_action

        await log_action(
            action="soft_delete_patient",
            user_id=operator_doctor_id,
            resource_type="patient", resource_id=patient_id,
            detail="取消接诊联动软删孤儿患者档案（该患者仅此一次接诊且非 HIS 来源）",
        )
        return True
