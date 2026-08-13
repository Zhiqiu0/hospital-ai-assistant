"""患者档案（纵向记录）mixin（services/_patient_profile.py）

从 patient_service 拆出（Round: 超标文件拆分）。含患者档案（过敏/既往/用药等
JSONB 纵向数据）的读取、更新、字段确认三个接口及序列化辅助。由 PatientService
组合，依赖宿主类提供 self.db。
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models.patient import Patient
from app.schemas.patient import PatientProfileUpdate
from app.services.patient_cache import _PROFILE_KEY, _PROFILE_TTL, _invalidate_patient_cache
from app.services.redis_cache import redis_cache

# 档案字段列表：JSONB 重构后共 7 个，月经史已移除
# （月经史是时变信息，每次接诊在 inquiry_inputs.menstrual_history 重填）
PROFILE_FIELDS = (
    "past_history",
    "allergy_history",
    "family_history",
    "personal_history",
    "current_medications",
    "marital_history",
    "religion_belief",
)


class PatientProfileMixin:
    """患者档案读写（依赖宿主类提供 self.db）。"""

    # ── 患者档案（Longitudinal Record，JSONB 实现）────────────────────────────
    async def get_profile(self, patient_id: str) -> dict:
        """取患者档案（过敏/既往/用药等纵向数据），带 Redis 缓存。

        返回结构（扁平化兼容旧 API + 新增 fields_meta）：
            {
              "past_history":     "高血压5年",
              "allergy_history":  "否认",
              ...
              "religion_belief":  None,
              "updated_at":       "2026-04-25T...",   # 各字段最大值聚合
              "fields_meta": {
                "past_history": {"updated_at": "...", "updated_by": "doc_xxx"},
                ...
              }
            }

        缓存 5 分钟；update_profile / confirm_profile_field 写时主动失效。
        """
        cache_key = _PROFILE_KEY.format(pid=patient_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        # 软删患者一律视为不存在，避免任意路径把已删档案带回前端
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            )
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        data = self._serialize_profile(patient.profile or {})
        await redis_cache.set_json(cache_key, data, ttl=_PROFILE_TTL)
        return data

    async def update_profile(
        self,
        patient_id: str,
        data: PatientProfileUpdate,
        doctor_id: Optional[str] = None,
    ) -> dict:
        """更新患者档案。只覆盖传入的字段，未传的保留旧值。

        每个被修改字段独立刷新 updated_at + updated_by；其他字段元数据不变。
        值未实际改变（前后相同）的字段不更新元数据，避免医生只是查看时也"被算确认"——
        想主动确认走 confirm_profile_field 接口。
        """
        # 行锁（2026-08-13 第二轮审计修复）：档案是「读 JSONB → Python 合并 →
        # 整体写回」，两个医生同时改同一患者的不同字段时，后提交者用自己读到的
        # 旧快照覆盖，先提交的那次修改被静默丢弃——过敏史这种字段被回退是临床
        # 风险。加 with_for_update 把同一患者的档案写入串行化（读-改-写全程持锁
        # 到事务提交）。跨患者互不影响，不构成吞吐瓶颈。
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            ).with_for_update()
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")

        profile_data = dict(patient.profile or {})  # 浅拷贝避免直接改 ORM dict
        now_iso = datetime.now().isoformat()
        changed = False

        for field in PROFILE_FIELDS:
            new_val = getattr(data, field, None)
            if new_val is None:
                continue  # 未传字段保持原状
            old_entry = profile_data.get(field) or {}
            if old_entry.get("value") == new_val:
                continue  # 值未变，跳过（避免误刷新元数据）
            profile_data[field] = {
                "value": new_val,
                "updated_at": now_iso,
                "updated_by": doctor_id,
            }
            changed = True

        if changed:
            patient.profile = profile_data
            # JSONB 字段被原地修改时 SQLAlchemy 不会自动标记 dirty，必须显式 flag_modified
            flag_modified(patient, "profile")
            await self.db.commit()
            await self.db.refresh(patient)
            await _invalidate_patient_cache(patient_id)

        return await self.get_profile(patient_id)

    async def confirm_profile_field(
        self,
        patient_id: str,
        field: str,
        doctor_id: Optional[str] = None,
    ) -> dict:
        """医生点"✓ 仍准确"按钮：仅刷新该字段 updated_at + updated_by，不动 value。

        对应 FHIR verificationStatus: confirmed 概念——医生看了档案确认仍然准确就让
        "X 天前确认"重新计时。如果该字段从未录入过，不操作直接返回。
        """
        if field not in PROFILE_FIELDS:
            raise HTTPException(status_code=400, detail=f"不支持的档案字段: {field}")

        # 同 update_profile：确认动作也是读-改-写整份 JSONB，需行锁串行化，
        # 否则与并发的档案修改互相覆盖（2026-08-13 第二轮审计修复）
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            ).with_for_update()
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")

        profile_data = dict(patient.profile or {})
        if field not in profile_data:
            # 字段从未录入，没法"确认"
            return await self.get_profile(patient_id)

        entry = dict(profile_data[field] or {})
        entry["updated_at"] = datetime.now().isoformat()
        entry["updated_by"] = doctor_id
        profile_data[field] = entry
        patient.profile = profile_data
        flag_modified(patient, "profile")
        await self.db.commit()
        await self.db.refresh(patient)
        await _invalidate_patient_cache(patient_id)
        return await self.get_profile(patient_id)

    async def resolve_his_pending(
        self,
        patient_id: str,
        field: str,
        adopt: bool,
        doctor_id: Optional[str] = None,
    ) -> dict:
        """裁决 HIS 待处理值（2026-08-13）：adopt=True 采纳，False 忽略。

        采纳 → HIS 的值成为档案正式值，updated_by 记为做出决定的医生
               （是他判断该采纳的，责任归属清晰）。
        忽略 → 只清掉待处理标记，保留我方原值，updated_at 一并刷新
               （医生看过并做了判断，等价于一次"仍准确"确认）。
        两种情况都清除 his_pending，避免提示反复出现。
        """
        if field not in PROFILE_FIELDS:
            raise HTTPException(status_code=400, detail=f"不支持的档案字段: {field}")

        # 同 update_profile：读-改-写整份 JSONB，需行锁串行化
        result = await self.db.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.is_deleted.is_(False),
            ).with_for_update()
        )
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")

        profile_data = dict(patient.profile or {})
        entry = dict(profile_data.get(field) or {})
        pending = entry.pop("his_pending", None)
        if not pending:
            # 没有待处理差异（可能已被别的医生处理过）→ 幂等返回当前档案
            return await self.get_profile(patient_id)

        if adopt:
            entry["value"] = pending.get("value")
        entry["updated_at"] = datetime.now().isoformat()
        entry["updated_by"] = doctor_id
        profile_data[field] = entry
        patient.profile = profile_data
        flag_modified(patient, "profile")
        await self.db.commit()
        await self.db.refresh(patient)
        await _invalidate_patient_cache(patient_id)
        return await self.get_profile(patient_id)

    @staticmethod
    def _serialize_profile(profile_data: dict) -> dict:
        """JSONB profile 扁平化为 API 响应。

        老 API 形式：{past_history, allergy_history, ..., updated_at}
        新增 fields_meta：{past_history: {updated_at, updated_by}, ...}
        前端老代码读 profile.past_history 仍然有效；新增字段元数据走 fields_meta。
        """
        flat: dict = {}
        meta: dict = {}
        max_updated_at: Optional[str] = None
        for f in PROFILE_FIELDS:
            entry = profile_data.get(f) or {}
            flat[f] = entry.get("value")
            updated_at = entry.get("updated_at")
            # HIS 待处理值（2026-08-13）：HIS 推来的值与我方不一致时挂在这里，
            # 前端档案卡显示差异 + 采纳/忽略按钮，绝不静默覆盖也绝不静默丢弃。
            his_pending = entry.get("his_pending")
            if updated_at or his_pending:
                meta[f] = {
                    "updated_at": updated_at,
                    "updated_by": entry.get("updated_by"),
                    "his_pending_value": (his_pending or {}).get("value"),
                    "his_pending_at": (his_pending or {}).get("pushed_at"),
                }
                if updated_at and (max_updated_at is None or updated_at > max_updated_at):
                    max_updated_at = updated_at
        flat["updated_at"] = max_updated_at
        flat["fields_meta"] = meta
        return flat
