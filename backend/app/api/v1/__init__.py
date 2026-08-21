from fastapi import APIRouter
from app.api.v1 import auth, patients, encounters, medical_records, ai, pacs, lab_reports, inpatient, ai_voice_stream, ai_feedback, sentry_tunnel, his, his_queue, his_ws, diagnosis_codes
from app.api.v1.admin import router as admin_router

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["认证"])
router.include_router(ai.router, prefix="/ai", tags=["AI生成"])
# 实时语音识别 WebSocket（/api/v1/ai/voice-stream）
router.include_router(ai_voice_stream.router, prefix="/ai", tags=["AI生成"])
router.include_router(patients.router, prefix="/patients", tags=["患者"])
router.include_router(encounters.router, prefix="/encounters", tags=["就诊"])
router.include_router(medical_records.router, prefix="/medical-records", tags=["病历"])
# 诊断编码字典检索（2026-08-21 阶段2 编码化）
router.include_router(diagnosis_codes.router, prefix="/diagnosis-codes", tags=["编码字典"])
# 注：/qc-issues PATCH 死端点已删（2026-08-12 清理）——前端 issue 状态全在 qcStore
# 前端态维护，该端点零调用且不校验问题归属（越权面），质控主路径见 /ai/quick-qc。
router.include_router(pacs.router, prefix="/pacs", tags=["PACS影像"])
router.include_router(lab_reports.router, prefix="/lab-reports", tags=["检验报告"])
# 住院专项：病区视图、体征、问题列表、时效合规
router.include_router(inpatient.router, prefix="", tags=["住院专项"])
# 病程记录 CRUD
# AI 建议反馈收集
router.include_router(ai_feedback.router, prefix="/ai", tags=["AI反馈"])
# Sentry tunnel：透传前端 envelope 绕过 ad-blocker / 出口防火墙
router.include_router(sentry_tunnel.router, prefix="", tags=["可观测性"])

# 后台管理：单一聚合 router，自带 audit_admin_action 依赖（修复"管理员操作零审计"硬伤）
router.include_router(admin_router, prefix="/admin")

# 注：旧的桌面 Agent「控件模式」和「/embed 嵌入模式」两代旧接入范式均已退休删除
# （2026-08-12 embed 下线），HIS 接入统一走下面的接口模式：推送建档 + 叫号 + 回写。
# HIS 外部接口（接诊推送接收 + 病历回写，HMAC 验签，HIS_ADAPTER_ENABLED=false 时统一 503）
router.include_router(his.router, tags=["HIS对接"])
# HIS WebSocket 长连接通道（规范第 7 章方案 B：接诊上行 + 回写下行走同一条 wss）
router.include_router(his_ws.router, tags=["HIS对接"])
# 工作台叫号队列（今日队列拉取 + SSE 实时事件，医生登录态鉴权）
router.include_router(his_queue.router, tags=["HIS对接"])
