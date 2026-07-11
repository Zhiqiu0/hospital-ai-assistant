"""病历草稿保存 mixin（services/_medical_record_draft.py）

从 medical_record_service 拆出（Round 5: 超标文件拆分）。含两类"不签发"的保存：
  - auto_save_draft : 医生编辑器高频 auto-save，UPDATE 当前版本 content，不新增版本
  - save_ai_draft   : AI 生成完毕的批次保存，upsert record 并追加新版本
由 MedicalRecordService 组合，依赖宿主类提供 self.db。
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select

from app.models.medical_record import MedicalRecord, RecordVersion


class MedicalRecordDraftMixin:
    """病历草稿保存（依赖宿主类提供 self.db）。"""

    async def auto_save_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
        expected_updated_at: Optional[datetime] = None,
    ) -> dict:
        """医生编辑器输入 / auto-save 防抖触发——把当前内容覆写到 draft 版本。

        与 save_ai_draft 区别：save_ai_draft 是 AI 生成完毕的"批次保存"，每次创建
        新 RecordVersion；本方法面向高频 5 秒一次的 auto-save，**不创建新版本**，
        只 UPDATE 当前 version 的 content——避免半小时几百个版本的爆炸式增长。

        乐观锁：调用方传入 expected_updated_at 时校验记录版本号；不匹配返 409。
        前端单设备场景一般不会触发；多设备并发编辑时这是唯一的冲突保护。

        Returns:
            {"record_id": ..., "version_no": ..., "updated_at": ISO 字符串}
            updated_at 给前端下次 auto-save 带回作为乐观锁凭证。
        Raises:
            HTTPException(409): 乐观锁冲突，调用方应提示"内容已被其他设备修改"
            HTTPException(403): 病历已签发，不可再编辑
        """
        result = await self.db.execute(
            select(MedicalRecord)
            .where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            )
            .order_by(MedicalRecord.updated_at.desc())
            .with_for_update()
        )
        record = result.scalars().first()

        if record is not None and record.status == "submitted":
            raise HTTPException(status_code=403, detail="病历已签发，不可再编辑")

        # 乐观锁校验（只在传入预期值时启用——AI 生成那次首发不需要）
        if expected_updated_at is not None and record is not None and record.updated_at:
            # DB updated_at 是 naive；expected_updated_at 由 pydantic 解析客户端字符串，
            # 一旦前端回传带 Z/时区偏移的 ISO 串就会变成 aware，naive>aware 直接抛
            # TypeError → auto-save 500。这里把 aware 归一化成 naive 再比，杜绝该崩溃。
            expected = expected_updated_at
            if expected.tzinfo is not None:
                expected = expected.replace(tzinfo=None)
            # 数据库 updated_at 可能比预期值更新（其他设备已写过）→ 拒绝
            if record.updated_at > expected:
                raise HTTPException(
                    status_code=409,
                    detail="病历已被其他设备修改，请刷新后重试",
                )

        if record is None:
            # 首次 auto-save：建 record + 第一个 version
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=1,
            )
            self.db.add(record)
            await self.db.flush()
            version = RecordVersion(
                medical_record_id=record.id,
                version_no=1,
                content={"text": content},
                source="ai_generated",  # auto-save 起点常常是 AI 生成的，统一标这个
                triggered_by=user_id,
            )
            self.db.add(version)
        else:
            # 已有 record：UPDATE 当前 version 的 content（关键：不增加 version_no）
            ver_result = await self.db.execute(
                select(RecordVersion)
                .where(
                    RecordVersion.medical_record_id == record.id,
                    RecordVersion.version_no == record.current_version,
                )
                .with_for_update()
            )
            current_version = ver_result.scalar_one_or_none()
            if current_version is None:
                # 异常情况：record 存在但当前 version 不存在——创建一条
                current_version = RecordVersion(
                    medical_record_id=record.id,
                    version_no=record.current_version,
                    content={"text": content},
                    source="ai_generated",
                    triggered_by=user_id,
                )
                self.db.add(current_version)
            else:
                current_version.content = {"text": content}
            record.status = "editing"

        # 强制刷新 record.updated_at——SQLAlchemy onupdate 只在字段实际改变时触发，
        # 但 auto-save 经常 status 还是 "editing"，等于不更新 updated_at；
        # 这会让乐观锁失效（多设备冲突时两边的 expected_updated_at 都对得上）。
        # 显式 set 确保每次 auto-save 都推进 updated_at。
        record.updated_at = datetime.now()

        await self.db.commit()
        await self.db.refresh(record)

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)

        return {
            "record_id": record.id,
            "version_no": record.current_version,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    async def save_ai_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
    ) -> dict:
        """AI 生成完毕保存草稿（不签发，不动接诊状态）。

        与 save_content 的差异：
          - save_content 要求 record_id 已知（医生编辑场景）
          - save_ai_draft 用 (encounter_id, record_type) upsert：
            * 该接诊该类型 record 不存在 → 创建一条 + 新版本
            * 已存在且非 submitted → 在原 record 上加新版本，状态保持 editing
            * 已签发（submitted）→ 跳过保存，返回原 record（不让 AI 覆盖签发病历）

        为什么必要：解决"AI 生成的病历只在前端 zustand store，logout 后清空 →
        DB 没数据可恢复 → 医生开心写一半的草稿全丢"的合规事故。

        Returns:
            {"record_id": ..., "version_no": ..., "saved": bool}
            saved=False 表示已签发跳过保存。
        """
        result = await self.db.execute(
            select(MedicalRecord)
            .where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            )
            .order_by(MedicalRecord.updated_at.desc())
            .with_for_update()
        )
        record = result.scalars().first()

        # 已签发病历不让 AI 覆盖（医生最终确认过的版本是法定证据）
        if record is not None and record.status == "submitted":
            return {"record_id": record.id, "version_no": record.current_version, "saved": False}

        if record is None:
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=0,
            )
            self.db.add(record)
            await self.db.flush()  # 拿到 record.id

        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},  # 与 quick_save 保持同一存储格式
            source="ai_generated",
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"
        await self.db.commit()

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)
        return {"record_id": record.id, "version_no": new_version_no, "saved": True}
