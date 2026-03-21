import { useEffect, useState } from 'react'
import { Button, Empty, Spin, message, Typography, Collapse, Tag } from 'antd'
import { FileTextOutlined, CopyOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography

interface LabReportItem {
  id: string
  original_filename: string
  ocr_text: string
  status: string
  created_at: string
}

export default function LabReportTab() {
  const { currentEncounterId, inquiry, setInquiry } = useWorkbenchStore()
  const [reports, setReports] = useState<LabReportItem[]>([])
  const [loading, setLoading] = useState(false)

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

  useEffect(() => {
    fetchReports()
  }, [currentEncounterId])

  const handleInsert = (ocr_text: string) => {
    const existing = inquiry.auxiliary_exam?.trim() || ''
    const newVal = existing ? existing + '\n' + ocr_text : ocr_text
    setInquiry({ ...inquiry, auxiliary_exam: newVal })
    message.success({ content: '已插入辅助检查', duration: 1.5 })
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/lab-reports/${id}`)
      setReports((prev) => prev.filter((r) => r.id !== id))
      message.success({ content: '已删除', duration: 1.5 })
    } catch {
      message.error('删除失败')
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="small" />
        <div style={{ marginTop: 8, fontSize: 12, color: '#94a3b8' }}>加载中...</div>
      </div>
    )
  }

  if (reports.length === 0) {
    return (
      <div style={{ padding: '0 12px' }}>
        <Empty
          description={<span style={{ fontSize: 13, color: '#94a3b8' }}>暂无检验报告，点击辅助检查旁「上传报告」添加</span>}
          style={{ marginTop: 40 }}
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
        <div style={{ textAlign: 'center', marginTop: 8 }}>
          <Button size="small" icon={<ReloadOutlined />} onClick={fetchReports} style={{ fontSize: 12 }}>
            刷新
          </Button>
        </div>
      </div>
    )
  }

  const items = reports.map((r) => ({
    key: r.id,
    label: (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%' }}>
        <FileTextOutlined style={{ color: '#7c3aed', flexShrink: 0 }} />
        <Text style={{ fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {r.original_filename || '检验报告'}
        </Text>
        <Tag color="purple" style={{ fontSize: 10, margin: 0, flexShrink: 0 }}>已识别</Tag>
      </div>
    ),
    children: (
      <div>
        <div style={{
          background: '#fafafa',
          border: '1px solid #e2e8f0',
          borderRadius: 6,
          padding: '8px 10px',
          fontSize: 12,
          lineHeight: 1.7,
          whiteSpace: 'pre-wrap',
          color: '#1e293b',
          maxHeight: 240,
          overflowY: 'auto',
          marginBottom: 10,
        }}>
          {r.ocr_text || '（无识别内容）'}
        </div>
        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <Button
            size="small"
            icon={<DeleteOutlined />}
            danger
            onClick={() => handleDelete(r.id)}
            style={{ fontSize: 11, borderRadius: 5 }}
          >
            删除
          </Button>
          <Button
            size="small"
            icon={<CopyOutlined />}
            onClick={() => handleInsert(r.ocr_text)}
            style={{
              fontSize: 11, borderRadius: 5,
              color: '#7c3aed', borderColor: '#ddd6fe',
              background: '#f5f3ff',
            }}
          >
            插入辅助检查
          </Button>
        </div>
        <Text type="secondary" style={{ fontSize: 10 }}>
          {r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : ''}
        </Text>
      </div>
    ),
  }))

  return (
    <div style={{ padding: '8px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetchReports} style={{ fontSize: 11 }}>
          刷新
        </Button>
      </div>
      <Collapse
        size="small"
        items={items}
        style={{ borderRadius: 8 }}
      />
    </div>
  )
}
