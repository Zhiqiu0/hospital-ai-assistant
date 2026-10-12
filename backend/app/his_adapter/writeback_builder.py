"""把一次接诊的病历组装成 HIS 回写 payload。

数据来源：
  - Encounter.his_external_ref / visit_no / visit_type → 关联键、病历类型
  - 指定签发版本的 his_projection → record.* / vitals.* / diagnoses[]
  - 最新 RecordVersion.content → full_text（整段签发全文）

红线：临床字段来自最终正文的版本投影；空串明确清空，不能回落旧问诊。
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.his_adapter.record_projection import projection_for_writeback
from app.his_adapter._projection_parse import ProjectionError
from app.models.medical_record import MedicalRecord, RecordVersion

def _parse_record_text(content: Any) -> str:
    """RecordVersion.content → 全文（{"text":...} 取 text，纯字符串原样，其它空串）。"""
    if isinstance(content, dict):
        return content.get("text") or ""
    if isinstance(content, str):
        return content
    return ""


async def build_writeback_payload(
    db: AsyncSession, encounter_id: str, app_version: str = "1.0.0",
    record_id: Optional[str] = None,
) -> dict:
    """组装一次接诊的病历回写 payload（dict，结构见接口规范 3.2）。

    record_id（2026-08-29 第五轮审计·回写粒度下沉）：指定要回写**哪一份文书**。
    此前回写从头到尾只带 encounter_id，builder 执行时重挑"最新已签发的一份"，
    住院多文书场景三连炸：连续签发只推最新一份、早签的那份静默漏推；
    失败被后续成功覆盖；管理员修订早期文书后重推的仍是最新文书。
    签发钩子/修订重推现在都精确传本次签发/修订的 record_id；
    不传（对账兜底、旧调用）保持原"最新已签发优先"行为。
    """
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise ValueError(f"encounter not found: {encounter_id}")

    # 精确选择文书版本，不再读取可变的最新问诊。
    _where = [RecordVersion.version_no == MedicalRecord.current_version]
    if record_id:
        # 精确定位本次签发/修订的那份文书；仍校验 encounter 归属防串接诊
        _where += [MedicalRecord.id == record_id,
                   MedicalRecord.encounter_id == encounter_id]
    else:
        _where += [MedicalRecord.encounter_id == encounter_id]
    picked = (await db.execute(
        select(RecordVersion, MedicalRecord)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .where(*_where)
        # 优先取「已签发」的那份（2026-08-13 第五轮审计修复）：
        # 原先只按 updated_at 倒序取最近更新的一份。住院一次接诊有入院记录/病程/
        # 出院小结等多份病历，医生刚签发出院小结、随后又碰了一下病程草稿，
        # 回写就会把那份草稿推给 HIS——回写的必须是刚签发的正式文书。
        .order_by(
            (MedicalRecord.status == "submitted").desc(),
            desc(MedicalRecord.submitted_at),
            desc(MedicalRecord.updated_at),
        )
        .limit(1)
    )).first()
    row, record_row = (picked[0], picked[1]) if picked else (None, None)
    full_text = _parse_record_text(row.content) if row else ""

    his_ref = encounter.his_external_ref or {}

    # 责任医师工号取**签发快照**（2026-08-31 审计 M3·中高）：
    # his_external_ref.doctor_code 在转科改派时会被就地覆盖，而回写 payload
    # 每次重新组装（对账补投、修订重推都会重来）——8/2 A 医生签发的入院记录
    # 若在 8/10 转科后由对账补投，HIS 病案里的责任医师就变成了 B。
    # 医院的法定病案是 HIS 那一份，署名必须锁定签发瞬间的那个人。
    # patient_snapshot.doctor_id 是签发时冻结且进签名哈希的，是权威来源。
    signer_code = ""
    _snap = getattr(record_row, "patient_snapshot", None) if record_row is not None else None
    _signer_id = (_snap or {}).get("doctor_id") if isinstance(_snap, dict) else None
    if _signer_id:
        from app.models.user import DoctorCode, User

        _row = (await db.execute(
            select(DoctorCode.code)
            .where(DoctorCode.user_id == _signer_id)
            .order_by(DoctorCode.id)
            .limit(1)
        )).scalar_one_or_none()
        if not _row:
            _row = (await db.execute(
                select(User.employee_no).where(User.id == _signer_id)
            )).scalar_one_or_none()
        signer_code = _row or ""
    visit_id = his_ref.get("his_visit_no") or encounter.visit_no or ""
    # 回写的 record_type 取**病历自己的类型**（2026-08-13 第五轮审计修复）：
    # 原先只按接诊 visit_type 三分，住院会落进 else 被当成 outpatient 推给 HIS——
    # 而规范里住院有 admission_note / course_record / discharge_record / op_record
    # 等专属类型，推错类型 HIS 侧会归档到错误的文书栏目。
    # 病历表上就存着真实类型，直接用它；查不到再按接诊类型兜底。
    record_type = (
        record_row.record_type
        if record_row is not None and record_row.record_type
        else ("emergency" if encounter.visit_type == "emergency" else "outpatient")
    )

    # ── record_no：住院多份同类型文书的区分键（2026-08-14 第八轮审计）──────────
    #
    # 接口规范 §2.5 白纸黑字：「回写以（visit_id + record_type + record_no）为
    # 幂等键——该键对应的文书在 HIS 尚无则新建，已有则覆盖更新」，§3.2 请求体
    # 也列了这个字段。第六轮的 i20260814recordno 迁移专门为此在我方库里加了
    # record_no 并让签发时正确递增（1..15），**但回写 payload 从头到尾没带上它**。
    # 后果：住院 15 份日常病程，每次回写的 (visit_id, record_type) 逐字相同，
    # HIS 按规范只能认定是同一份文书被反复覆盖——我方库里 15 份都在，
    # HIS 病案里只剩最后一天那份。而医院的**法定病案是 HIS 那一份**。
    # 门急诊各只有一份，规范允许 record_no 可空，故仅在有值时下发。
    # 转字符串下发（2026-08-14 规范一致性核对修复）：规范 3.2 把 record_no 声明为
    # string，而这里原样下发 Python int → JSON number。厂商用强类型 DTO
    # （Java / C# 严格模式）反序列化会直接抛类型错误整包拒收；而它是幂等键的
    # 一段，类型不一致直接影响病案是新建还是覆盖，不能靠对方宽松解析碰运气。
    # 规范里 visit_id / vitals.* 一律是 string，这里跟着统一。
    _no = getattr(record_row, "record_no", None) if record_row is not None else None
    record_no = str(_no) if _no is not None else None

    # 无签发文书时不得伪造由旧问诊拼装的回写内容。
    if row is None or record_row.status != "submitted":
        raise ValueError("HIS回写失败：未找到已签发文书")
    try:
        projection = projection_for_writeback(row.content, record_type)
    except ProjectionError as exc:
        # 仅在已精确找到文书后附状态键；不存在/串接诊的record_id不能污染其它文书。
        exc.record_key = f"{record_type}:{record_no}" if record_no is not None else None
        raise

    payload: dict = {
        "visit_id": visit_id,
        "record_type": record_type,
        # 幂等键第三段（见上方 record_no 说明）。
        "is_tcm": projection["is_tcm"],
        "status": "draft",
        "record": projection["record"],
        "vitals": projection["vitals"],
        "diagnoses": projection["diagnoses"],

        "meta": {
            "source": "mediscribe_ai",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # 接诊推送落的 doctor_code（2026-08-11 联动后唯一来源；
            # 旧 embed 会话的 his_doctor_no 兜底已随 embed 下线删除，无存量数据）
            # 签发医师工号优先（见上方 signer_code 注释），取不到才回落接诊上的值
            "doctor_code": signer_code or his_ref.get("doctor_code") or "",
            "app_version": app_version,
        },
    }
    # 缺失标识不下发，避免误清医生工号；正文record字段则以空串表达终稿删除。
    # vitals依规范特别条款仅发非空值，未测值不更新HIS已有测量结果。
    if record_no is not None:
        payload["record_no"] = record_no
    if full_text:
        payload["full_text"] = full_text
    if not payload["meta"].get("doctor_code"):
        payload["meta"].pop("doctor_code", None)

    return payload
