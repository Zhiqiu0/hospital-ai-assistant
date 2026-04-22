/**
 * 检验报告标签页（components/workbench/LabReportTab.tsx）
 * 报告卡片已提取至 LabReportCard.tsx。
 */
import { useEffect, useState } from 'react'
import { Button, Empty, Spin, message, Upload, Modal } from 'antd'
import { ReloadOutlined, InboxOutlined, PlusOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import LabReportCard from './LabReportCard'
import api from '@/services/api'

const { Dragger } = Upload

interface LabReportItem {
  id: string
  original_filename: string
  ocr_text: string
  status: string
  created_at: string
}

function extractReportType(text: string): string {
  return text.match(/【报告类型】([^\n【]+)/)?.[1]?.trim() || '未知类型'
}

function extractPatientName(text: string): string {
  return text.match(/姓名[：:]\s*([^\s\n]+)/)?.[1]?.trim() || ''
}

function smartInsert(existing: string, newReport: string): string {
  if (!existing.trim()) return newReport
  const newType = extractReportType(newReport)
  if (newType === '未知类型') return existing.trimEnd() + '\n\n' + newReport
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
      const data = (await api.get(
        `/lab-reports/?encounter_id=${currentEncounterId}`
      )) as LabReportItem[]
      setReports(data)
    } catch {
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReports()
    setInsertedIds(new Set())
  }, [currentEncounterId])

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
      const data = (await api.post('/lab-reports/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })) as LabReportItem
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
    const newVal = smartInsert(inquiry.auxiliary_exam?.trim() || '', report.ocr_text)
    const newInquiry = { ...inquiry, auxiliary_exam: newVal }
    setInquiry(newInquiry)
    if (currentEncounterId)
      api.put(`/encounters/${currentEncounterId}/inquiry`, newInquiry).catch(() => {})
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
      for (const r of reports) current = smartInsert(current, r.ocr_text)
      const newInquiry = { ...inquiry, auxiliary_exam: current }
      setInquiry(newInquiry)
      if (currentEncounterId)
        api.put(`/encounters/${currentEncounterId}/inquiry`, newInquiry).catch(() => {})
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
      setInsertedIds(prev => {
        const s = new Set(prev)
        s.delete(id)
        return s
      })
      message.success({ content: '已删除', duration: 1.5 })
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        padding: '8px 12px',
        gap: 10,
      }}
    >
      <Dragger
        accept=".jpg,.jpeg,.png,.webp,.pdf"
        multiple
        showUploadList={false}
        beforeUpload={file => {
          handleUpload(file)
          return false
        }}
        disabled={uploadingCount > 0}
        style={{ borderRadius: 8, padding: 0 }}
      >
        {uploadingCount > 0 ? (
          <div style={{ padding: '12px 0', textAlign: 'center' }}>
            <Spin size="small" />
            <div style={{ fontSize: 12, color: '#7c3aed', marginTop: 6 }}>
              AI 识别中{uploadingCount > 1 ? `（${uploadingCount} 份）` : ''}...
            </div>
          </div>
        ) : (
          <div style={{ padding: '10px 0', textAlign: 'center' }}>
            <InboxOutlined style={{ fontSize: 22, color: '#7c3aed' }} />
            <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>
              点击或拖拽上传检验报告
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>支持 JPG / PNG / PDF</div>
          </div>
        )}
      </Dragger>

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
        <div
          style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={handleInsertAll}
            block
            style={{
              borderRadius: 6,
              fontSize: 12,
              height: 28,
              color: '#7c3aed',
              borderColor: '#ddd6fe',
              background: '#f5f3ff',
            }}
          >
            一键插入全部（{reports.length} 份）
          </Button>
          {reports.map(r => (
            <LabReportCard
              key={r.id}
              report={r}
              inserted={insertedIds.has(r.id)}
              expanded={expandedId === r.id}
              currentPatientName={currentPatient?.name}
              onInsert={() => handleInsert(r)}
              onDelete={() => handleDelete(r.id)}
              onToggleExpand={() => setExpandedId(expandedId === r.id ? null : r.id)}
            />
          ))}
        </div>
      )}

      <div style={{ textAlign: 'right' }}>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={fetchReports}
          style={{ fontSize: 11, color: '#94a3b8' }}
        >
          刷新
        </Button>
      </div>
    </div>
  )
}
