"""HIS 对接模块（嵌入模式 + 接口模式回写/接诊推送）

本模块是 MediScribe 与院内 HIS（首期对接金算盘）打通的所有后端代码集中地。

方案：回写走「接口模式」——调 HIS 正经接口 + HMAC 验签（signing / writeback_*）。
旧的「控件模式」（桌面 Agent UI 自动化填表 + jinsuanpan_map.yaml 字段映射）已退休删除。

设计原则：
  - 与现有 SaaS 模式严格隔离：所有 /embed/* 路由由 his_adapter_enabled
    全局保险丝控制，关闭时直接 503 不影响 SaaS。
  - 复用现有 service：嵌入会话不开新表，复用 encounter / medical_record
    模型，仅在 encounter 上加 his_external_ref JSONB 字段记录 HIS 患者标识。

模块入口：
  - depends.require_his_enabled  : FastAPI 依赖，保险丝守门
  - signing / writeback_*        : 接口模式回写（组装→签名→写入→刷新）
  - models                       : HISExternalRef / StartEmbed* / ApiEnvelope / AdmitPushRequest
"""
