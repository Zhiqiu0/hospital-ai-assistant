/**
 * 影像上传弹窗（components/workbench/ImagingUploadModal.tsx）
 *
 * 用于上传患者影像资料（X光/CT/MRI）并关联到当前接诊：
 *   - 支持文件选择（jpg/png/dcm）和摄像头拍照（useRef<HTMLVideoElement>）
 *   - 上传前选择影像类型（exam_type）和检查部位（body_part）
 *   - 调用 POST /pacs/upload（multipart/form-data）
 *   - 上传成功后通知 PACS 工作台刷新影像列表
 *
 * DICOM 文件：
 *   .dcm 文件由后端 pydicom 解析，转换为可在浏览器显示的 PNG 缩略图。
 *   前端不做 DICOM 解析，仅透传二进制文件。
 *
 * 摄像头拍照：
 *   navigator.mediaDevices.getUserMedia() 获取视频流，
 *   canvas.toBlob() 截帧后作为 File 对象上传。
 *
 * ── 2026-05-03 重构 ───────────────────────────────────────────────────────
 * 不再"插入辅助检查"——AI 分析结果只在弹窗内展示供医生查看，不再写
 * inquiry.auxiliary_exam，避免跟新接管【辅助检查】章节的 ExamSuggestionTab
 * 互相覆盖。下次迭代独立"影像所见"章节时再补回写入入口。
 */
import { useState, useRef } from 'react'
import { Modal, Button, Select, Input, message, Spin } from 'antd'
import { CameraOutlined, UploadOutlined } from '@ant-design/icons'
import api from '@/services/api'

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
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [imageType, setImageType] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisResult, setAnalysisResult] = useState('')

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const allowedTypes = ['image/jpeg', 'image/png', 'image/webp']
    const isDcm = file.name.toLowerCase().endsWith('.dcm')
    if (!isDcm && !allowedTypes.includes(file.type)) {
      message.error('仅支持 JPG / PNG / WebP / DCM 格式')
      return
    }
    setSelectedFile(file)
    setAnalysisResult('')
    if (isDcm) {
      setPreviewUrl(null) // 浏览器无法直接预览 DCM
    } else {
      setPreviewUrl(URL.createObjectURL(file))
    }
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

  const handleClose = () => {
    setSelectedFile(null)
    setPreviewUrl(null)
    setImageType('')
    setAnalysisResult('')
    if (fileInputRef.current) fileInputRef.current.value = ''
    onClose()
  }

  return (
    <Modal
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #7c3aed, #a855f7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <CameraOutlined style={{ color: 'var(--surface)', fontSize: 13 }} />
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
          accept="image/jpeg,image/png,image/webp,.dcm"
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />
        {selectedFile ? (
          <div>
            {previewUrl ? (
              <img
                src={previewUrl}
                alt="preview"
                style={{ maxHeight: 200, maxWidth: '100%', borderRadius: 8, marginBottom: 8 }}
              />
            ) : (
              <div style={{ fontSize: 36, marginBottom: 8 }}>🩻</div>
            )}
            <div style={{ fontSize: 12, color: '#7c3aed' }}>{selectedFile.name} · 点击重新选择</div>
          </div>
        ) : (
          <div>
            <UploadOutlined style={{ fontSize: 32, color: '#9ca3af', marginBottom: 8 }} />
            <div style={{ fontSize: 14, color: '#6b7280' }}>点击上传影像图片</div>
            <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>
              支持 JPG / PNG / WebP / DCM
            </div>
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
          <div style={{ marginTop: 8, fontSize: 13, color: '#9ca3af' }}>
            正在分析影像，请稍候...
          </div>
        </div>
      )}
      {analysisResult && !analyzing && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
            AI 分析结果
          </div>
          <Input.TextArea
            value={analysisResult}
            onChange={e => setAnalysisResult(e.target.value)}
            rows={8}
            style={{ borderRadius: 8, fontSize: 13, fontFamily: 'inherit', marginBottom: 8 }}
          />
          <div
            style={{
              fontSize: 11,
              color: 'var(--text-4)',
              padding: '6px 10px',
              background: 'var(--surface-2)',
              borderRadius: 6,
            }}
          >
            ℹ️ 当前过渡期 AI 分析结果仅供查看，暂不写入病历；后续将开通独立的「影像所见」章节
          </div>
        </div>
      )}
    </Modal>
  )
}
