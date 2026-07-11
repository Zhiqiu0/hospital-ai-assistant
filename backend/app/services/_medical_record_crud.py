"""病历 CRUD 与版本 mixin（services/_medical_record_crud.py）

从 medical_record_service 拆出（Round 5: 超标文件拆分）。含病历的新建占位、
按 ID 查询（可附归属权校验）、医生编辑保存（递增版本 + 行锁）、以及
版本列表查询。由 MedicalRecordService 组合，依赖宿主类提供 self.db。
"""
from fastapi import HTTPException
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.schemas.medical_record import MedicalRecordCreate, RecordContentUpdate


class MedicalRecordCrudMixin:
    """病历 CRUD 与版本控制（依赖宿主类提供 self.db）。"""

    async def create(self, data: MedicalRecordCreate) -> MedicalRecord:
        """为接诊新建一条病历记录（初始状态 draft，内容为空）。

        每次 AI 生成病历时都会调用此方法先创建记录占位，
        之后由 AI 服务保存内容版本（source='ai_generated'）。
        """
        record = MedicalRecord(
            encounter_id=data.encounter_id,
            record_type=data.record_type,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_id(self, record_id: str, doctor_id: str | None = None) -> MedicalRecord:
        """按 ID 查询病历，可选附加归属权校验。

        Args:
            record_id: 病历 ID。
            doctor_id: 若传入，则同时校验该病历对应接诊的主治医生必须为此 ID，
                       防止医生 A 访问医生 B 的病历（越权访问）。

        Raises:
            HTTPException(403): 传入 doctor_id 但归属权不匹配（合并 "不存在" 和 "无权" 的响应，
                                 不暴露病历是否存在的信息）。
            HTTPException(404): 未传入 doctor_id 且病历不存在（管理员查询场景）。
        """
        if doctor_id:
            # 联表 Encounter 校验归属权，一次查询完成，避免二次 SELECT
            result = await self.db.execute(
                select(MedicalRecord)
                .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
                .where(MedicalRecord.id == record_id, Encounter.doctor_id == doctor_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=403, detail="病历不存在或无权访问")
            return record

        # 无归属权校验（管理员或内部调用场景）
        result = await self.db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="病历不存在")
        return record

    async def save_content(self, record_id: str, data: RecordContentUpdate, user_id: str):
        """医生编辑并保存病历内容，创建新版本。

        并发安全：使用 with_for_update() 行锁，防止两个请求同时写入时版本号冲突
        （例如两个标签页同时保存）。

        业务规则：
          - 已签发（status='submitted'）的病历不可再编辑，保障病历合法性。
          - 每次保存都追加一条 RecordVersion（source='doctor_edited'），不覆盖旧版本。

        Args:
            record_id: 病历 ID。
            data:      新内容（RecordContentUpdate 中的 content 字段，支持结构化 dict 或纯文本）。
            user_id:   操作医生 ID，写入版本的 triggered_by 字段，用于审计。

        Returns:
            {"ok": True, "version_no": 新版本号}
        """
        # 行锁查询：联表 Encounter 校验归属权 + 加锁防并发
        result = await self.db.execute(
            select(MedicalRecord)
            .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
            .where(MedicalRecord.id == record_id, Encounter.doctor_id == user_id)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=403, detail="病历不存在或无权修改")
        if record.status == "submitted":
            raise HTTPException(status_code=403, detail="病历已签发，不可修改")

        # 版本号递增并创建新版本记录
        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record_id,
            version_no=new_version_no,
            content=data.content,
            source="doctor_edited",   # 标记来源：医生手动编辑
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"     # 重置为编辑中（如曾被 AI 标为其他状态）
        await self.db.commit()
        # 病历变更，工作台快照失效
        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(record.encounter_id)
        return {"ok": True, "version_no": new_version_no}

    async def get_versions(self, record_id: str):
        """获取病历的所有版本列表（按版本号倒序）。

        用于版本回溯面板，展示"谁在什么时候用什么方式修改了病历"。
        只返回元数据（版本号、来源、时间），不返回内容，减少传输量。

        source 字段含义：
          - 'ai_generated'  : AI 首次生成
          - 'ai_polished'   : AI 润色后的版本
          - 'doctor_edited' : 医生手动编辑
          - 'doctor_signed' : 医生签发时保存的最终版本
        """
        result = await self.db.execute(
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record_id)
            .order_by(RecordVersion.version_no.desc())
        )
        versions = result.scalars().all()
        return {
            "items": [
                {
                    "version_no": v.version_no,
                    "source": v.source,
                    "created_at": v.created_at,
                }
                for v in versions
            ]
        }
