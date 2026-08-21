# -*- coding: utf-8 -*-
"""诊断条目服务（services/diagnosis_service.py，2026-08-21 阶段1a）。

职责：
  - list_by_encounter : 按接诊拉全部诊断条目（主诊断优先、组内按 sort_order）
  - replace_all       : 整组替换写入 + 业务校验 + 文本投影双写

双写过渡策略（阶段1 的风险隔离关键）：
  diagnoses 表是权威；每次写入后把条目渲染成文本投影，UPDATE 回
  inquiry_inputs 最新版的旧三列（western/tcm_disease/tcm_syndrome_diagnosis），
  LLM 生成 / 渲染器 / QC 引擎现有文本链路零改动继续工作。投影是派生数据，
  不递增 inquiry 版本号（版本语义保留给医生输入）。

业务校验（法定语义，写入即挡）：
  - tcm_disease / tcm_syndrome 各至多一条（中医主病主证各一）
  - 全列表至多一条 is_primary；一条都没标且列表非空时自动补：第一条西医
    （无西医则整体第一条）为主——与 HIS 回写 builder 既有隐式规则一致，
    保证"主诊断唯一"这一病案首页硬约束在数据层恒成立
"""
import logging

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Diagnosis, InquiryInput
from app.schemas.diagnosis import DiagnosisItemIn

logger = logging.getLogger(__name__)


def render_diagnosis_projection(items: list[DiagnosisItemIn]) -> dict[str, str]:
    """把条目列表渲染成旧三列文本投影（双写过渡用，也是回填/测试的单一实现）。

    western 多条时编号串接（"1.高血压病；2.2型糖尿病"），单条时纯名——
    与医院真实病历"其他诊断逐条编号"的书写习惯一致；主诊断恒排首位。
    """
    western = sorted(
        (i for i in items if i.category == "western"),
        key=lambda i: (not i.is_primary, i.sort_order),
    )
    tcm_d = next((i for i in items if i.category == "tcm_disease"), None)
    tcm_s = next((i for i in items if i.category == "tcm_syndrome"), None)

    if len(western) > 1:
        western_text = "；".join(f"{n}.{it.name}" for n, it in enumerate(western, 1))
    elif western:
        western_text = western[0].name
    else:
        western_text = ""

    # 住院入院诊断合成行（admission_diagnosis 是住院问诊/渲染的输入源）：
    # 与走查实测的真实书写格式一致（"中医诊断：X — Y\n西医诊断：..."）。
    # 门诊接诊该列本就不消费，写入无副作用——投影函数不感知 visit_type，保持纯函数
    from app.services.ai._render_common import _merge_tcm_diagnosis

    admission_parts: list[str] = []
    if tcm_d or tcm_s:
        merged = _merge_tcm_diagnosis(tcm_d.name if tcm_d else "", tcm_s.name if tcm_s else "")
        admission_parts.append(f"中医诊断：{merged}")
    if western_text:
        admission_parts.append(f"西医诊断：{western_text}")

    return {
        "western_diagnosis": western_text,
        "tcm_disease_diagnosis": tcm_d.name if tcm_d else "",
        "tcm_syndrome_diagnosis": tcm_s.name if tcm_s else "",
        "admission_diagnosis": "\n".join(admission_parts),
    }


# 条目类别 → 字典 code_type（HIS 回写侧 TCD_* 统一映射为 "GB95"，见 writeback_builder）
CATEGORY_TO_CODE_TYPE = {
    "western": "ICD10",
    "tcm_disease": "TCD_DIS",
    "tcm_syndrome": "TCD_SYN",
}


class DiagnosisService:
    """诊断条目 CRUD（依赖注入 AsyncSession）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _auto_fill_codes(self, items: list[DiagnosisItemIn]) -> None:
        """名称精确匹配字典补码（原地修改 items；确定性匹配，配不上留空）。"""
        from app.models.encounter import DiagnosisCode

        pending = [i for i in items if not i.code and i.name]
        if not pending:
            return
        names = {i.name for i in pending}
        rows = (await self.db.execute(
            select(DiagnosisCode.code, DiagnosisCode.name, DiagnosisCode.code_type)
            .where(DiagnosisCode.name.in_(names))
        )).all()
        # (code_type, name) → code；同名多码（极少）不补，避免猜错
        by_key: dict[tuple[str, str], list[str]] = {}
        for code, name, ctype in rows:
            by_key.setdefault((ctype, name), []).append(code)
        for item in pending:
            expect_type = CATEGORY_TO_CODE_TYPE.get(item.category)
            codes = by_key.get((expect_type, item.name), [])
            if len(codes) == 1:
                item.code = codes[0]
                item.code_type = expect_type

    async def list_by_encounter(self, encounter_id: str) -> list[Diagnosis]:
        """拉取接诊全部诊断条目：主诊断优先，组内按 sort_order。"""
        rows = (await self.db.execute(
            select(Diagnosis)
            .where(Diagnosis.encounter_id == encounter_id)
            .order_by(Diagnosis.is_primary.desc(), Diagnosis.sort_order, Diagnosis.created_at)
        )).scalars().all()
        return list(rows)

    async def replace_all(
        self,
        encounter_id: str,
        items: list[DiagnosisItemIn],
        added_by: str | None = None,
    ) -> list[Diagnosis]:
        """整组替换写入（删旧插新，同一事务）+ 校验 + 文本投影双写。"""
        # ── 业务校验 ────────────────────────────────────────────────
        for cat in ("tcm_disease", "tcm_syndrome"):
            if sum(1 for i in items if i.category == cat) > 1:
                label = "中医疾病诊断" if cat == "tcm_disease" else "中医证候诊断"
                raise HTTPException(status_code=422, detail=f"{label}至多一条")
        primaries = [i for i in items if i.is_primary]
        if len(primaries) > 1:
            raise HTTPException(status_code=422, detail="主要诊断只能有一条")
        if items and not primaries:
            # 自动补主：第一条西医（无西医则整体第一条）——与 HIS 回写既有规则一致
            fallback = next((i for i in items if i.category == "western"), items[0])
            fallback.is_primary = True

        # ── 确定性自动补码（2026-08-21 阶段2）────────────────────────
        # 无编码的条目按「名称精确匹配字典」补 code/code_type——只做确定性
        # 匹配（同名即同码），配不上留空给医生在选择器里选；绝不做模糊猜码
        #（编错码比不编码危害大，医保拒付追责口径是"谁填报谁负责"）。
        await self._auto_fill_codes(items)

        # ── 删旧插新（整组替换，避免逐条 diff 的一致性坑）────────────
        await self.db.execute(delete(Diagnosis).where(Diagnosis.encounter_id == encounter_id))
        rows: list[Diagnosis] = []
        for it in items:
            row = Diagnosis(
                encounter_id=encounter_id,
                category=it.category,
                name=it.name,
                code=it.code or None,
                code_type=it.code_type or None,
                is_primary=it.is_primary,
                admission_condition=it.admission_condition,
                sort_order=it.sort_order,
                added_by=added_by,
            )
            self.db.add(row)
            rows.append(row)

        # ── 文本投影双写（派生数据，不递增 inquiry 版本号）──────────
        projection = render_diagnosis_projection(items)
        latest_id = (await self.db.execute(
            select(InquiryInput.id)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(InquiryInput.version.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest_id is not None:
            await self.db.execute(
                update(InquiryInput).where(InquiryInput.id == latest_id).values(**projection)
            )

        await self.db.commit()
        for row in rows:
            await self.db.refresh(row)

        # 工作台快照缓存失效——否则 60s 内刷新页面拿到旧诊断列表
        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)
        return rows
