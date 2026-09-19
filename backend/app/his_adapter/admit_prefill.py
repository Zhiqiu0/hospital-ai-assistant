# -*- coding: utf-8 -*-
"""HIS 接诊推送·问诊预填（admit_service 拆分件，2026-09-19）。

纯机械搬移，零逻辑改动。把推送里的体征/主诉等预填进 InquiryInput
（体征出生理极限的丢弃并留痕）。被 admit_service.process_admit 调用；
admit_service 保留同名 re-export。
"""
import logging

from datetime import datetime as _dt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.his_adapter.models import AdmitPushRequest
from app.models.patient import Patient

logger = logging.getLogger(__name__)

# 预填的体征键（与 InquiryInput 列一一对应）
_VITALS_KEYS = ("temperature", "pulse", "respiration", "bp_systolic",
                "bp_diastolic", "spo2", "height", "weight")


async def _prefill_from_push(
    db: AsyncSession, encounter_id: str, patient_id: str, payload: AdmitPushRequest
) -> None:
    """把推送里的选填体征/档案预填进工作台（规范 3.1，2026-08-13 补接）。

    落点分两处，与前端读取位置对齐：
      - vitals.*        → InquiryInput（工作台左侧「生命体征快速录入」直接显示）
      - allergy/past    → 患者档案 profile（PatientProfileCard 显示，纵向跟随患者）

    安全边界：
      - 档案**只填空缺**，绝不覆盖我方已有值——我们的档案是医生确认过的，
        HIS 推来的可能是陈旧数据，覆盖等于用旧值抹掉医生的确认。
      - 预填失败不影响接诊建立（体征是锦上添花，接诊本身是命门），只记 warning。
    """
    from app.models.encounter import InquiryInput

    vitals = payload.vitals
    vitals_data = {
        k: (getattr(vitals, k) or "").strip()
        for k in _VITALS_KEYS
    } if vitals else {}
    vitals_data = {k: v for k, v in vitals_data.items() if v}
    # 生理极限预检（2026-08-29 第七轮审计）：厂商推"体温 365"（漏小数点）、
    # 身高体重错位等出界值单独丢弃并留痕，其余字段照填——绝不因体征拒收
    # 接诊（与 birth_date 解析失败同哲学）。口径与问诊/住院路径共用 vital_limits。
    from app.services.vital_limits import parse_vital_number, vital_out_of_range
    dropped = [k for k, v in vitals_data.items() if vital_out_of_range(k, v)]
    for k in dropped:
        logger.warning(
            "his_admit.prefill_vitals: %s=%r 超生理极限已丢弃 encounter=%s",
            k, vitals_data.pop(k), encounter_id)
    # 血压交叉预检（2026-08-29 第八轮回归修复）：各自在界内但收缩≤舒张
    # （80/120 错位形态）若照填，医生此后每次整表保存都会撞后端交叉校验
    # 422 被卡死——预填口径必须与保存校验口径一致，错位对丢弃留痕
    _sys = parse_vital_number(vitals_data.get("bp_systolic"))
    _dia = parse_vital_number(vitals_data.get("bp_diastolic"))
    if _sys is not None and _dia is not None and _sys <= _dia:
        logger.warning(
            "his_admit.prefill_vitals: 血压 %s/%s 收缩≤舒张（疑似错位）已丢弃 encounter=%s",
            vitals_data.pop("bp_systolic"), vitals_data.pop("bp_diastolic"), encounter_id)

    try:
        if vitals_data:
            db.add(InquiryInput(encounter_id=encounter_id, version=1, **vitals_data))
            await db.commit()
            logger.info("his_admit.prefill_vitals: encounter=%s 字段=%s",
                        encounter_id, ",".join(sorted(vitals_data)))

        # 档案字段：我方为空 → 直接填；我方已有且不同 → 挂待处理提示，绝不覆盖
        profile_patch = {
            "allergy_history": (payload.allergy_history or "").strip(),
            "past_history": (payload.past_history or "").strip(),
        }
        profile_patch = {k: v for k, v in profile_patch.items() if v}
        if profile_patch:
            # 行锁（2026-08-14 第七轮审计 #20）：档案是「读 JSONB → Python 合并 →
            # 整体写回」。update_profile 早在第二轮就为此加了 with_for_update，
            # 唯独 HIS 预填这条路径漏了——医生正在档案卡上改过敏史时 HIS 推来一条
            # 接诊，两边各自读到旧快照、后提交的把先提交的抹掉，医生刚填的过敏史
            # 就这么没了。process_admit 顶上的 advisory lock 只按 visit_id 串行，
            # 挡不住"同一患者的不同就诊"或"医生手改 vs HIS 推送"。
            patient = (await db.execute(
                select(Patient).where(Patient.id == patient_id).with_for_update()
            )).scalar_one_or_none()
            if patient is not None:
                profile = dict(patient.profile or {})
                changed = False
                for field, value in profile_patch.items():
                    entry = dict(profile.get(field) or {})
                    existing = entry.get("value")
                    # ── 区分「从没填过」与「医生特意清空」（2026-08-14 审计 #19）──
                    #
                    # 原判断是 `if not existing`，而医生把过敏史清空时
                    # update_profile 写进去的是 {"value": "", updated_at, updated_by}
                    # ——一条**有医生署名**的空值，语义是"已核实，无"。
                    # 空字符串是假值，于是下面直接用 HIS 的陈旧值填了回去，
                    # 医生特意做的删除被无声撤销：他刚确认患者不对青霉素过敏，
                    # HIS 那条老记录又冒回来了。
                    # 只有**整条不存在**才算空缺；已有署名的空值走下面的差异提示。
                    doctor_cleared = bool(entry) and entry.get("updated_at") is not None
                    if not existing and not doctor_cleared:
                        # 我方空缺 → 直接填（复诊首次拿到 HIS 档案的常见情况）
                        profile[field] = {
                            "value": value,
                            "updated_at": _dt.now().isoformat(),
                            "updated_by": None,  # 来源是 HIS 推送，非某个医生手填
                        }
                        changed = True
                        continue
                    # existing 走到这里可能是 ""（医生特意清空）甚至 None，
                    # 统一兜一层，别让一条畸形档案把整个接诊预填打挂
                    if (existing or "").strip() == value:
                        # 两边一致：清掉可能残留的旧提示，不打扰医生
                        if entry.pop("his_pending", None) is not None:
                            profile[field] = entry
                            changed = True
                        continue
                    # 两边不一致（2026-08-13）：既不能用 HIS 陈旧值覆盖医生确认过的内容，
                    # 也不能默默丢弃 HIS 的更新——过敏史漏一项会出用药事故。
                    # 挂成待处理提示，由医生在档案卡上看到差异后自己决定采纳/忽略。
                    entry["his_pending"] = {
                        "value": value,
                        "pushed_at": _dt.now().isoformat(),
                    }
                    profile[field] = entry
                    changed = True
                if changed:
                    patient.profile = profile
                    flag_modified(patient, "profile")
                    await db.commit()
                    # 失效档案缓存（2026-08-13 第五轮审计修复）：档案有 5 分钟
                    # Redis 缓存，写完不失效的话 HIS 推来的过敏史/既往史更新
                    # 最长 5 分钟对医生不可见——他可能正好在这窗口里开药。
                    # 患者档案的所有其他写路径（update_profile/confirm/resolve_his）
                    # 都调了这个，唯独 HIS 预填这条漏了。
                    from app.services.patient_cache import _invalidate_patient_cache
                    await _invalidate_patient_cache(patient_id)
                    logger.info("his_admit.prefill_profile: patient=%s 字段=%s",
                                patient_id, ",".join(sorted(profile_patch)))
    except Exception:
        # 预填失败绝不能连累接诊建立（接诊在则医生还能自己录，接诊没了就啥都没了）
        logger.exception("his_admit.prefill_failed: encounter=%s", encounter_id)
        await db.rollback()
