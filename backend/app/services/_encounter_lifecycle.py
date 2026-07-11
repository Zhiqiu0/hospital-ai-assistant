"""接诊创建与查询 mixin（services/_encounter_lifecycle.py）

从 encounter_service 拆出（Round: 超标文件拆分）。含接诊的新建、
"是否已有进行中/已完成接诊"判断、其他医生未完成接诊查询、以及
"我的接诊列表 / 按 ID 查接诊"两个读接口。由 EncounterService 组合。
"""
from app.utils.age import calc_age
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.encounter import Encounter
from app.schemas.encounter import EncounterCreate
from app.services.encounter_cache import (
    _MY_ENCOUNTERS_KEY,
    _MY_ENCOUNTERS_TTL,
    invalidate_my_encounters,
)
from app.services.redis_cache import redis_cache


class EncounterLifecycleMixin:
    """接诊创建 + 查询（依赖宿主类提供 self.db）。"""

    async def create(self, data: EncounterCreate, doctor_id: str) -> Encounter:
        """新建接诊记录，关联患者和当前医生。

        Args:
            data:      接诊创建入参（患者 ID、就诊类型等）。
            doctor_id: 接诊医生的用户 ID。

        Returns:
            新创建的 Encounter ORM 对象。
        """
        encounter = Encounter(
            patient_id=data.patient_id,
            doctor_id=doctor_id,
            department_id=data.department_id,
            visit_type=data.visit_type,
            is_first_visit=data.is_first_visit,
            bed_no=data.bed_no,
            admission_route=data.admission_route,
            admission_condition=data.admission_condition,
        )
        self.db.add(encounter)
        await self.db.commit()
        await self.db.refresh(encounter)
        # 新接诊会出现在该医生的进行中列表里，失效缓存
        await invalidate_my_encounters(doctor_id)
        # 住院接诊会改变患者的 has_active_inpatient 字段，失效该患者基本信息 + 搜索缓存
        if data.visit_type == "inpatient":
            from app.services.patient_service import _invalidate_patient_cache
            await _invalidate_patient_cache(data.patient_id)
        return encounter

    async def find_in_progress(self, patient_id: str, doctor_id: str):
        """查询该医生对该患者是否已有进行中的接诊，有则返回，无则返回 None。"""
        result = await self.db.execute(
            select(Encounter)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == doctor_id,
                Encounter.status == "in_progress",
            )
            .order_by(Encounter.visited_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_completed_encounter(self, patient_id: str) -> bool:
        """该患者是否有任一已完成（status='completed'）接诊。

        2026-05-03 加：复诊判断改写依赖此方法——
          - 有 completed 接诊 → 复诊（is_first_visit=False）
          - 无 → 初诊（即使曾经有 in_progress / cancelled，也算初诊）
        语义上 completed 隐含"病历已签发"（门诊签发自动 completed；住院走出院流程
        completed），所以此判断比"是否有签发病历"更准确：撞 status 字段一个就够，
        不需要 join MedicalRecord 表。
        """
        result = await self.db.execute(
            select(Encounter.id)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.status == "completed",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_pending_by_other_doctors(
        self, patient_id: str, exclude_doctor_id: str
    ) -> list[dict]:
        """查询该患者除当前医生外，其他医生留下的 in_progress 接诊。

        用于 quick-start 返回 pending_encounters，前端弹 Modal 警示医生：
        "该患者还有医生 X 未完成接诊"。不阻断创建（值班/转交场景常见），
        仅提示让医生自行决策。

        返回字段：encounter_id / doctor_id / doctor_name / visit_type / visited_at
        """
        # 延迟 import 避免循环依赖（user 模型在别处也 import 本模块）
        from app.models.user import User

        result = await self.db.execute(
            select(
                Encounter.id,
                Encounter.doctor_id,
                Encounter.visit_type,
                Encounter.visited_at,
                User.real_name,
                User.username,
            )
            .join(User, Encounter.doctor_id == User.id)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id != exclude_doctor_id,
                Encounter.status == "in_progress",
            )
            .order_by(Encounter.visited_at.desc())
        )
        rows = result.all()
        return [
            {
                "encounter_id": r.id,
                "doctor_id": r.doctor_id,
                # real_name 可能为空（注册时 optional），fallback 到 username 保证有展示
                "doctor_name": r.real_name or r.username,
                "visit_type": r.visit_type,
                "visited_at": r.visited_at.isoformat() if r.visited_at else None,
            }
            for r in rows
        ]

    async def get_my_encounters(self, doctor_id: str, limit: int = 20):
        """获取当前医生进行中的接诊列表（带 Redis 缓存 30s）。

        Args:
            doctor_id: 医生用户 ID。
            limit:     返回条数上限，默认 20。

        Returns:
            接诊列表，每项含接诊基本信息和患者概况。
        """
        # 列表是医生工作台首屏，每次切回都重读；新建/关闭接诊时主动失效
        cache_key = _MY_ENCOUNTERS_KEY.format(doctor_id=doctor_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        result = await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))  # 预加载患者，避免 N+1
            .where(Encounter.doctor_id == doctor_id, Encounter.status == "in_progress")
            .order_by(Encounter.visited_at.desc())
            .limit(limit)
        )
        encounters = result.scalars().all()
        data = [
            {
                "encounter_id": e.id,
                "visit_type": e.visit_type,
                "status": e.status,
                "visited_at": e.visited_at.isoformat() if e.visited_at else None,
                "chief_complaint_brief": e.chief_complaint_brief,
                "patient": {
                    "id": e.patient.id,
                    "name": e.patient.name,
                    "gender": e.patient.gender,
                    # 历史此处只用 year 相减，未减去未过生日的修正——
                    # 与 snapshot/详情接口算法不一致会让同一患者在不同页显示差 1 岁，
                    # 统一走 calc_age 顺带修复
                    "age": calc_age(e.patient.birth_date),
                } if e.patient else None,
            }
            for e in encounters
        ]
        await redis_cache.set_json(cache_key, data, ttl=_MY_ENCOUNTERS_TTL)
        return data

    async def get_by_id(self, encounter_id: str) -> Encounter:
        """按 ID 查询接诊记录。

        Raises:
            HTTPException(404): 接诊记录不存在。
        """
        result = await self.db.execute(select(Encounter).where(Encounter.id == encounter_id))
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="就诊记录不存在")
        return encounter
