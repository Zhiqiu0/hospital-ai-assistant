"""病历草稿保存 mixin（services/_medical_record_draft.py）

从 medical_record_service 拆出（Round 5: 超标文件拆分）。含两类"不签发"的保存：
  - auto_save_draft : 医生编辑器高频 auto-save，原地 UPDATE 当前 doctor_edited
                      版本；当前版本若是 AI 产物则先新开一版（AI 原文不可变）
  - save_ai_draft   : AI 生成完毕的批次保存，upsert record 并追加新版本
由 MedicalRecordService 组合，依赖宿主类提供 self.db。
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.medical_record import MedicalRecord, RecordVersion


class MedicalRecordDraftMixin:
    """病历草稿保存（依赖宿主类提供 self.db）。"""

    async def _is_inpatient(self, encounter_id: str) -> bool:
        """该接诊是否住院。

        住院一次接诊天然有多份同类型文书（15 份日常病程、3 份查房……），
        「上一份已签发」不代表「这一份不能写」；门急诊一次接诊一份病历，
        已签发就是真的不能再改。两条草稿路径都要按这个区分，
        与签发路径（_medical_record_sign）保持同一口径。
        """
        from app.models.encounter import Encounter

        visit_type = (await self.db.execute(
            select(Encounter.visit_type).where(Encounter.id == encounter_id)
        )).scalar_one_or_none()
        return visit_type == "inpatient"

    async def _next_record_no(self, encounter_id: str, record_type: str) -> int:
        """同类型文书的下一个序号（与 _medical_record_sign 同一算法）。"""
        return (await self.db.execute(
            select(func.coalesce(func.max(MedicalRecord.record_no), 0) + 1).where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            )
        )).scalar() or 1

    async def auto_save_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
        expected_updated_at: Optional[datetime] = None,
        recorded_at: Optional[datetime] = None,
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
        # NUL 剥离（2026-08-28 极端字符审计）：PG JSONB 拒收 \u0000，
        # PDF 复制粘贴偶带 NUL → 每次保存都 DataError 500。剥掉无信息损失。
        content = content.replace("\x00", "")
        # 首行并发防重（2026-08-28 完整性审计）：该 (enc,type) 还没有行时
        # record 级行锁锁不到东西，AI 落库与 auto-save 并发会各插一行同号文书。
        # 与 quick_save 同口径先锁 encounter 行，把首行插入串行化；
        # 三元组唯一约束（k20260828recuniq）作最后兜底。
        from app.models.encounter import Encounter as _Enc
        await self.db.execute(
            select(_Enc.id).where(_Enc.id == encounter_id).with_for_update()
        )
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
            # ── 住院多份同类型文书（2026-08-14 第八轮审计修复）────────────────
            #
            # 住院一次接诊天然有多份同类型文书（15 份日常病程、3 份查房……）。
            # 原先这里无条件 403「病历已签发，不可再编辑」——医生 8/2 签发第 1 份
            # 病程后，8/3 写第 2 份时每 5 秒的 auto-save 全部 403；而前端
            # useAutoSaveDraft 把 403 判为「永久性拒绝」，清空失败队列并提示
            # 「该病历已签发，草稿不再自动保存」，此后整段住院期间该类型的草稿
            # **一个字都不落库**，只有签发那一刻才有数据。
            # 签发路径（_medical_record_sign）第六轮就已经有「住院遇 submitted
            # 就新起一份 record_no」的分支，这两条草稿路径当时没跟上。
            # 这里对齐：住院 → 置空走下面的新建分支；门急诊一次接诊一份，
            # 仍然 403（那才是真正的"已签发不可改"）。
            if await self._is_inpatient(encounter_id):
                record = None
            else:
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
            # 首次 auto-save：建 record + 第一个 version。
            # source 修正（2026-08-12 复检）：走到这里说明没有任何 AI 生成在先
            # （AI 生成走 save_ai_draft 会先建 record），是纯手写起点——原来
            # 统一标 'ai_generated' 会让纯手写病历被误计入 AI 采纳统计。
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=1,
                # 同类型第几份（住院多份文书的区分键，与签发路径同一算法）
                record_no=await self._next_record_no(encounter_id, record_type),
                # 临床相关时间；与 created_at 差得多即判为补记（见 record_time.py）
                recorded_at=recorded_at,
            )
            self.db.add(record)
            await self.db.flush()
            version = RecordVersion(
                medical_record_id=record.id,
                version_no=1,
                content={"text": content},
                source="doctor_edited",
                triggered_by=user_id,
            )
            self.db.add(version)
        else:
            # 已有 record：UPDATE 当前 version 的 content（不增加 version_no）——
            # 但 **AI 生成的版本不可覆写**（2026-08-12 复检修复）：原实现把医生
            # 编辑直接覆写进 ai_generated 版本行，AI 原始草稿被逐步冲掉，签发时
            # 的采纳度对比基线（最近一版 AI 草稿）变成医生 5 秒前自己的文本，
            # ai_similarity 恒≈1、整条指标失真。现改为：当前版本是 AI 产物时
            # 先新开一版 doctor_edited 再覆写，AI 原文成为不可变历史；后续高频
            # auto-save 覆写的都是这版 doctor_edited，版本数只 +1 不爆炸。
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
                    source="doctor_edited",
                    triggered_by=user_id,
                )
                self.db.add(current_version)
            elif current_version.source.startswith("ai_"):
                # AI 版本冻结：另起一版承接医生编辑
                new_no = record.current_version + 1
                self.db.add(RecordVersion(
                    medical_record_id=record.id,
                    version_no=new_no,
                    content={"text": content},
                    source="doctor_edited",
                    triggered_by=user_id,
                ))
                record.current_version = new_no
            else:
                current_version.content = {"text": content}
            record.status = "editing"

        # 记录时间同步（2026-08-28 时间审计修复）：原先 recorded_at 只在首次
        # 建 record 的分支写入，更新分支从不碰——而住院时间轴"新建文书"是先以
        # now 建档、医生随后才把 DatePicker 改成实际时点（如补写昨天的查房），
        # 改动全部落进更新分支被静默丢弃：补记标识（is_late_entry）永远不成立，
        # record_time.py 头注宣称的整条补记链路没有一环生效。
        if recorded_at is not None:
            record.recorded_at = recorded_at

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
        # NUL 剥离（2026-08-28 极端字符审计）：PG JSONB 拒收 \u0000，
        # PDF 复制粘贴偶带 NUL → 每次保存都 DataError 500。剥掉无信息损失。
        content = content.replace("\x00", "")
        # 首行并发防重（2026-08-28 完整性审计）：该 (enc,type) 还没有行时
        # record 级行锁锁不到东西，AI 落库与 auto-save 并发会各插一行同号文书。
        # 与 quick_save 同口径先锁 encounter 行，把首行插入串行化；
        # 三元组唯一约束（k20260828recuniq）作最后兜底。
        from app.models.encounter import Encounter as _Enc
        await self.db.execute(
            select(_Enc.id).where(_Enc.id == encounter_id).with_for_update()
        )
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
            # 住院例外（2026-08-14 第八轮审计修复）：住院一次接诊有多份同类型
            # 文书，"上一份已签发"不等于"这一份不能写"。原先无条件 saved=False，
            # 而 record_gen_v2_service 不检查返回值也不报错 → AI 生成的第 2 份
            # 病程只活在浏览器 store 里，刷新即丢，医生毫不知情。
            if await self._is_inpatient(encounter_id):
                record = None
            else:
                return {
                    "record_id": record.id,
                    "version_no": record.current_version,
                    "saved": False,
                }

        if record is None:
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=0,
                record_no=await self._next_record_no(encounter_id, record_type),
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
        # commit 后 ORM 属性过期，异步访问会炸（MissingGreenlet）——refresh 后再读
        await self.db.refresh(record)

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)
        return {
            "record_id": record.id,
            "version_no": new_version_no,
            "saved": True,
            # 前端 auto-save 乐观锁基线同步用（2026-08-21 第四轮走查：生成落库后
            # 前端基线不知道这次写入，下一次 auto-save 必假 409）
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
