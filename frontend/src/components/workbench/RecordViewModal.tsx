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
  const formatted = (record.content || '').replace(/\n/g, '<br>')
  const html = `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>${typeLabel} - ${patientDesc}</title>
<style>
  body { font-family: 'PingFang SC','Microsoft YaHei',sans-serif; margin: 0; padding: 32px 48px; color: #1e293b; }
  h2 { text-align: center; font-size: 20px; margin-bottom: 4px; }
  .meta { text-align: center; font-size: 13px; color: #64748b; margin-bottom: 24px; padding-bottom: 12px; border-bottom: 1px solid #e2e8f0; }
  .content { font-size: 14px; line-height: 2.0; white-space: pre-wrap; }
  .footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8; text-align: right; }
  @media print { body { padding: 20px 32px; } }
</style></head><body>
<h2>${typeLabel}</h2>
<div class="meta">${patientDesc}${signedAt ? `&nbsp;&nbsp;|&nbsp;&nbsp;签发时间：${signedAt}` : ''}</div>
<div class="content">${formatted}</div>
<div class="footer">MediScribe 智能病历系统 · 本病历由医生审核签发</div>
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
          <Space>
            <FileTextOutlined style={{ color: accentColor }} />
            <span>{record.patient_name}</span>
            <Tag color={tagColor}>{recordTypeLabel(record.record_type)}</Tag>
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
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 520,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: '#1e293b',
        }}
      >
        {record?.content || '（病历内容为空）'}
      </div>
      <div
        style={{
          marginTop: 12,
          padding: '8px 12px',
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <CheckOutlined style={{ color: '#22c55e' }} />
        <Text style={{ fontSize: 12, color: '#166534' }}>已签发病历 · 不可修改</Text>
      </div>
    </Modal>
  )
}
