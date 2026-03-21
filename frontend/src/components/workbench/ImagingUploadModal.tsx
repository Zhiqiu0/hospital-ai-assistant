import { useState, useRef } from 'react'
import { Modal, Button, Select, Input, message, Spin, Typography } from 'antd'
import { CameraOutlined, UploadOutlined, CheckOutlined } from '@ant-design/icons'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'

const { Text } = Typography

interface Props {
  open: boolean
  onClose: () => void
}

const IMAGE_TYPES = [
  { value: '', label: '不指定类型' },
  { value: '胸部X光', label: '胸部X光' },
  { value: '胸部CT', label: '胸部CT' },
  { value: '腹部CT', label: '腹部CT' },
  { value: '头颅CT', label: '头颅CT' },
  { value: '腹部超声', label: '腹部超声' },
  { value: '心脏超声', label: '心脏超声' },
  { value: '脑部MRI', label: '脑部MRI' },
  { value: '骨骼X光', label: '骨骼X光' },
  { value: '其他', label: '其他' },
]

export default function ImagingUploadModal({ open, onClose }: Props) {
  const { inquiry, setInquiry } = useWorkbenchStore()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [imageType, setImageType] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState('')
  const [inserted, setInserted] = useState(false)

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const allowed = ['image/jpeg', 'image/png', 'image/webp']
    if (!allowed.includes(file.type)) {
      message.error('仅支持 JPG / PNG / WebP 格式')
      return
    }
    setSelectedFile(file)
    setAnalysisResult('')
    setInserted(false)
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
  }

  const handleAnalyze = async () => {
    if (!selectedFile) {
      message.warning('请先选择影像图片')
      return
    }
    setAnalyzing(true)
    setAnalysisResult('')
    try {
      const form = new FormData()
      form.append('file', selectedFile)
      form.append('image_type', imageType)
      const res: any = await api.post('/pacs/analyze-image', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setAnalysisResult(res.analysis || '（未返回分析内容）')
    } catch (err: any) {
      message.error(err?.detail || 'AI分析失败，请重试')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleInsert = () => {
    const existing = inquiry.auxiliary_exam?.trim()
    const newVal = existing ? existing + '\n' + analysisResult : analysisResult
    setInquiry({ ...inquiry, auxiliary_exam: newVal })
    setInserted(true)
    message.success('已插入辅助检查')
  }

  const handleClose = () => {
    setSelectedFile(null)
    setPreviewUrl(null)
    setImageType('')
    setAnalysisResult('')
    setInserted(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
    onClose()
  }

  return (
    <Modal
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 8,
            background: 'linear-gradient(135deg, #7c3aed, #a855f7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <CameraOutlined style={{ color: '#fff', fontSize: 13 }} />
          </div>
          <span>影像AI分析</span>
        </span>
      }
      open={open}
      onCancel={handleClose}
      footer={null}
      width={680}
      styles={{ body: { padding: '20px 24px' } }}
    >
      {/* Upload area */}
      <div
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${selectedFile ? '#a855f7' : '#d1d5db'}`,
          borderRadius: 12,
          padding: '24px 20px',
          textAlign: 'center',
          cursor: 'pointer',
          background: selectedFile ? '#faf5ff' : '#f9fafb',
          transition: 'all 0.2s',
          marginBottom: 16,
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        {previewUrl ? (
          <div>
            <img
              src={previewUrl}
              alt="preview"
              style={{ maxHeight: 200, maxWidth: '100%', borderRadius: 8, marginBottom: 8 }}
            />
            <div style={{ fontSize: 12, color: '#7c3aed' }}>
              {selectedFile?.name} · 点击重新选择
            </div>
          </div>
        ) : (
          <div>
            <UploadOutlined style={{ fontSize: 32, color: '#9ca3af', marginBottom: 8 }} />
            <div style={{ fontSize: 14, color: '#6b7280' }}>点击上传影像图片</div>
            <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>支持 JPG / PNG / WebP</div>
          </div>
        )}
      </div>

      {/* Image type + analyze button */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        <Select
          value={imageType}
          onChange={setImageType}
          style={{ flex: 1 }}
          placeholder="选择影像类型（可选）"
          options={IMAGE_TYPES}
        />
        <Button
          type="primary"
          onClick={handleAnalyze}
          disabled={!selectedFile || analyzing}
          loading={analyzing}
          style={{
            background: 'linear-gradient(135deg, #7c3aed, #a855f7)',
            border: 'none',
            borderRadius: 8,
            fontWeight: 600,
            paddingInline: 24,
          }}
        >
          AI 分析
        </Button>
      </div>

      {/* Result area */}
      {analyzing && (
        <div style={{ textAlign: 'center', padding: '32px 0', color: '#7c3aed' }}>
          <Spin />
          <div style={{ marginTop: 8, fontSize: 13, color: '#9ca3af' }}>正在分析影像，请稍候...</div>
        </div>
      )}
      {analysisResult && !analyzing && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 }}>AI 分析结果</div>
          <Input.TextArea
            value={analysisResult}
            onChange={(e) => setAnalysisResult(e.target.value)}
            rows={8}
            style={{ borderRadius: 8, fontSize: 13, fontFamily: 'inherit', marginBottom: 12 }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Text style={{ fontSize: 12, color: '#94a3b8', alignSelf: 'center' }}>
              {inserted ? '已插入辅助检查 ✓' : '可直接编辑后插入'}
            </Text>
            <Button
              type="primary"
              icon={inserted ? <CheckOutlined /> : undefined}
              onClick={handleInsert}
              disabled={inserted}
              style={{
                background: inserted ? '#22c55e' : 'linear-gradient(135deg, #2563eb, #3b82f6)',
                border: 'none',
                borderRadius: 8,
              }}
            >
              {inserted ? '已插入' : '插入辅助检查'}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  )
}
