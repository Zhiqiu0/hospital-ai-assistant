from fastapi import APIRouter
from app.api.v1 import auth, patients, encounters, medical_records, qc, ai, pacs, lab_reports
from app.api.v1.admin import users, departments, qc_rules, prompts, stats, records as admin_records, audit_logs, model_configs, voice_records as admin_voice_records

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["认证"])
router.include_router(ai.router, prefix="/ai", tags=["AI生成"])
router.include_router(patients.router, prefix="/patients", tags=["患者"])
router.include_router(encounters.router, prefix="/encounters", tags=["就诊"])
router.include_router(medical_records.router, prefix="/medical-records", tags=["病历"])
router.include_router(qc.router, prefix="/qc-issues", tags=["质控"])
router.include_router(pacs.router, prefix="/pacs", tags=["PACS影像"])
router.include_router(lab_reports.router, prefix="/lab-reports", tags=["检验报告"])

# 后台管理
router.include_router(users.router, prefix="/admin/users", tags=["管理-用户"])
router.include_router(departments.router, prefix="/admin/departments", tags=["管理-科室"])
router.include_router(qc_rules.router, prefix="/admin/qc-rules", tags=["管理-质控规则"])
router.include_router(prompts.router, prefix="/admin/prompts", tags=["管理-Prompt"])
router.include_router(stats.router, prefix="/admin/stats", tags=["管理-统计"])
router.include_router(admin_records.router, prefix="/admin/records", tags=["管理-病历"])
router.include_router(audit_logs.router, prefix="/admin/audit-logs", tags=["管理-审计日志"])
router.include_router(model_configs.router, prefix="/admin/model-configs", tags=["管理-模型配置"])
router.include_router(admin_voice_records.router, prefix="/admin/voice-records", tags=["管理-语音记录"])
