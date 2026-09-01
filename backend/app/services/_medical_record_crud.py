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

        Raises:
            HTTPException(409): 该 (接诊, 病历类型) 已有签发过的病历。
        """
        # 已签发不可绕过（2026-08-13 第五轮审计修复）：quick_save 对门急诊有
        # "已签发就直接返回"的幂等守卫，但本端点完全不查——为同一个
        # (encounter_id, record_type) 再建一条 draft 就能重新走一遍签发流程，
        # 产出第二份正式病历。而下游按 (encounter_id, record_type) 取病历时
        # order_by(updated_at desc)，展示与回写都会指向后建的那份，
        # 等于"已签发不可修改"被整体绕开。住院同类型多份文书靠 record_no 区分，
        # 不走这条零字段的建档路径。
        existing = (await self.db.execute(
            select(MedicalRecord).where(
                MedicalRecord.encounter_id == data.encounter_id,
                MedicalRecord.record_type == data.record_type,
                MedicalRecord.status == "submitted",
            ).limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="该接诊的这类病历已签发，不能再建新的；需要更正请走病历修订",
            )

        # record_no 复用统一计算（2026-08-28 完整性审计）：原先恒用列默认值 1，
        # 对已有同类型文书的住院接诊调一次就造出重复 (enc,type,1)——HIS 回写
        # 幂等键撞车互相覆盖。与草稿/签发路径同口径先锁 encounter 行串行化，
        # 再算 next_no；三元组唯一约束（k20260828recuniq）作最后兜底。
        from sqlalchemy import func

        await self.db.execute(
            select(Encounter.id).where(Encounter.id == data.encounter_id)
            .with_for_update()
        )
        next_no = (await self.db.execute(
            select(func.coalesce(func.max(MedicalRecord.record_no), 0) + 1).where(
                MedicalRecord.encounter_id == data.encounter_id,
                MedicalRecord.record_type == data.record_type,
            )
        )).scalar() or 1
        record = MedicalRecord(
            encounter_id=data.encounter_id,
            record_type=data.record_type,
            record_no=next_no,
            # 记录时间兜底（2026-09-02）：见 _medical_record_draft 处的说明。
            # 用 func.now() 而非 datetime.now()，与 created_at 同一时钟源。
            recorded_at=func.now(),
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
        # 行锁查询：联表 Encounter 校验归属权 + 加锁防并发。
        # of=MedicalRecord 必须显式指定（2026-08-31 并发矩阵审计）：
        # PG 的 FOR UPDATE 不带 OF 会锁住 FROM 里**所有**表的行，本查询
        # 驱动表是 medical_records（PK 命中），实际锁序变成 record→encounter，
        # 与全仓约定的 encounter→record（quick_save/auto_save_draft/save_ai_draft/
        # create 四处）正好相反 → 对同一 (encounter, record) 并发即死锁环，
        # PG 检测后 abort 其一，医生侧 500 且该次写入丢失。
        # 只锁病历行既消除倒置，也不再无谓阻塞签发/取消/出院。
        result = await self.db.execute(
            select(MedicalRecord)
            .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
            .where(MedicalRecord.id == record_id, Encounter.doctor_id == user_id)
            .with_for_update(of=MedicalRecord)
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
