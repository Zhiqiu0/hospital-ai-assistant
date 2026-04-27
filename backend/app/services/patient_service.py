"""
患者服务（services/patient_service.py）

职责：
  封装患者档案的 CRUD 操作和智能查重逻辑：
  - find_existing : 按身份证号或 (姓名+手机/出生日期) 查找已有患者
  - search        : 按姓名/患者编号模糊搜索，支持分页
  - create        : 创建新患者档案
  - update        : 更新患者信息
  - get_by_id     : 按 UUID 查询单个患者

查重策略（find_existing）：
  优先级 1：身份证号精确匹配（最可靠，18位唯一）
  优先级 2：手机号 + 姓名 精确匹配
  优先级 3：姓名 + 出生日期 精确匹配
  以上三种都匹配不到则视为新患者，由调用方创建。
"""

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.patient import Patient
from app.utils.age import calc_age
from app.schemas.patient import PatientCreate, PatientProfileUpdate, PatientUpdate
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

# Redis 缓存 key：基本信息和档案分开缓存，避免一改 profile 把基本信息也失效
_BASIC_KEY = "patient:basic:{pid}"
_PROFILE_KEY = "patient:profile:{pid}"
_BASIC_TTL = 300   # 5 分钟，基本信息变动很少
_PROFILE_TTL = 300


async def _invalidate_patient_cache(patient_id: str) -> None:
    """患者写操作（update / update_profile）后失效缓存。"""
    await redis_cache.delete(
        _BASIC_KEY.format(pid=patient_id),
        _PROFILE_KEY.format(pid=patient_id),
    )
    # 患者基本信息变更也会影响搜索结果，把搜索缓存全清掉
    await redis_cache.delete_prefix("patient:search:")


