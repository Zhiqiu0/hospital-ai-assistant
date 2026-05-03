/**
 * 检验报告标签页（components/workbench/LabReportTab.tsx）
 * 报告卡片已提取至 LabReportCard.tsx。
 *
 * ── 2026-05-03 重构 ───────────────────────────────────────────────────────
 * 不再"插入辅助检查"——OCR 识别结果只在 tab 内展示（点卡片展开看 OCR 文本），
 * 不再写 inquiry.auxiliary_exam，避免跟新接管【辅助检查】章节的 ExamSuggestionTab
 * 互相覆盖。下次迭代独立"检验结果"章节时再补回写入入口。
 */
import { useEffect, useState } from 'react'
import { Button, Empty, Spin, message, Upload } from 'antd'
import { ReloadOutlined, InboxOutlined } from '@ant-design/icons'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
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

export default function LabReportTab() {
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)
  const currentPatient = useCurrentPatient()
  const [reports, setReports] = useState<LabReportItem[]>([])
  const [loading, setLoading] = useState(false)
  const [uploadingCount, setUploadingCount] = useState(0)
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

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/lab-reports/${id}`)
      setReports(prev => prev.filter(r => r.id !== id))
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
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>
              点击或拖拽上传检验报告
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-4)' }}>支持 JPG / PNG / PDF</div>
          </div>
        )}
      </Dragger>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '20px 0' }}>
          <Spin size="small" />
        </div>
      ) : reports.length === 0 ? (
        <Empty
          description={<span style={{ fontSize: 12, color: 'var(--text-4)' }}>暂无检验报告</span>}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ margin: '16px 0' }}
        />
      ) : (
        <div
          style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}
        >
          {reports.map(r => (
            <LabReportCard
              key={r.id}
              report={r}
              expanded={expandedId === r.id}
              currentPatientName={currentPatient?.name}
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
          style={{ fontSize: 11, color: 'var(--text-4)' }}
        >
          刷新
        </Button>
      </div>
    </div>
  )
}
