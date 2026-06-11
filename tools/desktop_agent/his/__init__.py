"""HIS 操作模块(his/)

子模块:
  - detector : 探测 HIS 窗口
  - reader   : 读 HIS 当前患者信息(UI Automation)
  - writer   : 写回 HIS(自动填入)

配置文件:
  - jinsuanpan_map.yaml : 字段映射,与后端 his_adapter/jinsuanpan_map.yaml
                         保持同步。Agent 启动时从后端 /desktop/config 拉
                         最新版本覆盖本地副本。
"""