class PatientService:
    """患者数据访问服务，封装患者 CRUD 及去重逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_existing(
        self,
        *,
        id_card: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        birth_date: date | None = None,
    ) -> dict | None:
        """查找系统中已存在的患者档案，用于防止重复建档。

        查找顺序（找到即返回，不继续后续匹配）：
          1. id_card 非空 → 按身份证号精确匹配
          2. phone + name 非空 → 按手机号+姓名精确匹配
          3. name + birth_date 非空 → 按姓名+出生日期精确匹配

        Returns:
            找到则返回患者响应字典；未找到则返回 None。
        """
        patient = None

        # 优先用身份证号（精度最高，18位唯一标识）
        if id_card:
            result = await self.db.execute(select(Patient).where(Patient.id_card == id_card))
            patient = result.scalar_one_or_none()

        # 其次用手机号+姓名（适合没有身份证的场景）
        if not patient and phone and name:
            result = await self.db.execute(
                select(Patient).where(Patient.phone == phone, Patient.name == name)
            )
            patient = result.scalar_one_or_none()

        # 最后用姓名+出生日期（精度较低，同名同日出生有碰撞风险，仅作兜底）
        if not patient and name and birth_date:
            result = await self.db.execute(
                select(Patient).where(Patient.name == name, Patient.birth_date == birth_date)
            )
            patient = result.scalar_one_or_none()

        return self._to_response(patient) if patient else None

    async def search(self, keyword: str, page: int, page_size: int):
        """按姓名或患者编号搜索患者，支持分页（带 Redis 缓存）。

        缓存 30 秒；create / update 时清整个 patient:search:* 前缀。
        新建/复诊弹窗在用户输入时高频触发，命中缓存可显著降低 DB 负载。
        每条响应附带 has_active_inpatient（是否有进行中的住院接诊），
        前端 PatientHistoryDrawer 据此显示"在院中 / 已出院"状态标签。
        """
        cache_key = f"patient:search:{keyword}:{page}:{page_size}"
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        offset = (page - 1) * page_size
        # 子查询：每个患者最近一次接诊时间（用于"按最近就诊时间倒序"排序）
        # 比"按建档时间排序"更贴医生工作流——昨天来过的患者大概率今天也想找
        from app.models.encounter import Encounter as _Enc
        last_visit_subq = (
            select(
                _Enc.patient_id.label("pid"),
                func.max(_Enc.visited_at).label("last_visit_at"),
            )
            .group_by(_Enc.patient_id)
            .subquery()
        )
        query = select(Patient).outerjoin(
            last_visit_subq, Patient.id == last_visit_subq.c.pid
        )
        if keyword:
            query = query.where(
                or_(
                    Patient.name.ilike(f"%{keyword}%"),
                    Patient.patient_no.ilike(f"%{keyword}%"),
                )
            )
        # 先查总数（用于分页计算），再查当前页数据
        count_result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()
        # 排序：最近就诊时间倒序为主；从未接诊（last_visit_at IS NULL）的回落到建档时间倒序
        query = query.order_by(
            last_visit_subq.c.last_visit_at.desc().nullslast(),
            Patient.created_at.desc(),
        )
        result = await self.db.execute(query.offset(offset).limit(page_size))
        items = result.scalars().all()
        # 一次性查这批患者的住院状态（active + 历史，一次 SQL 拿两个集合）
        active_set, ever_set = await self._fetch_inpatient_state([p.id for p in items])
        data = {
            "total": total,
            "items": [
                self._to_response(
                    p,
                    has_active_inpatient=p.id in active_set,
                    has_any_inpatient_history=p.id in ever_set,
                )
                for p in items
            ],
        }
        await redis_cache.set_json(cache_key, data, ttl=30)
        return data

    async def _fetch_inpatient_state(
        self, patient_ids: list[str]
    ) -> tuple[set[str], set[str]]:
        """批量查给定 patient_ids 的住院状态，一次 SQL 返回两个集合：

        Returns:
            (active_ids, ever_admitted_ids)
              - active_ids: 当前有进行中住院接诊（in_progress）→ 显示"在院中"
              - ever_admitted_ids: 历史上有过任何住院记录（含已出院）→ 用于区分
                "已出院"和"从未住过院"。空集合 = 纯门诊患者，不打住院相关 Tag。
        """
        if not patient_ids:
            return set(), set()
        from app.models.encounter import Encounter
        result = await self.db.execute(
            select(Encounter.patient_id, Encounter.status)
            .where(
                Encounter.patient_id.in_(patient_ids),
                Encounter.visit_type == "inpatient",
            )
        )
        active: set[str] = set()
        ever: set[str] = set()
        for pid, status in result:
            ever.add(pid)
            if status == "in_progress":
                active.add(pid)
        return active, ever

    async def create(self, data: PatientCreate) -> dict:
        """创建新患者档案。

        使用 exclude_none=True 避免将 None 字段写入数据库，
        保留数据库字段的默认值（如 is_from_his=False）。
        """
        patient = Patient(**data.model_dump(exclude_none=True))
        self.db.add(patient)
        await self.db.commit()
        await self.db.refresh(patient)  # 刷新获取数据库生成的 id、created_at 等
        # 新患者会出现在搜索结果中，把搜索缓存清掉避免读到过期列表
        await redis_cache.delete_prefix("patient:search:")
        return self._to_response(patient)

    async def update(self, patient_id: str, data: PatientUpdate) -> dict:
        """更新患者信息（只更新非 None 的字段）。

        Raises:
            HTTPException(404): 患者不存在。
        """
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        # exclude_none=True 确保只更新传入的字段，不覆盖其他字段
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(patient, field, value)
        await self.db.commit()
        await self.db.refresh(patient)
        # 失效该患者的 Redis 缓存（基本信息变更后下次读重新查 DB）
        await _invalidate_patient_cache(patient_id)
        return self._to_response(patient)

    async def get_by_id(self, patient_id: str) -> dict:
        """按 UUID 查询单个患者（带 Redis 缓存）。

        缓存 5 分钟；update / update_profile 写时主动失效。
        """
        cache_key = _BASIC_KEY.format(pid=patient_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        active_set, ever_set = await self._fetch_inpatient_state([patient_id])
        data = self._to_response(
            patient,
            has_active_inpatient=patient_id in active_set,
            has_any_inpatient_history=patient_id in ever_set,
        )
        await redis_cache.set_json(cache_key, data, ttl=_BASIC_TTL)
        return data

    def _to_response(
        self,
        patient: Patient,
        has_active_inpatient: bool = False,
        has_any_inpatient_history: bool = False,
    ) -> dict:
        """将 Patient ORM 对象转换为标准响应字典。

        age 字段非 DB 列，由 utils.calc_age 从 birth_date 实时算出。
        has_active_inpatient / has_any_inpatient_history 由调用方批量查询后传入；
        find_existing 等不关心住院状态的场景默认 False，前端会"什么 Tag 都不打"。

        三态前端判断：
          active=true                          → 在院中（绿）
          active=false && history=true         → 已出院（灰）
          history=false                        → 不打住院相关 Tag（纯门诊或新患者）
        """
        return {
            "id": patient.id,
            "patient_no": patient.patient_no,
            "name": patient.name,
            "gender": patient.gender,
            "age": calc_age(patient.birth_date),
            "phone": patient.phone,
            "has_active_inpatient": has_active_inpatient,
            "has_any_inpatient_history": has_any_inpatient_history,
            "birth_date": patient.birth_date,
        }

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

        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
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
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
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

        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
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
            if updated_at:
                meta[f] = {
                    "updated_at": updated_at,
                    "updated_by": entry.get("updated_by"),
                }
                if max_updated_at is None or updated_at > max_updated_at:
                    max_updated_at = updated_at
        flat["updated_at"] = max_updated_at
        flat["fields_meta"] = meta
        return flat
