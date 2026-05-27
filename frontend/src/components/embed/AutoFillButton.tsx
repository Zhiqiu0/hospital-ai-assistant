/**
 * 嵌入模式"自动填入 HIS"按钮（components/embed/AutoFillButton.tsx）
 *
 * 嵌入模式专属按钮：医生写完 AI 病历后点这个，调本地桌面 Agent 把内容
 * 写回金算盘 HIS。SaaS 模式下不渲染。
 *
 * UX：
 *   - Agent 未启动 → 按钮 disabled + tooltip 提示"启动 MediScribe Agent"
 *   - 填入中 → 按钮 loading + 进度条 Modal 实时显示每个字段
 *   - 失败 → 失败字段复制到剪贴板兜底 + Notify 医生
 */
import { useState, useEffect } from 'react'
import { Button, Tooltip, Progress, Modal, List, Tag } from 'antd'
import { CloudUploadOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import { desktopAgent, type FillRequest, type FillFieldResult } from '@/services/desktopAgent'

interface AutoFillButtonProps {
  encounterId: string
  /** 收集当前所有字段的回调，由 EmbedWorkbenchPage 提供 */
  collectFields: () => FillRequest['fields']
}

export default function AutoFillButton({ encounterId, collectFields }: AutoFillButtonProps) {
  // Agent 在线状态：null=未探测 / true=在线 / false=离线
  const [agentOnline, setAgentOnline] = useState<boolean | null>(null)
  // 填入中
  const [filling, setFilling] = useState(false)
  // 进度条状态
  const [progress, setProgress] = useState(0)
  // 已完成的字段列表（实时展示给医生看）
  const [doneFields, setDoneFields] = useState<FillFieldResult[]>([])
  // 进度对话框开关
  const [progressModalOpen, setProgressModalOpen] = useState(false)

  // 组件挂载时探测 Agent
  useEffect(() => {
    let cancelled = false
    desktopAgent.discover().then(found => {
      if (cancelled) return
      setAgentOnline(found)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const handleAutoFill = async () => {
    // 二次 ping 保险：组件 mount 时 Agent 在，但医生写病历可能花了几分钟，
    // 期间 Agent 可能被杀掉
    const ping = await desktopAgent.ping()
    if (!ping) {
      setAgentOnline(false)
      message.error('桌面 Agent 未运行，请先启动 MediScribe Agent')
      return
    }
    if (!ping.his_detected) {
      message.warning('没检测到金算盘 HIS 窗口，请先打开 HIS 并选中患者')
      return
    }

    setFilling(true)
    setProgress(0)
    setDoneFields([])
    setProgressModalOpen(true)

    // 订阅 WebSocket 实时进度
    const ws = desktopAgent.connectProgress(evt => {
      setDoneFields(prev => [...prev, evt])
      if (evt.progress != null) setProgress(evt.progress)
    })

    try {
      const fields = collectFields()
      const result = await desktopAgent.fill({ encounter_id: encounterId, fields })

      // 处理结果
      if (result.status === 'success') {
        message.success(
          `填入完成 ${result.succeeded}/${result.total_fields} 字段，耗时 ${(result.duration_ms / 1000).toFixed(1)}s`
        )
      } else if (result.status === 'partial') {
        message.warning(`部分字段失败 (${result.failed}/${result.total_fields})，已复制到剪贴板`)
      } else {
        message.error('填入失败，完整病历已复制到剪贴板')
      }
      setProgress(100)
    } catch (e) {
      message.error(`填入异常：${(e as Error).message}`)
    } finally {
      ws.close()
      setFilling(false)
    }
  }

  const buttonDisabled = !agentOnline || filling
  const tooltipTitle =
    agentOnline === null
      ? '探测桌面 Agent 中...'
      : agentOnline === false
        ? '桌面 Agent 未运行，请启动 MediScribe Agent'
        : '把当前 AI 病历一键写回金算盘 HIS'

  return (
    <>
      <Tooltip title={tooltipTitle}>
        <Button
          type="primary"
          icon={<CloudUploadOutlined />}
          loading={filling}
          disabled={buttonDisabled}
          onClick={handleAutoFill}
          style={{
            borderRadius: 8,
            fontWeight: 600,
            background: agentOnline ? 'linear-gradient(135deg, #047857, #10b981)' : undefined,
            border: 'none',
          }}
        >
          自动填入 HIS
        </Button>
      </Tooltip>

      <Modal
        title="正在写入金算盘 HIS"
        open={progressModalOpen}
        onCancel={() => !filling && setProgressModalOpen(false)}
        footer={null}
        width={520}
        maskClosable={!filling}
      >
        <Progress
          percent={progress}
          status={filling ? 'active' : 'success'}
          style={{ marginBottom: 16 }}
        />
        <List
          size="small"
          dataSource={doneFields}
          locale={{ emptyText: '准备开始…' }}
          renderItem={item => (
            <List.Item>
              <span style={{ flex: 1 }}>{item.field_key}</span>
              <Tag
                color={
                  item.status === 'success'
                    ? 'success'
                    : item.status === 'fallback_clipboard'
                      ? 'warning'
                      : 'error'
                }
              >
                {item.status === 'success'
                  ? `✓ ${item.duration_ms}ms`
                  : item.status === 'fallback_clipboard'
                    ? '已复制到剪贴板'
                    : item.error_message || '失败'}
              </Tag>
            </List.Item>
          )}
          style={{ maxHeight: 320, overflow: 'auto' }}
        />
      </Modal>
    </>
  )
}
