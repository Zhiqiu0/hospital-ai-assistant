"""患者建档/更新 mixin（services/_patient_write.py）

从 patient_service 拆出（Round: 超标文件拆分）。含新建患者档案（含身份证查重）、
更新患者基本信息两个写接口。由 PatientService 组合，依赖宿主类提供 self.db 及
共享辅助 _to_response（PatientCommonMixin）。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services._patient_validators import _assert_id_card_birth_date_consistent
from app.services.patient_cache import _invalidate_patient_cache
from app.services.redis_cache import redis_cache
from app.utils.pinyin import compute_pinyin


class PatientWriteMixin:
    """患者建档 / 更新（依赖宿主类提供 self.db）。"""

    async def create(self, data: PatientCreate, *, commit: bool = True) -> dict:
        """创建新患者档案。

        commit 参数（2026-06-11 治本）：
          True（默认）——方法内部 commit，保持原有行为；
          False——只 flush 拿主键不提交，由调用方把"建患者 + 后续写入"包进
          同一事务（embed/start 用，防止接诊创建失败时留下孤儿患者档案）。

        使用 exclude_none=True 避免将 None 字段写入数据库，
        保留数据库字段的默认值（如 is_from_his=False）。
        姓名拼音索引 name_pinyin / name_pinyin_initials 由本方法回填——
        创建路径都走这里（quick-start / 手动建档 / HIS 同步），单一入口好控。

        身份证去重（2026-05-27 加）：
          alembic b8c9d0e1f2a3 给 patients.id_card 加了 partial unique index
          （活跃患者唯一）。这里 service 层先显式查重 + 抛 409，给前端更清晰的错误
          信息，避免依赖 DB IntegrityError 的乱码细节；最后还有 IntegrityError
          兜底，应对并发 race（同 id_card 两个请求几乎同时走到 INSERT）。
        """
        # 跨字段一致性：身份证内嵌的出生日期（第 7-14 位）必须与 birth_date 字段一致
        # 防止医生打字错位 / LLM 抽取错位导致主索引污染
        _assert_id_card_birth_date_consistent(data.id_card, data.birth_date)

        # 显式查重：已有活跃同 id_card 患者直接 409，让调用方决定（打开已有 / 改身份证）
        if data.id_card:
            dup = await self.db.execute(
                select(Patient.id, Patient.name).where(
                    Patient.id_card == data.id_card,
                    Patient.is_deleted.is_(False),
                )
            )
            existing = dup.first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "patient_id_card_conflict",
                        "message": f"该身份证号已存在患者档案（{existing.name}）",
                        "existing_patient_id": existing.id,
                    },
                )

        patient = Patient(**data.model_dump(exclude_none=True))
        # 同步生成拼音索引，供搜索框拼音/首字母/混拼匹配
        patient.name_pinyin, patient.name_pinyin_initials = compute_pinyin(patient.name)
        self.db.add(patient)
        try:
            if commit:
                await self.db.commit()
            else:
                # flush 同样会触发 partial unique index 校验，IntegrityError 兜底依然有效
                await self.db.flush()
        except IntegrityError as e:
            # 并发 race 兜底：上面查重和这里 commit 之间另一个请求恰好插入了同号
            # DB 的 partial unique index 会拦下来；这里回滚 + 重新查一次，转 409
            await self.db.rollback()
            # 只处理 id_card 唯一冲突，其他完整性错误原样抛
            if "uq_patients_id_card_active" not in str(e.orig):
                raise
            dup2 = await self.db.execute(
                select(Patient.id, Patient.name).where(
                    Patient.id_card == data.id_card,
                    Patient.is_deleted.is_(False),
                )
            )
            existing2 = dup2.first()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "patient_id_card_conflict",
                    "message": f"该身份证号已存在患者档案（{existing2.name if existing2 else '未知'}）",
                    "existing_patient_id": existing2.id if existing2 else None,
                },
            )
        await self.db.refresh(patient)  # 刷新获取数据库生成的 id、created_at 等
        # 新患者会出现在搜索结果中，把搜索缓存清掉避免读到过期列表
        await redis_cache.delete_prefix("patient:search:")
        return self._to_response(patient)

    async def update(self, patient_id: str, data: PatientUpdate) -> dict:
        """更新患者信息（只更新非 None 的字段）。

        姓名变更时同步刷新拼音索引——否则改名后老拼音还命中旧名拼音、新名搜不到。

        Raises:
            HTTPException(404): 患者不存在（含已软删情况）。
        """
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        # exclude_none=True 确保只更新传入的字段，不覆盖其他字段
        update_data = data.model_dump(exclude_none=True)
        # 跨字段一致性：取"更新后最终值"对比（仅改身份证保留旧 birth_date 的场景也覆盖）
        final_id_card = update_data.get("id_card", patient.id_card)
        final_birth_date = update_data.get("birth_date", patient.birth_date)
        _assert_id_card_birth_date_consistent(final_id_card, final_birth_date)

        # 改 id_card 时查重：避免把这个患者的身份证号改成跟别人重复
        # （新值跟原值一样不查；DB 也有 partial unique index 兜底）
        new_id_card = update_data.get("id_card")
        if new_id_card and new_id_card != patient.id_card:
            dup = await self.db.execute(
                select(Patient.id, Patient.name).where(
                    Patient.id_card == new_id_card,
                    Patient.is_deleted.is_(False),
                    Patient.id != patient_id,
                )
            )
            existing = dup.first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "patient_id_card_conflict",
                        "message": f"该身份证号已被另一患者档案（{existing.name}）占用",
                        "existing_patient_id": existing.id,
                    },
                )

        for field, value in update_data.items():
            setattr(patient, field, value)
        # 姓名变了就重算拼音索引（其他字段变更不影响拼音）
        if "name" in update_data:
            patient.name_pinyin, patient.name_pinyin_initials = compute_pinyin(patient.name)
        try:
            await self.db.commit()
        except IntegrityError as e:
            await self.db.rollback()
            if "uq_patients_id_card_active" in str(e.orig):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "patient_id_card_conflict",
                        "message": "该身份证号已被另一患者档案占用",
                    },
                )
            raise
        await self.db.refresh(patient)
        # 失效该患者的 Redis 缓存（基本信息变更后下次读重新查 DB）
        await _invalidate_patient_cache(patient_id)
        return self._to_response(patient)
