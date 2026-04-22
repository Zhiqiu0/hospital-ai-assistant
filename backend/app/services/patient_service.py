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

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientProfileUpdate, PatientUpdate

# 档案字段列表：用于序列化 profile 和批量赋值
PROFILE_FIELDS = (
    "past_history",
    "allergy_history",
    "family_history",
    "personal_history",
    "current_medications",
    "marital_history",
    "menstrual_history",
    "religion_belief",
)


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
        """按姓名或患者编号搜索患者，支持分页。

        Args:
            keyword:   搜索关键词（模糊匹配姓名 / 患者编号），空字符串返回全部
            page:      页码（从 1 开始）
            page_size: 每页条数

        Returns:
            {"total": int, "items": [患者响应字典, ...]}
        """
        offset = (page - 1) * page_size
        query = select(Patient)
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
        result = await self.db.execute(query.offset(offset).limit(page_size))
        items = result.scalars().all()
        return {"total": total, "items": [self._to_response(p) for p in items]}

    async def create(self, data: PatientCreate) -> dict:
        """创建新患者档案。

        使用 exclude_none=True 避免将 None 字段写入数据库，
        保留数据库字段的默认值（如 is_from_his=False）。
        """
        patient = Patient(**data.model_dump(exclude_none=True))
        self.db.add(patient)
        await self.db.commit()
        await self.db.refresh(patient)  # 刷新获取数据库生成的 id、created_at 等
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
        return self._to_response(patient)

    async def get_by_id(self, patient_id: str) -> dict:
        """按 UUID 查询单个患者。

        Raises:
            HTTPException(404): 患者不存在。
        """
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        return self._to_response(patient)

    def _to_response(self, patient: Patient) -> dict:
        """将 Patient ORM 对象转换为标准响应字典。

        计算 age 字段（非 DB 字段，由 birth_date 实时计算）。
        考虑了是否已过生日（同年月日比较），确保年龄计算准确。
        """
        age = None
        if patient.birth_date:
            today = date.today()
            age = today.year - patient.birth_date.year - (
                (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)
            )
        return {
            "id": patient.id,
            "patient_no": patient.patient_no,
            "name": patient.name,
            "gender": patient.gender,
            "age": age,
            "phone": patient.phone,
            "birth_date": patient.birth_date,
        }

    # ── 患者档案（Longitudinal Record）─────────────────────────────────────────
    async def get_profile(self, patient_id: str) -> dict:
        """取患者档案（过敏/既往/用药等纵向数据）。"""
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        return {
            **{f: getattr(patient, f"profile_{f}") for f in PROFILE_FIELDS},
            "updated_at": patient.profile_updated_at,
        }

    async def update_profile(self, patient_id: str, data: PatientProfileUpdate) -> dict:
        """更新患者档案。只覆盖传入的字段，未传的保留旧值。"""
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")

        changed = False
        for field in PROFILE_FIELDS:
            new_val = getattr(data, field)
            if new_val is None:
                continue
            attr = f"profile_{field}"
            if getattr(patient, attr) != new_val:
                setattr(patient, attr, new_val)
                changed = True

        if changed:
            patient.profile_updated_at = datetime.now()
            await self.db.commit()
            await self.db.refresh(patient)

        return await self.get_profile(patient_id)
