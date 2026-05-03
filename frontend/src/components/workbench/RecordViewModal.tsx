/**
 * 病历查看弹窗（components/workbench/RecordViewModal.tsx）
 *
 * 只读模式展示一份完整病历内容，被 HistoryDrawer 和管理页调用：
 *   - 展示患者基本信息、就诊类型、病历类型、签发时间
 *   - 完整病历文本内容（pre 标签保留格式）
 *   - 「打印」按钮调用 window.print()，打印区域通过 CSS 媒体查询控制
 *
 * Props:
 *   record: 完整病历对象（含 content 字段）
 *   open: 是否显示
 *   onClose: 关闭回调
 *
 * 不提供编辑功能：已签发病历不可修改，
 * 草稿病历应通过续接诊恢复工作台进行编辑。
 */
import { Modal, Space, Tag, Button, Typography } from 'antd'
import { FileTextOutlined, CheckOutlined, PrinterOutlined } from '@ant-design/icons'

const { Text } = Typography

interface RecordViewModalProps {
  record: any
  onClose: () => void
  accentColor: string
  tagColor: string
  recordTypeLabel: (type: string) => string
  showPrint?: boolean
}

function printRecord(record: any, recordTypeLabel: (type: string) => string) {
  const typeLabel = recordTypeLabel(record.record_type)
  const patientDesc = [
    record.patient_name,
    record.patient_gender === 'male' ? '男' : record.patient_gender === 'female' ? '女' : '',
    record.patient_age ? `${record.patient_age}岁` : '',
  ]
    .filter(Boolean)
    .join(' · ')
  const signedAt = record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''
  // 责任医生：按《病历书写规范》必须显示。优先用接诊医生，签发者不同时附注。
  const doctorLine = record.doctor_name
    ? `接诊医生：${record.doctor_name}${
        record.submitted_by_name && record.submitted_by_name !== record.doctor_name
          ? `（签发：${record.submitted_by_name}）`
          : ''
      }`
    : ''
  const formatted = (record.content || '').replace(/\n/g, '<br>')
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patientDesc}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 4px; }
  .meta { text-align: center; font-size: 13px; color: #64748b; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 12px; color: #94a3b8; display: flex; justify-content: space-between; }
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
<div class="meta">${patientDesc}${signedAt ? `&nbsp;&nbsp;|&nbsp;&nbsp;签发时间：${signedAt}` : ''}</div>
<div class="content">${formatted}</div>
<div class="footer"><span>${doctorLine}</span><span>MediScribe 智能病历系统 · 本病历由医生审核签发</span></div>
<script>window.onload = function() { window.print(); }<\/script>
</body></html>`
  const w = window.open('', '_blank')
  if (w) {
    w.document.write(html)
    w.document.close()
  }
}

export default function RecordViewModal({
  record,
  onClose,
  accentColor,
  tagColor,
  recordTypeLabel,
  showPrint = false,
}: RecordViewModalProps) {
  return (
    <Modal
      title={
        record && (
          <Space wrap>
            <FileTextOutlined style={{ color: accentColor }} />
            <span style={{ fontWeight: 600 }}>{record.patient_name}</span>
            {record.patient_gender && record.patient_gender !== 'unknown' && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_gender === 'male' ? '男' : '女'}
              </Text>
            )}
            {record.patient_age != null && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_age}岁
              </Text>
            )}
            <Tag color={tagColor} style={{ margin: 0 }}>
              {recordTypeLabel(record.record_type)}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''}
            </Text>
          </Space>
        )
      }
      open={!!record}
      onCancel={onClose}
      footer={
        <Space>
          {showPrint && (
            <Button icon={<PrinterOutlined />} onClick={() => printRecord(record, recordTypeLabel)}>
              打印 / 导出PDF
            </Button>
          )}
          <Button type={showPrint ? 'primary' : 'default'} onClick={onClose}>
            关闭
          </Button>
        </Space>
      }
      width={680}
    >
      <div
        style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 520,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: 'var(--text-1)',
        }}
      >
        {record?.content || '（病历内容为空）'}
      </div>
      {/* 已签发标识 + 责任医生 + 签发时间。
          按《病历书写规范》要求展示责任医生姓名；后端从 list_by_patient 返回。
          submitted_by_name = 实际触发签发的医生（可能与接诊医生不同：管床代签等）；
          doctor_name = 接诊医生（接诊创建者，主要责任人）。一般情况下两者相同。 */}
      <div
        style={{
          marginTop: 12,
          padding: '10px 14px',
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          fontSize: 12,
          color: '#166534',
        }}
      >
        <Space size={6}>
          <CheckOutlined style={{ color: '#22c55e' }} />
          <span>已签发病历 · 不可修改</span>
        </Space>
        {record?.doctor_name && (
          <span style={{ color: '#065f46' }}>
            接诊医生：<b>{record.doctor_name}</b>
            {/* 2026-05-03 改：医生侧不再展示 submitted_by_name 差异——
                管理员后台修订病历会让 submitted_by_name 变成 admin，原逻辑会显示
                "（签发：系统管理员）"误导医生认为责任主体不是自己。合规要求的修订
                留痕走 audit_logs 表（管理员后台 + 审计员可查），医生侧只看接诊医生
                即可。如未来真有"管床代签"需求需另起字段（如 first_signed_by）单独
                展示，不复用 submitted_by_name（语义已被修订人占用）。 */}
          </span>
        )}
        {record?.submitted_at && (
          <span style={{ color: '#065f46' }}>
            签发于：{new Date(record.submitted_at).toLocaleString('zh-CN')}
          </span>
        )}
      </div>
    </Modal>
  )
}
