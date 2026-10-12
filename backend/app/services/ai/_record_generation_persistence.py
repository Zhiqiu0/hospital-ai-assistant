"""AI 生成落库及审计；显式文书身份与正文同批传入，不回落到最新同类型。"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.request_context import get_encounter_id, get_user_id
from app.services.ai.llm_client import llm_client
from app.services.ai.task_logger import log_ai_task
from app.services.ai._record_generation_helpers import DraftSaveError

logger = logging.getLogger(__name__)


async def _log_and_save_draft(
    task_type: str,
    record_type: str,
    record_text: str,
    db: AsyncSession,
    *,
    save_draft: bool,
    model_name: str | None = None,
    record_id: str | None = None,  # 发起时选中的文书，贯穿生成落库
) -> str | None:
    """写 ai_tasks 审计 + 可选自动落 draft 病历。

    save_draft=True 时仅 generate 路径调用（覆盖式更新草稿）。supplement / polish
    也是更新草稿的——只要 encounter 存在就更新，让医生退出再进来能看到最新草稿。

    Returns:
        草稿落库后的 updated_at ISO 字符串（未落库时 None；失败抛 DraftSaveError）——done 事件带给
        前端同步 auto-save 乐观锁基线（2026-08-21 第四轮走查：生成落库后前端
        基线不知道这次写入，下一次 auto-save 必假 409）。
    """
    usage = llm_client._last_usage
    try:
        await log_ai_task(
            task_type,
            token_input=usage.prompt_tokens if usage else None,
            token_output=usage.completion_tokens if usage else None,
            model_name=model_name,  # 真实模型，非全局默认（审计 #7）
        )
    except Exception as exc:
        logger.error("log_ai_task_failed task=%s err=%s", task_type, exc)

    if not save_draft:
        return None
    encounter_id = get_encounter_id()
    user_id = get_user_id()
    if encounter_id and user_id and user_id != "-":
        try:
            from app.services.medical_record_service import MedicalRecordService
            saved = await MedicalRecordService(db).save_ai_draft(
                encounter_id=encounter_id,
                record_type=record_type,
                content=record_text,
                user_id=user_id,
                record_id=record_id,
            )
            return saved.get("updated_at")
        except Exception as exc:
            # 单独披露保存失败，后续仍发送生成文本供医生保留及自动保存恢复。
            logger.error("save_ai_draft_failed encounter=%s err=%s", encounter_id, exc)
            raise DraftSaveError("病历已生成，但草稿保存失败，请检查保存状态并重试") from exc
    return None
