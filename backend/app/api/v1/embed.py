"""嵌入模式 API（HIS 桌面 Agent 启动 / 浏览器嵌入页校验）

路由前缀：/api/v1/embed
所有路由由 his_adapter.depends.require_his_enabled 守门，
HIS_ADAPTER_ENABLED=false 时统一 503。

业务流程：
  1. 医生在 HIS 触发 AI 助手
  2. 桌面 Agent 调 POST /embed/start：携带 HIS 患者信息 → 后端创建
     encounter (his_external_ref 落 HIS 标识) + 签发 4h token
  3. Agent 启动浏览器 → URL 带 token
  4. 浏览器调 GET /embed/session/{encounter_id} 拿到接诊上下文
  5. 后续病历生成 / 质控 / 签发都走现有接诊路由，不需要嵌入专属接口
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, get_current_user
from app.database import get_db
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import StartEmbedRequest, StartEmbedResponse
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.patient_service import PatientService

router = APIRouter(
    prefix="/embed",
    tags=["embed"],
    dependencies=[Depends(require_his_enabled)],
)


@router.post("/start", response_model=StartEmbedResponse)
async def start_embed_session(
    req: StartEmbedRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StartEmbedResponse:
    """启动嵌入会话。

    桌面 Agent 在医生触发 AI 助手时调用。后端：
      1. 按 HIS 患者标识找 / 建患者（不污染 SaaS 患者搜索）
      2. 创建 encounter，落 his_external_ref
      3. 签发短期 embed_token（4h，JWT），让浏览器嵌入页跳过登录

    Args:
        req: HIS 患者信息 + Agent 自身信息
        db: 数据库 session
        current_user: 当前医生（Agent 用医生的长期 token 调本接口）

    Returns:
        encounter_id + embed_token + embed_url，Agent 拿来启动浏览器
    """
    # 1. 找已有患者（按 HIS hospital_code + patient_no 复合匹配）
    #    复用 patients 表，但加 his_external_ref 字段标记是 HIS 患者，
    #    避免与 SaaS 患者搜索结果混杂（搜索接口加 HIS 过滤）。
    patient_service = PatientService(db)
    existing_patient = await _find_his_patient(db, req)

    if existing_patient:
        patient_id = existing_patient.id
    else:
        # 新建 HIS 患者（最小信息，详细的等接诊弹窗医生再补）
        from app.schemas.patient import PatientCreate
        from datetime import date

        birth_date = None
        if req.patient_birth_date:
            try:
                birth_date = date.fromisoformat(req.patient_birth_date)
            except ValueError:
                pass  # 无法解析就留空，不阻塞创建

        new_patient = await patient_service.create(
            PatientCreate(
                name=req.patient_name,
                gender=req.patient_gender,
                birth_date=birth_date,
            )
        )
        patient_id = new_patient["id"]

    # 2. 创建嵌入接诊，落 HIS 标识
    encounter = Encounter(
        patient_id=patient_id,
        doctor_id=current_user.id,
        department_id=current_user.department_id,
        visit_type="outpatient",  # MVP 阶段仅支持门诊嵌入
        visit_no=req.his_ref.his_visit_no,
        is_first_visit=True,  # 由前端后续判断改写
        status="in_progress",
        his_external_ref=req.his_ref.model_dump(),
    )
    db.add(encounter)
    await db.commit()
    await db.refresh(encounter)

    # 3. 签发短期 embed_token（独立于医生长期 token，权限受限）
    ttl = timedelta(hours=settings.his_embed_token_ttl_hours)
    expires_at = datetime.now(timezone.utc) + ttl
    embed_token = create_access_token(
        data={
            "sub": current_user.id,
            "role": current_user.role,
            "embed": True,
            "encounter_id": encounter.id,
            "his_patient_no": req.his_ref.his_patient_no,
            "agent_device_id": req.agent_device_id,
        },
        expires_delta=ttl,
    )

    # 4. 拼浏览器 URL
    embed_url = (
        f"{_get_frontend_base_url()}/embed"
        f"?token={embed_token}"
        f"&encounter_id={encounter.id}"
    )

    return StartEmbedResponse(
        encounter_id=encounter.id,
        embed_token=embed_token,
        embed_url=embed_url,
        expires_at=expires_at,
    )


@router.get("/session/{encounter_id}")
async def get_embed_session(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """浏览器嵌入页加载时拉取接诊上下文。"""
    result = await db.execute(
        select(Encounter).where(
            Encounter.id == encounter_id,
            Encounter.doctor_id == current_user.id,
        )
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="嵌入会话不存在")

    if not encounter.his_external_ref:
        raise HTTPException(status_code=400, detail="此接诊不是嵌入模式")

    patient = await db.get(Patient, encounter.patient_id)

    return {
        "encounter_id": encounter.id,
        "patient_id": patient.id if patient else None,
        "patient_name": patient.name if patient else None,
        "his_ref": encounter.his_external_ref,
        "visit_type": encounter.visit_type,
        "is_first_visit": encounter.is_first_visit,
    }


async def _find_his_patient(db: AsyncSession, req: StartEmbedRequest) -> Patient | None:
    """按 HIS 标识找已有患者（同一 HIS 患者多次接诊复用档案）。

    匹配键：encounters.his_external_ref 中 his_patient_no + hospital_code 都相同。
    """
    result = await db.execute(
        select(Encounter)
        .where(
            Encounter.his_external_ref["his_patient_no"].astext == req.his_ref.his_patient_no,
            Encounter.his_external_ref["hospital_code"].astext == req.his_ref.hospital_code,
        )
        .order_by(Encounter.created_at.desc())
        .limit(1)
    )
    last_encounter = result.scalar_one_or_none()
    if not last_encounter:
        return None
    return await db.get(Patient, last_encounter.patient_id)


def _get_frontend_base_url() -> str:
    """从 allowed_origins 取第一个作为前端 base URL。
    生产环境是 https://mediscribe.cn，开发环境是 http://localhost:5174。
    """
    return settings.origins_list[0] if settings.origins_list else "http://localhost:5174"
