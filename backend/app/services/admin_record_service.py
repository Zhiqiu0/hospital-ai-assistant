"""
管理后台病历服务（app/services/admin_record_service.py）

2026-06-11 Round 5 迁移：业务逻辑从 app/api/v1/admin/records.py 下沉到 service 层，
路由层只保留请求解析 + 鉴权 + 调 service，行为零改变。

职责：
  - list_all_records : 分页查询所有已签发病历（4 表 JOIN：病历→接诊→患者/医生，
                       外联科室），附带病案首页快照与患者 fallback 字段
  - revise_record    : 管理员修订已签发病历——创建新 RecordVersion（旧版本永久保留）、
                       更新 current_version、写审计日志、失效接诊 snapshot 缓存

修订设计（合规要点）：
  已签发病历是法律文件，国家《病历书写基本规范》要求修正必须留痕。
  本系统的实现：
    - 不覆盖原版本，创建新 RecordVersion（version_no+1, source='admin_revise'）
    - 修订理由必填，写入 audit_logs.detail
    - record.current_version 指向新版本，但旧版本永久保留可查
    - 触发者（triggered_by）= 当前管理员账号
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from datetime import datetime

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.services.audit_service import log_action
from app.services.encounter_service import invalidate_encounter_snapshot

logger = logging.getLogger(__name__)


class AdminRecordService:
    """管理后台病历数据访问服务，封装全院病历列表查询与管理员修订逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all_records(
        self, page: int, page_size: int, doctor_id: str | None = None,
        search: str | None = None,
    ) -> dict:
        """委托列表查询模块，保持修订服务和搜索分页各自独立。"""
        from app.services.admin_record_query import list_all_records
        return await list_all_records(self.db, page, page_size, doctor_id, search)

    async def revise_record(
        self,
        record_id: str,
        content: str,
        revise_reason: str,
        current_user,
    ) -> dict:
        """管理员修订已签发病历：创建新 RecordVersion，旧版本保留供审计。

        流程：
          1. 校验病历存在
          2. 创建新 RecordVersion（version_no = current_version + 1）
          3. 更新 record.current_version 指向新版本
          4. 写 audit_log（含修订理由）
          5. 失效 snapshot 缓存让医生工作台拉到最新版本

        Args:
            record_id: 病历 ID。
            content: 完整的新病历正文（前端提交修订后的全文，不是 diff）。
            revise_reason: 修订理由（必填，写入 audit_logs，永久留痕）。
            current_user: 当前管理员（用于 triggered_by 与审计日志署名）。

        Raises:
            HTTPException(404): 病历不存在。
        """
        # 行锁（2026-08-13 第五轮审计修复）：同类写路径 save_content / quick_save
        # 都带 with_for_update，唯独修订是裸 select，而 record_versions 上没有
        # UNIQUE(medical_record_id, version_no)。两名管理员同时修订同一份病历会
        # 各插一条相同 version_no，此后按 current_version 取正文的 JOIN 命中两行，
        # 同一份病历刷新出不同内容——医疗场景不可接受。
        record = (await self.db.execute(
            select(MedicalRecord).where(MedicalRecord.id == record_id).with_for_update()
        )).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="病历不存在")

        new_version_no = (record.current_version or 0) + 1
        new_version = RecordVersion(
            medical_record_id=record_id,
            version_no=new_version_no,
            # 保持 quick-save 的 {"text": ...} 结构，下游 _parse_record_content 已支持
            content={"text": content},
            source="admin_revise",
            triggered_by=current_user.id,
        )

        # 修订版本也必须进签名链（2026-08-13 第五轮审计修复）：
        # 原先 sign_hash/prev_hash 都是 NULL，而所有对外读路径都按 current_version
        # 取正文——一份病历被修订过一次，它此后展示的正文就永久脱离防篡改体系，
        # 而完整性端点只扫 sign_hash IS NOT NULL，会给出"全部通过"的错误结论。
        # 只有已签发过的病历才入链（未签发的病历本就没有链）。
        if record.status == "submitted":
            from app.services._record_signature import compute_sign_hash, latest_chain_hash
            prev_hash = await latest_chain_hash(self.db)
            new_version.prev_hash = prev_hash
            new_version.sign_hash = compute_sign_hash(
                content_text=content,
                patient_snapshot=record.patient_snapshot,
                doctor_id=current_user.id,
                submitted_at_iso=record.submitted_at.isoformat() if record.submitted_at else "",
                prev_hash=prev_hash,
            )
        self.db.add(new_version)
        record.current_version = new_version_no
        await self.db.commit()
        await self.db.refresh(new_version)

        # 审计日志：理由写进 detail，永久留痕（patient/encounter id 也带上方便检索）
        await log_action(
            action="revise_record",
            user_id=current_user.id,
            user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
            user_role=getattr(current_user, "role", None),
            resource_type="medical_record",
            resource_id=record_id,
            detail=f"修订理由：{revise_reason}（新版本号：{new_version_no}）",
        )

        # 失效该接诊的 snapshot，让医生端工作台再打开能拿到最新内容
        await invalidate_encounter_snapshot(record.encounter_id)

        # ── 修订后必须重推 HIS（2026-08-14 第八轮审计修复）──────────────────
        #
        # 原先这里完全不碰回写。于是：门诊病历签发 → 自动回写 HIS 成功 →
        # 事后发现诊断录错 → 管理员在后台修订、填了理由、系统建新版本进签名链、
        # 前端提示修订成功；而 **HIS 病案里躺着的仍是修订前的错误版本，永久不会
        # 更新**，医生和管理员都以为改过了。
        # 对账任务也够不着：_find_candidates 只捞 writeback.status 属
        # {skipped, write_failed, refresh_failed, error} 或从未回写的，
        # 'success' 不在重投集合里。
        # 而修订的动机通常正是「原版本有错」——这恰恰是最不能让 HIS 停在旧版本
        # 的场景。回写按 (visit_id+record_type+record_no) 幂等，重推即覆盖更新。
        his_writeback = None
        if settings.his_adapter_enabled and record.encounter_id:
            enc = await self.db.get(Encounter, record.encounter_id)
            if enc is not None and enc.his_external_ref:
                from app.his_adapter.bg_tasks import spawn
                from app.his_adapter.writeback_dispatch import dispatch_writeback
                # record_id 必带（2026-08-29 粒度下沉）：不带的话 builder 会
                # 重挑"最新已签发"的文书——修订的是早期文书（如入院记录）时
                # 重推的却是最新病程，HIS 里的错误版本永不更新，与本段注释
                # 宣称的目标正相反。
                spawn(
                    dispatch_writeback(enc.id, current_user.id, enc.visit_no or "",
                                       record_id=record_id),
                    name=f"writeback-revise:{enc.id}:{record_id}",
                )
                his_writeback = "dispatched"
                logger.info(
                    "record.revise: 已派发 HIS 重推 encounter_id=%s record_id=%s",
                    enc.id, record_id,
                )

        return {
            "ok": True,
            "record_id": record_id,
            "new_version_no": new_version_no,
            "revised_at": datetime.now().isoformat(),
            # 让管理端能显示"已重推 HIS"，而不是让人以为只改了本地
            "his_writeback": his_writeback,
        }
