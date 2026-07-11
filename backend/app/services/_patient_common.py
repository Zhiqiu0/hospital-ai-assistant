"""患者共享读辅助 mixin（services/_patient_common.py）

从 patient_service 拆出（Round: 超标文件拆分）。放 ORM→响应字典转换、
批量住院状态查询这两个被多个 mixin（查询 / 单查）复用的底层辅助方法。
由 PatientService 组合，方法依赖宿主类提供的 self.db。
"""
from sqlalchemy import select

from app.models.patient import Patient
from app.utils.age import calc_age


class PatientCommonMixin:
    """患者共享读辅助（依赖宿主类提供 self.db）。"""

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
            # ── 病案首页扩展字段（2026-05-16 加）─────────────────────────
            # 供前端导出 Word / 打印 / 查看病历时渲染病案首页；后端 patient
            # 表本来就存了这些字段，只是 schema 之前没暴露。
            "id_card": patient.id_card,
            "address": patient.address,
            "ethnicity": patient.ethnicity,
            "marital_status": patient.marital_status,
            "occupation": patient.occupation,
            "workplace": patient.workplace,
            "contact_name": patient.contact_name,
            "contact_phone": patient.contact_phone,
            "contact_relation": patient.contact_relation,
            "blood_type": patient.blood_type,
        }
