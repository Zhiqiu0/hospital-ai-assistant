import { useEffect, useState } from 'react'
import { Button, Empty, Spin, message, Typography, Tag, Upload, Modal } from 'antd'
import {
  FileTextOutlined, DeleteOutlined, ReloadOutlined,
  InboxOutlined, CheckCircleOutlined, PlusOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography
const { Dragger } = Upload

interface LabReportItem {
  id: string
  original_filename: string
  ocr_text: string
  status: string
  created_at: string
}

// 从 ocr_text 中提取报告类型
function extractReportType(text: string): string {
  const m = text.match(/【报告类型】([^\n【]+)/)
  return m?.[1]?.trim() || '未知类型'
}

// 从 ocr_text 中提取患者姓名
function extractPatientName(text: string): string {
  const m = text.match(/姓名[：:]\s*([^\s\n]+)/)
  return m?.[1]?.trim() || ''
}

// 智能插入：同类型替换，不同类型追加
function smartInsert(existing: string, newReport: string): string {
  if (!existing.trim()) return newReport
  const newType = extractReportType(newReport)
  if (newType === '未知类型') return existing.trimEnd() + '\n\n' + newReport

  // 按报告分块（每块以【报告类型】开头）
  const sections = existing.split(/(?=【报告类型】)/)
  const idx = sections.findIndex(s => extractReportType(s) === newType)
  if (idx >= 0) {
    sections[idx] = newReport
    return sections.join('')
  }
  return existing.trimEnd() + '\n\n' + newReport
}

export default function LabReportTab() {
  const { currentEncounterId, currentPatient, inquiry, setInquiry } = useWorkbenchStore()
  const [reports, setReports] = useState<LabReportItem[]>([])
  const [loading, setLoading] = useState(false)
  const [uploadingCount, setUploadingCount] = useState(0)
  const [insertedIds, setInsertedIds] = useState<Set<string>>(new Set())
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const fetchReports = async () => {
    if (!currentEncounterId) return
    setLoading(true)
    try {
      const data = await api.get(`/lab-reports/?encounter_id=${currentEncounterId}`) as LabReportItem[]
      setReports(data)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchReports() }, [currentEncounterId])

  const handleUpload = async (file: File) => {
    const duplicate = reports.find(r => r.original_filename === file.name)
    if (duplicate) {
      message.warning({ content: `已存在同名报告：${file.name}`, duration: 2 })
      return false
    }
    setUploadingCount(prev => prev + 1)
    const formData = new FormData()
    formData.append('file', file)
    if (currentEncounterId) formData.append('encounter_id', currentEncounterId)
    try {
      const data = await api.post('/lab-reports/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }) as LabReportItem
      setReports(prev => [data, ...prev])
      message.success({ content: `识别成功：${extractReportType(data.ocr_text)}`, duration: 2 })
    } catch {
      message.error(`上传失败：${file.name}`)
    } finally {
      setUploadingCount(prev => prev - 1)
    }
    return false
  }

  const doInsert = (report: LabReportItem) => {
    const current = inquiry.auxiliary_exam?.trim() || ''
    const newVal = smartInsert(current, report.ocr_text)
    const newInquiry = { ...inquiry, auxiliary_exam: newVal }
    setInquiry(newInquiry)
    if (currentEncounterId) {
      api.put(`/encounters/${currentEncounterId}/inquiry`, newInquiry).catch(() => {})
    }
    setInsertedIds(prev => new Set([...prev, report.id]))
    message.success({ content: `已插入：${extractReportType(report.ocr_text)}`, duration: 1.5 })
  }

  const handleInsert = (report: LabReportItem) => {
    const reportName = extractPatientName(report.ocr_text)
    const patientName = currentPatient?.name || ''
    if (reportName && patientName && reportName !== patientName) {
      Modal.confirm({
        title: '患者姓名不符',
        content: `当前患者：${patientName}，报告患者：${reportName}。确认插入此报告？`,
        okText: '仍然插入',
        cancelText: '取消',
        okButtonProps: { danger: true },
        onOk: () => doInsert(report),
      })
      return
    }
    doInsert(report)
  }

  const handleInsertAll = () => {
    if (!reports.length) return
    const patientName = currentPatient?.name || ''
    const mismatched = reports.filter(r => {
      const rn = extractPatientName(r.ocr_text)
      return rn && patientName && rn !== patientName
    })
    const doAll = () => {
      let current = inquiry.auxiliary_exam?.trim() || ''
      for (const r of reports) {
        current = smartInsert(current, r.ocr_text)
      }
      const newInquiry = { ...inquiry, auxiliary_exam: current }
      setInquiry(newInquiry)
      if (currentEncounterId) {
        api.put(`/encounters/${currentEncounterId}/inquiry`, newInquiry).catch(() => {})
      }
      setInsertedIds(new Set(reports.map(r => r.id)))
      message.success({ content: `已插入全部 ${reports.length} 份报告`, duration: 2 })
    }
    if (mismatched.length > 0) {
      Modal.confirm({
        title: '部分报告患者姓名不符',
        content: `当前患者：${patientName}，其中 ${mismatched.length} 份报告姓名不符（${mismatched.map(r => extractPatientName(r.ocr_text)).join('、')}）。确认插入全部？`,
        okText: '仍然插入全部',
        cancelText: '取消',
        okButtonProps: { danger: true },
        onOk: doAll,
      })
      return
    }
    doAll()
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/lab-reports/${id}`)
      setReports(prev => prev.filter(r => r.id !== id))
      setInsertedIds(prev => { const s = new Set(prev); s.delete(id); return s })
      message.success({ content: '已删除', duration: 1.5 })
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '8px 12px', gap: 10 }}>
      {/* Upload area */}
      <Dragger
        accept=".jpg,.jpeg,.png,.webp,.pdf"
        multiple
        showUploadList={false}
        beforeUpload={(file) => { handleUpload(file); return false }}
        disabled={uploadingCount > 0}
        style={{ borderRadius: 8, padding: 0 }}
      >
        {uploadingCount > 0 ? (
          <div style={{ padding: '12px 0', textAlign: 'center' }}>
            <Spin size="small" />
            <div style={{ fontSize: 12, color: '#7c3aed', marginTop: 6 }}>AI 识别中{uploadingCount > 1 ? `（${uploadingCount} 份）` : ''}...</div>
          </div>
        ) : (
          <div style={{ padding: '10px 0', textAlign: 'center' }}>
            <InboxOutlined style={{ fontSize: 22, color: '#7c3aed' }} />
            <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>点击或拖拽上传检验报告</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>支持 JPG / PNG / PDF</div>
          </div>
        )}
      </Dragger>

      {/* Report list */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <Spin size="small" />
        </div>
      ) : reports.length === 0 ? (
        <Empty
          description={<span style={{ fontSize: 12, color: '#94a3b8' }}>暂无检验报告</span>}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ margin: '16px 0' }}
        />
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Insert all button */}
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={handleInsertAll}
            style={{
              borderRadius: 6, fontSize: 12, height: 28,
              color: '#7c3aed', borderColor: '#ddd6fe', background: '#f5f3ff',
            }}
            block
          >
            一键插入全部（{reports.length} 份）
          </Button>

          {/* Individual report cards */}
          {reports.map(r => {
            const inserted = insertedIds.has(r.id)
            const reportType = extractReportType(r.ocr_text)
            // Extract anomaly summary
            const anomalyMatch = r.ocr_text.match(/【异常项汇总】([\s\S]*?)(?=\n【|$)/)
            const hasAnomaly = !!anomalyMatch
            const anomalyItems = anomalyMatch
              ? anomalyMatch[1]
                  .split(/\n?\d+\.\s+/).filter(Boolean)
                  .map(s => s.replace(/\*\*/g, '').split(/[：:]/)[0].trim())
                  .filter(Boolean).slice(0, 2)
              : []
            const expanded = expandedId === r.id
            const reportPatientName = extractPatientName(r.ocr_text)
            const nameMismatch = !!reportPatientName && !!currentPatient?.name && reportPatientName !== currentPatient.name

            return (
              <div key={r.id} style={{
                border: `1px solid ${nameMismatch ? '#fecaca' : inserted ? '#bbf7d0' : '#e2e8f0'}`,
                borderRadius: 8,
                background: nameMismatch ? '#fff5f5' : inserted ? '#f0fdf4' : '#fff',
                overflow: 'hidden',
              }}>
                {/* Card header */}
                <div
                  style={{ padding: '8px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                  onClick={() => setExpandedId(expanded ? null : r.id)}
                >
                  <FileTextOutlined style={{ color: nameMismatch ? '#ef4444' : '#7c3aed', fontSize: 13, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {reportType}
                    </div>
                    <div style={{ fontSize: 10, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.original_filename}
                    </div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end', flexShrink: 0 }}>
                    {inserted && <Tag color="success" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}>已插入</Tag>}
                    {nameMismatch && <Tag color="error" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}><WarningOutlined /> 患者不符</Tag>}
                    {hasAnomaly && <Tag color="warning" style={{ fontSize: 10, margin: 0, lineHeight: '16px' }}><WarningOutlined /> 有异常</Tag>}
                  </div>
                </div>

                {/* Anomaly preview strip */}
                {hasAnomaly && anomalyItems.length > 0 && (
                  <div style={{
                    padding: '4px 10px',
                    background: '#fffbeb',
                    borderTop: '1px solid #fef3c7',
                    display: 'flex', gap: 6, flexWrap: 'wrap',
                  }}>
                    {anomalyItems.map((item, i) => (
                      <span key={i} style={{ fontSize: 10, color: '#92400e' }}>▲ {item}</span>
                    ))}
                  </div>
                )}

                {/* Expanded content */}
                {expanded && (
                  <div style={{ borderTop: '1px solid #f1f5f9' }}>
                    <div style={{
                      padding: '8px 10px',
                      fontSize: 11, lineHeight: 1.6,
                      whiteSpace: 'pre-wrap', color: '#334155',
                      maxHeight: 200, overflowY: 'auto',
                      background: '#fafafa',
                    }}>
                      {r.ocr_text}
                    </div>
                  </div>
                )}

                {/* Actions */}
                <div style={{ padding: '6px 10px', display: 'flex', gap: 6, justifyContent: 'flex-end', borderTop: '1px solid #f1f5f9' }}>
                  <Text style={{ fontSize: 10, color: '#94a3b8', flex: 1, alignSelf: 'center' }}>
                    {r.created_at ? new Date(r.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}
                  </Text>
                  <Button size="small" icon={<DeleteOutlined />} danger onClick={() => handleDelete(r.id)} style={{ fontSize: 11, borderRadius: 5, height: 24 }} />
                  <Button
                    size="small"
                    icon={inserted ? <CheckCircleOutlined /> : <PlusOutlined />}
                    onClick={() => handleInsert(r)}
                    style={{
                      fontSize: 11, borderRadius: 5, height: 24,
                      color: inserted ? '#16a34a' : '#7c3aed',
                      borderColor: inserted ? '#86efac' : '#ddd6fe',
                      background: inserted ? '#f0fdf4' : '#f5f3ff',
                    }}
                  >
                    {inserted ? '已插入' : '插入'}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Refresh */}
      <div style={{ textAlign: 'right' }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetchReports} style={{ fontSize: 11, color: '#94a3b8' }}>
          刷新
        </Button>
      </div>
    </div>
  )
}
