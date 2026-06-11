"""HIS 对接模块（嵌入模式 / 桌面 Agent 字段映射 / 审计）

本模块是 MediScribe 与院内 HIS（首期对接金算盘）打通的所有后端代码集中地。

设计原则：
  - 与现有 SaaS 模式严格隔离：所有 /embed/* /desktop/* 路由由
    his_adapter_enabled 全局保险丝控制，关闭时直接 503 不影响 SaaS。
  - 复用现有 service：嵌入会话不开新表，复用 encounter / medical_record
    模型，仅在 encounter 上加 his_external_ref JSONB 字段记录 HIS 患者标识。
  - 数据不出院：HIS 患者数据只作上下文用，AI 生成的病历临时存（关联到
    encounter），填入 HIS 后按医院规定 N 天自动清理。

模块入口：
  - depends.require_his_enabled  : FastAPI 依赖，保险丝守门
  - config_loader                : 加载 jinsuanpan_map.yaml
  - models                       : HISContext / FillRequest / FillResult
"""
