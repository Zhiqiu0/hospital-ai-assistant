"""工作台快照组装 mixin（services/_encounter_snapshot.py）

从 encounter_service 拆出（Round: 超标文件拆分）。一次性拼装前端恢复
接诊工作台所需的全量数据（患者/问诊/病历/语音/上次 AI 产物），带 Redis 缓存。
由 EncounterService 组合。
"""
from app.utils.age import calc_age
from fastapi import HTTPException
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import selectinload

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.voice_record import VoiceRecord
from app.services.encounter_cache import _SNAPSHOT_KEY, _SNAPSHOT_TTL
from app.services.encounter_serializers import (
    _serialize_inquiry,
    _serialize_record,
    _serialize_voice,
)
from app.services.redis_cache import redis_cache


class EncounterSnapshotMixin:
    """工作台快照组装（依赖宿主类提供 self.db）。"""

    async def get_workspace_snapshot(self, encounter_id: str, doctor_id: str) -> dict:
        """组装工作台完整快照（前端恢复接诊状态时调用）。

        查询内容：
          - Encounter（含 Patient）
          - 最新的 InquiryInput（问诊输入）
          - 所有 MedicalRecord（含最新版本内容）
          - 最新一条 VoiceRecord（语音录音）

        权限控制：
          只有接诊医生本人（doctor_id 匹配）才能访问，防止越权查看他人接诊。

        Raises:
            HTTPException(404): 接诊不存在或无权访问。

        缓存策略：
          5+ 张表关联，是工作台启动热路径。Redis 缓存 60s；保存 inquiry / 病历版本 /
          语音 / 接诊状态变化时由各 service 调 invalidate_encounter_snapshot 主动
          失效。注意：缓存 key 不带 doctor_id，但读时仍校验 doctor_id 才返回，
          避免把别的医生的快照当成命中。
        """
        cache_key = _SNAPSHOT_KEY.format(eid=encounter_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None and cached.get("_doctor_id") == doctor_id:
            # 命中缓存且 doctor_id 校验通过，返回时剥掉内部字段
            return {k: v for k, v in cached.items() if k != "_doctor_id"}
        # 缓存未命中或 doctor_id 不匹配，走 DB 查询（404 由权限层抛）

        # ── 1. 接诊 + 患者（含权限校验）──────────────────────────────────
        encounter = (await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.id == encounter_id, Encounter.doctor_id == doctor_id)
        )).scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="接诊记录不存在或无权访问")

        # ── 2. 最新一条问诊输入（按 updated_at 倒序取 1 条）────────────
        inquiry = (await self.db.execute(
            select(InquiryInput)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(desc(InquiryInput.updated_at))
            .limit(1)
        )).scalar_one_or_none()

        # ── 3. 病历 + 当前版本一次 LEFT JOIN 查回（消除 N+1）──────────
        # 原实现：N 条病历 → N+1 次查询；现在合并为 1 次。
        rows = (await self.db.execute(
            select(MedicalRecord, RecordVersion)
            .join(
                RecordVersion,
                and_(
                    RecordVersion.medical_record_id == MedicalRecord.id,
                    RecordVersion.version_no == MedicalRecord.current_version,
                ),
                isouter=True,
            )
            .where(MedicalRecord.encounter_id == encounter_id)
            .order_by(desc(MedicalRecord.updated_at), desc(MedicalRecord.submitted_at))
        )).all()
        record_items = [_serialize_record(record, version) for record, version in rows]

        # ── 4. 最新语音录音 ─────────────────────────────────────────────
        latest_voice = (await self.db.execute(
            select(VoiceRecord)
            .where(VoiceRecord.encounter_id == encounter_id)
            .order_by(desc(VoiceRecord.updated_at), desc(VoiceRecord.created_at))
            .limit(1)
        )).scalar_one_or_none()

        # ── 4.5 最新 AI 任务产物（QC issues + 追问/检查/诊断建议）────
        # 让 logout 重登 / 切设备时医生看到的不是空白，而是上次留下的 AI 产物
        latest_qc_issues, latest_ai_suggestions = await self._fetch_latest_ai_artifacts(encounter_id)

        # ── 5. 患者档案（PatientService.get_profile 内部 1 次查询）────
        # 延迟 import 避免 patient_service ↔ encounter_service 循环依赖。
        patient = encounter.patient
        patient_profile = None
        if patient:
            from app.services.patient_service import PatientService
            patient_profile = await PatientService(self.db).get_profile(patient.id)

        snapshot = {
            "encounter_id": encounter.id,
            "visit_type": encounter.visit_type,
            "status": encounter.status,
            # 病案首页需要完整字段（id_card/address/民族/婚姻/职业/紧急联系人等）；
            # 之前只返 4 个字段，导致前端导出 Word/打印病历时顶部首页缺信息。
            "patient": {
                "id": patient.id,
                "name": patient.name,
                "gender": patient.gender,
                "age": calc_age(patient.birth_date),
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
            } if patient else None,
            "patient_profile": patient_profile,
            "inquiry": _serialize_inquiry(inquiry, encounter),
            "is_first_visit": encounter.is_first_visit,
            "active_record": record_items[0] if record_items else None,
            "records": record_items,
            "latest_voice_record": _serialize_voice(latest_voice),
            # ★ 治本：把 AI 产物也带回去——logout 重登不丢质控/追问/检查/诊断
            "latest_qc_issues": latest_qc_issues,
            "latest_ai_suggestions": latest_ai_suggestions,
        }
        # 缓存附带 doctor_id 做二次校验，防止越权命中他人快照
        await redis_cache.set_json(
            cache_key,
            {**snapshot, "_doctor_id": doctor_id},
            ttl=_SNAPSHOT_TTL,
        )
        return snapshot

    async def _fetch_latest_ai_artifacts(
        self, encounter_id: str
    ) -> tuple[list[dict], dict]:
        """取该接诊最新一次 QC issues + 各类 AI 建议（追问/检查/诊断）。

        - QC：取最新一条 task_type='qc' 的 ai_task 关联的全部 qc_issues
        - 建议：按 task_type 各取最新一条 ai_task 的 output_result
                  inquiry / exam / diagnosis 三类各一份

        让 logout 重登 / 切设备 / 浏览器崩溃后医生仍能拿到上次跑的产物，
        不用重跑 LLM（省 token + 体验丝滑）。

        Returns:
            (qc_issues_list, ai_suggestions_dict)
            qc_issues_list 形如 [{"field_name":..., "issue_description":..., ...}]
            ai_suggestions_dict 形如 {"inquiry": {...}, "exam": {...}, "diagnosis": {...}}
            缺数据用空 list / 空 dict，前端能直接灌进 store
        """
        from app.models.medical_record import AITask, QCIssue
        # 最新 QC task
        latest_qc_task = (await self.db.execute(
            select(AITask)
            .where(AITask.encounter_id == encounter_id, AITask.task_type == "qc")
            .order_by(desc(AITask.created_at))
            .limit(1)
        )).scalar_one_or_none()
        qc_issues_list: list[dict] = []
        if latest_qc_task:
            issues = (await self.db.execute(
                select(QCIssue).where(QCIssue.ai_task_id == latest_qc_task.id)
            )).scalars().all()
            qc_issues_list = [
                {
                    "source": i.source,
                    "issue_type": i.issue_type,
                    "risk_level": i.risk_level,
                    "field_name": i.field_name,
                    "issue_description": i.issue_description,
                    "suggestion": i.suggestion,
                }
                for i in issues
            ]

        # 各类建议：按 task_type 各取最新一条
        ai_suggestions: dict = {}
        for task_type, key in [("inquiry", "inquiry"), ("exam", "exam"), ("diagnosis", "diagnosis")]:
            task = (await self.db.execute(
                select(AITask)
                .where(AITask.encounter_id == encounter_id, AITask.task_type == task_type)
                .order_by(desc(AITask.created_at))
                .limit(1)
            )).scalar_one_or_none()
            if task and task.output_result:
                ai_suggestions[key] = task.output_result

        return qc_issues_list, ai_suggestions
