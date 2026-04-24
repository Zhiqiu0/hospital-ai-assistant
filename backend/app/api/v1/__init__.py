from fastapi import APIRouter
from app.api.v1 import auth, patients, encounters, medical_records, qc, ai, pacs, lab_reports, inpatient, ai_voice_stream, progress_notes, ai_feedback
from app.api.v1.admin import router as admin_router

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["认证"])
router.include_router(ai.router, prefix="/ai", tags=["AI生成"])
# 实时语音识别 WebSocket（/api/v1/ai/voice-stream）
router.include_router(ai_voice_stream.router, prefix="/ai", tags=["AI生成"])
router.include_router(patients.router, prefix="/patients", tags=["患者"])
router.include_router(encounters.router, prefix="/encounters", tags=["就诊"])
router.include_router(medical_records.router, prefix="/medical-records", tags=["病历"])
router.include_router(qc.router, prefix="/qc-issues", tags=["质控"])
router.include_router(pacs.router, prefix="/pacs", tags=["PACS影像"])
router.include_router(lab_reports.router, prefix="/lab-reports", tags=["检验报告"])
# 住院专项：病区视图、体征、问题列表、时效合规
router.include_router(inpatient.router, prefix="", tags=["住院专项"])
# 病程记录 CRUD
router.include_router(progress_notes.router, prefix="", tags=["病程记录"])
# AI 建议反馈收集
router.include_router(ai_feedback.router, prefix="/ai", tags=["AI反馈"])

# 后台管理：单一聚合 router，自带 audit_admin_action 依赖（修复"管理员操作零审计"硬伤）
router.include_router(admin_router, prefix="/admin")
