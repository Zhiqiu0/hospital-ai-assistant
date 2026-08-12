"""HIS 对接模块（接口模式：接诊推送 + 病历回写 + WS + 叫号）

本模块是 MediScribe 与院内 HIS（首期对接金算盘）打通的所有后端代码集中地。

方案：全链路走「接口模式」——HIS 推送接诊建档，我方签发后回写，HMAC 验签
（signing / writeback_*）。两代旧范式（桌面 Agent「控件模式」UI 自动化、
「/embed 嵌入模式」token 拉起浏览器）均已退休删除（2026-08-12 embed 下线）。

设计原则：
  - 与现有 SaaS 模式严格隔离：所有 HIS 对接路由由 his_adapter_enabled
    全局保险丝控制，关闭时直接 503 不影响 SaaS。
  - 复用现有 service：HIS 接诊不开新表，复用 encounter / medical_record
    模型，仅在 encounter 上加 his_external_ref JSONB 字段记录 HIS 患者标识。

模块入口：
  - depends.require_his_enabled  : FastAPI 依赖，保险丝守门
  - admit_service                : 接诊推送建档（自动建档 + 医生映射 + 幂等）
  - signing / writeback_*        : 接口模式回写（组装→签名→写入→刷新）
  - models                       : HISExternalRef / ApiEnvelope / AdmitPushRequest
"""
