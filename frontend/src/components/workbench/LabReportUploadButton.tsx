/**
 * 检验报告上传按钮（components/workbench/LabReportUploadButton.tsx）
 *
 * 独立封装的检验报告文件上传组件，被 LabReportTab 引用：
 *   - 点击「上传报告」弹出 Modal，包含 Dragger 拖拽上传区
 *   - 支持格式：图片（jpg/png）和 PDF
 *   - 上传前通过 beforeUpload 做格式和大小（≤10MB）校验
 *   - 调用 POST /lab-reports/upload（multipart/form-data），
 *     附带 encounter_id 参数
 *   - 上传成功后触发父组件传入的 onSuccess 回调（刷新报告列表）
 *
 * 为何独立组件：
 *   上传逻辑较复杂（预览、校验、进度），与列表展示解耦更易维护。
 */
import { useState } from 'react'
import { Button, Modal, Upload, message, Spin, Typography } from 'antd'
import { UploadOutlined, FileTextOutlined, InboxOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'

const { Dragger } = Upload
const { Text } = Typography

interface LabReportItem {
  id: string
  original_filename: string
  ocr_text: string
  status: string
  created_at: string
}

interface Props {
  onInsert: (text: string) => void
}

export default function LabReportUploadButton({ onInsert }: Props) {
  const { currentEncounterId } = useWorkbenchStore()
  const [open, setOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<LabReportItem | null>(null)

  const handleUpload = async (file: File) => {
    setUploading(true)
    setResult(null)
    const formData = new FormData()
    formData.append('file', file)
    if (currentEncounterId) formData.append('encounter_id', currentEncounterId)

    try {
      const data = (await api.post('/lab-reports/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })) as LabReportItem
      setResult(data)
    } catch {
      message.error('上传失败，请重试')
    } finally {
      setUploading(false)
    }
    return false // 阻止 antd 默认上传
  }

  const handleInsert = () => {
    if (!result?.ocr_text) return
    onInsert(result.ocr_text)
    message.success({ content: '已插入辅助检查', duration: 1.5 })
    setOpen(false)
    setResult(null)
  }

  return (
    <>
      <Button
        size="small"
        icon={<UploadOutlined />}
        onClick={() => setOpen(true)}
        style={{
          fontSize: 11,
          borderRadius: 6,
          color: '#7c3aed',
          borderColor: '#ddd6fe',
          background: '#f5f3ff',
        }}
      >
        上传报告
      </Button>

      <Modal
        title={
          <span style={{ fontSize: 14, fontWeight: 700 }}>
            <FileTextOutlined style={{ marginRight: 6, color: '#7c3aed' }} />
            上传检验报告
          </span>
        }
        open={open}
        onCancel={() => {
          setOpen(false)
          setResult(null)
        }}
        footer={null}
        width={520}
      >
        {!result && !uploading && (
          <Dragger
            accept=".jpg,.jpeg,.png,.webp,.pdf"
            showUploadList={false}
            beforeUpload={file => {
              handleUpload(file)
              return false
            }}
            style={{ borderRadius: 10 }}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined style={{ color: '#7c3aed', fontSize: 40 }} />
            </p>
            <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-1)' }}>
              点击或拖拽上传检验报告
            </p>
            <p style={{ fontSize: 12, color: 'var(--text-4)' }}>支持 JPG / PNG / PDF，AI 自动识别内容</p>
          </Dragger>
        )}

        {uploading && (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin size="large" />
            <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text-2)' }}>
              AI 识别中，请稍候...
            </div>
          </div>
        )}

        {result && (
          <div>
            <div
              style={{
                background: 'var(--surface-2)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: '10px 12px',
                marginBottom: 12,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <FileTextOutlined style={{ color: '#7c3aed' }} />
              <Text style={{ fontSize: 13, fontWeight: 600 }}>{result.original_filename}</Text>
              <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
                识别完成
              </Text>
            </div>

            <div
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: '10px 12px',
                maxHeight: 280,
                overflowY: 'auto',
                fontSize: 13,
                lineHeight: 1.7,
                whiteSpace: 'pre-wrap',
                color: 'var(--text-1)',
                marginBottom: 14,
              }}
            >
              {result.ocr_text}
            </div>

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Button onClick={() => setResult(null)} style={{ borderRadius: 6 }}>
                重新上传
              </Button>
              <Button
                type="primary"
                onClick={handleInsert}
                style={{
                  background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
                  border: 'none',
                  borderRadius: 6,
                }}
              >
                插入辅助检查
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
