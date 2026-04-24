/**
 * PACS 影像工作台页面（pages/PacsWorkbenchPage.tsx）
 * DicomViewer 已提取至 components/workbench/DicomViewer.tsx。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Layout,
  Button,
  Upload,
  Select,
  message,
  Spin,
  Card,
  Typography,
  Row,
  Col,
  Tag,
  Input,
  Space,
  Alert,
  Progress,
  Steps,
} from 'antd'
import {
  UploadOutlined,
  ScanOutlined,
  CheckCircleOutlined,
  SendOutlined,
  ArrowLeftOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { useAuthedImage } from '@/services/authedImage'
import DicomViewer from '@/components/workbench/DicomViewer'

/**
 * 受鉴权 PACS 缩略图组件。
 * 后端已要求 Authorization 头（修复 PHI 泄露漏洞），
 * 这里用 useAuthedImage 把响应转成 blob URL 喂给原生 <img>。
 */
function AuthedThumbnail({
  studyId,
  filename,
  style,
}: {
  studyId: string
  filename: string
  style?: React.CSSProperties
}) {
  const { src, error } = useAuthedImage(
    `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(filename)}`
  )
  if (error) {
    return (
      <div
        style={{
          ...style,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#888',
          fontSize: 11,
          background: '#222',
        }}
      >
        加载失败
      </div>
    )
  }
  return <img src={src ?? ''} alt={filename} style={style} loading="lazy" />
}

const { Header, Content } = Layout
const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

interface Study {
  study_id: string
  patient_id: string
  modality: string
  body_part: string
  series_description: string
  total_frames: number
  status: string
  created_at: string
}

type Stage = 'list' | 'select_frames' | 'analyzing' | 'report'

export default function PacsWorkbenchPage() {
  const { user } = useAuthStore()
  const [studies, setStudies] = useState<Study[]>([])
  const [loadingStudies, setLoadingStudies] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [patients, setPatients] = useState<any[]>([])
  const [selectedPatient, setSelectedPatient] = useState<string>('')
  const [currentStudy, setCurrentStudy] = useState<any>(null)
  const [stage, setStage] = useState<Stage>('list')
  const [frames, setFrames] = useState<string[]>([])
  const [selectedFrames, setSelectedFrames] = useState<Set<string>>(new Set())
  const [previewFrame, setPreviewFrame] = useState<string>('')
  const [loadingFrames, setLoadingFrames] = useState(false)
  const [_analyzing, setAnalyzing] = useState(false)
  const [aiResult, setAiResult] = useState('')
  const [finalReport, setFinalReport] = useState('')
  const [publishing, setPublishing] = useState(false)

  useEffect(() => {
    api
      .get('/patients?page=1&page_size=100')
      .then((d: any) => setPatients(d.items || d || []))
      .catch(() => {})
  }, [])

  const loadStudies = useCallback(() => {
    setLoadingStudies(true)
    api
      .get('/pacs/studies')
      .then((d: any) => setStudies(d || []))
      .finally(() => setLoadingStudies(false))
  }, [])

  useEffect(() => {
    loadStudies()
  }, [loadStudies])

  const handleUpload = async (file: File) => {
    if (!selectedPatient) {
      message.warning('请先选择患者')
      return false
    }
    setUploading(true)
    setUploadProgress(0)
    const formData = new FormData()
    formData.append('patient_id', selectedPatient)
    formData.append('file', file)
    try {
      const res: any = await api.post('/pacs/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e: any) => setUploadProgress(Math.round((e.loaded / e.total) * 100)),
        timeout: 300000,
      })
      message.success(`上传成功！共 ${res.total_frames} 张切片，正在后台生成缩略图...`)
      loadStudies()
      openStudy(res.study_id, res.total_frames <= 10)
    } catch (e: any) {
      message.error(e?.detail || '上传失败')
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
    return false
  }

  const openStudy = async (studyId: string, autoAll = false) => {
    setLoadingFrames(true)
    try {
      const res: any = await api.get(`/pacs/${studyId}/frames`)
      setCurrentStudy({ study_id: studyId, ...res })
      setFrames(res.frames || [])
      const suggested: string[] = res.suggested || []
      setSelectedFrames(new Set(autoAll ? res.frames : suggested))
      setPreviewFrame(res.frames?.[0] || '')
      setStage('select_frames')
    } catch {
      message.error('加载切片列表失败')
    } finally {
      setLoadingFrames(false)
    }
  }

  const selectAll = () => setSelectedFrames(new Set(frames))
  const selectSuggested = () => {
    const step = Math.max(1, Math.floor(frames.length / 10))
    setSelectedFrames(new Set(frames.filter((_, i) => i % step === 0).slice(0, 10)))
  }
  const clearSelection = () => setSelectedFrames(new Set())
  const toggleFrame = (fname: string) =>
    setSelectedFrames(prev => {
      const next = new Set(prev)
      next.has(fname) ? next.delete(fname) : next.add(fname)
      return next
    })

  const runAnalysis = async () => {
    if (selectedFrames.size === 0) {
      message.warning('请至少选择 1 张关键帧')
      return
    }
    setAnalyzing(true)
    setStage('analyzing')
    try {
      const res: any = await api.post(`/pacs/${currentStudy.study_id}/analyze`, {
        selected_frames: Array.from(selectedFrames),
      })
      setAiResult(res.ai_analysis || '')
      setFinalReport(res.ai_analysis || '')
      setStage('report')
    } catch (e: any) {
      message.error(e?.detail || 'AI 分析失败')
      setStage('select_frames')
    } finally {
      setAnalyzing(false)
    }
  }

  const publishReport = async () => {
    if (!finalReport.trim()) {
      message.warning('报告内容不能为空')
      return
    }
    setPublishing(true)
    try {
      await api.post(`/pacs/${currentStudy.study_id}/publish`, { final_report: finalReport })
      message.success('报告已发布，临床医生可以查看')
      setStage('list')
      loadStudies()
    } catch {
      message.error('发布失败')
    } finally {
      setPublishing(false)
    }
  }

  const statusTag = (s: string) => {
    const map: Record<string, [string, string]> = {
      pending: ['待分析', 'default'],
      analyzing: ['分析中', 'processing'],
      analyzed: ['待审核', 'warning'],
      published: ['已发布', 'success'],
    }
    const [label, color] = map[s] || [s, 'default']
    return <Tag color={color}>{label}</Tag>
  }

  return (
    <Layout style={{ height: '100vh', background: '#f5f5f5' }}>
      <Header
        style={{
          background: '#001529',
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
          gap: 16,
        }}
      >
        <ScanOutlined style={{ color: '#1890ff', fontSize: 20 }} />
        <Title level={5} style={{ color: 'var(--surface)', margin: 0 }}>
          PACS 影像工作台
        </Title>
        <div style={{ flex: 1 }} />
        <Text style={{ color: '#999', fontSize: 12 }}>{user?.real_name} · 影像科</Text>
        <Button
          size="small"
          onClick={() => window.history.back()}
          icon={<ArrowLeftOutlined />}
          ghost
        >
          返回
        </Button>
      </Header>

      <Content style={{ padding: 24, overflow: 'auto' }}>
        {/* 阶段指示器（非 list 阶段显示，让医生直观看到当前进度） */}
        {stage !== 'list' && (
          <Card size="small" style={{ marginBottom: 16 }}>
            <Steps
              size="small"
              current={stage === 'select_frames' ? 0 : stage === 'analyzing' ? 1 : 2}
              status={stage === 'analyzing' ? 'process' : 'finish'}
              items={[
                { title: '选择关键帧', description: stage === 'select_frames' ? '勾选需要 AI 分析的影像帧' : undefined },
                { title: 'AI 分析', description: stage === 'analyzing' ? '通义千问视觉模型分析中' : undefined },
                { title: '报告审核', description: stage === 'report' ? '核对并发布最终报告' : undefined },
              ]}
            />
          </Card>
        )}

        {/* 检查列表阶段 */}
        {stage === 'list' && (
          <>
            <Card title="上传影像" style={{ marginBottom: 16 }}>
              <Row gutter={16} align="middle">
                <Col span={8}>
                  <Select
                    showSearch
                    placeholder="选择患者"
                    style={{ width: '100%' }}
                    value={selectedPatient || undefined}
                    onChange={setSelectedPatient}
                    filterOption={(input, option) =>
                      String(option?.label || '')
                        .toLowerCase()
                        .includes(input.toLowerCase())
                    }
                    options={patients.map((p: any) => ({
                      value: p.id,
                      label: `${p.name}（${p.patient_no || p.id.slice(0, 6)}）`,
                    }))}
                  />
                </Col>
                <Col>
                  <Upload
                    accept=".zip,.rar"
                    showUploadList={false}
                    beforeUpload={handleUpload}
                    disabled={uploading || !selectedPatient}
                  >
                    <Button
                      icon={<UploadOutlined />}
                      loading={uploading}
                      type="primary"
                      disabled={!selectedPatient}
                    >
                      上传 ZIP / RAR
                    </Button>
                  </Upload>
                </Col>
                {uploading && (
                  <Col flex={1}>
                    <Progress percent={uploadProgress} size="small" />
                  </Col>
                )}
              </Row>
              <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: 'block' }}>
                支持将 DCM 文件打包成 ZIP 或 RAR 后上传，系统自动解压生成缩略图
              </Text>
            </Card>

            <Card
              title="检查列表"
              extra={
                <Button size="small" icon={<ReloadOutlined />} onClick={loadStudies}>
                  刷新
                </Button>
              }
            >
              {loadingStudies ? (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <Spin />
                </div>
              ) : studies.length === 0 ? (
                <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无检查记录</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {studies.map(s => (
                    <div
                      key={s.study_id}
                      style={{
                        padding: '12px 16px',
                        background: '#fafafa',
                        borderRadius: 8,
                        border: '1px solid #e8e8e8',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 16,
                        cursor: s.status !== 'published' ? 'pointer' : 'default',
                      }}
                      onClick={() => s.status !== 'published' && openStudy(s.study_id)}
                    >
                      <div style={{ flex: 1 }}>
                        <Space>
                          <Tag color="blue">{s.modality || '未知'}</Tag>
                          <Text strong>{s.body_part || s.series_description || '未知部位'}</Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {s.total_frames} 张切片 ·{' '}
                            {new Date(s.created_at).toLocaleString('zh-CN')}
                          </Text>
                        </Space>
                      </div>
                      {statusTag(s.status)}
                      {s.status !== 'published' && (
                        <Button
                          size="small"
                          type="primary"
                          onClick={e => {
                            e.stopPropagation()
                            openStudy(s.study_id)
                          }}
                        >
                          {s.status === 'analyzed' ? '审核报告' : '开始分析'}
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )}

        {/* 选帧阶段 */}
        {stage === 'select_frames' && currentStudy && (
          <Row gutter={16}>
            <Col span={10}>
              <Card
                title={
                  <Space>
                    <span>选择关键帧</span>
                    <Tag>{selectedFrames.size} 张已选</Tag>
                  </Space>
                }
                extra={
                  <Space>
                    <Button size="small" onClick={selectSuggested}>
                      自动抽帧
                    </Button>
                    <Button size="small" onClick={selectAll}>
                      全选
                    </Button>
                    <Button size="small" onClick={clearSelection}>
                      清空
                    </Button>
                    <Button size="small" onClick={() => setStage('list')}>
                      返回
                    </Button>
                  </Space>
                }
                style={{ height: 'calc(100vh - 140px)', display: 'flex', flexDirection: 'column' }}
                bodyStyle={{ flex: 1, overflow: 'auto', padding: 8 }}
              >
                {loadingFrames ? (
                  <div style={{ textAlign: 'center', padding: 40 }}>
                    <Spin tip="加载切片列表..." />
                  </div>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
                    {frames.map(fname => (
                      <div
                        key={fname}
                        onClick={() => {
                          toggleFrame(fname)
                          setPreviewFrame(fname)
                        }}
                        style={{
                          cursor: 'pointer',
                          border: selectedFrames.has(fname)
                            ? '2px solid #1890ff'
                            : '2px solid transparent',
                          borderRadius: 4,
                          overflow: 'hidden',
                          position: 'relative',
                          background: '#111',
                          aspectRatio: '1',
                        }}
                      >
                        <AuthedThumbnail
                          studyId={currentStudy.study_id}
                          filename={fname}
                          style={{
                            width: '100%',
                            height: '100%',
                            objectFit: 'cover',
                            display: 'block',
                          }}
                        />
                        {selectedFrames.has(fname) && (
                          <div
                            style={{
                              position: 'absolute',
                              top: 2,
                              right: 2,
                              background: '#1890ff',
                              borderRadius: '50%',
                              width: 16,
                              height: 16,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <CheckCircleOutlined style={{ color: 'var(--surface)', fontSize: 10 }} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </Col>
            <Col span={14}>
              <Card
                title={`预览：${previewFrame}`}
                extra={
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    onClick={runAnalysis}
                    disabled={selectedFrames.size === 0}
                  >
                    送 AI 分析（{selectedFrames.size} 张）
                  </Button>
                }
                style={{ height: 'calc(100vh - 140px)' }}
                bodyStyle={{ padding: 12 }}
              >
                {previewFrame ? (
                  <DicomViewer studyId={currentStudy.study_id} filename={previewFrame} />
                ) : (
                  <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                    点击左侧缩略图预览
                  </div>
                )}
                <Alert
                  style={{ marginTop: 12 }}
                  type="info"
                  showIcon
                  message={`共 ${frames.length} 张切片，已选 ${selectedFrames.size} 张送 AI 分析`}
                />
              </Card>
            </Col>
          </Row>
        )}

        {/* AI 分析中 */}
        {stage === 'analyzing' && (
          <Card style={{ textAlign: 'center', padding: '48px 24px' }}>
            <Progress
              type="circle"
              percent={99}
              status="active"
              format={() => <Spin size="large" />}
              size={120}
              strokeColor={{ '0%': '#0891B2', '100%': '#06b6d4' }}
            />
            <Title level={4} style={{ marginTop: 24, marginBottom: 8 }}>
              AI 正在分析影像
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              共 {selectedFrames.size} 张关键帧发送给通义千问视觉模型，通常需要 15-30 秒
            </Text>
            <div style={{ marginTop: 16 }}>
              <Tag color="processing">模型推理中</Tag>
              <Tag color="default">无需等待，可切到其他页面</Tag>
            </div>
          </Card>
        )}

        {/* 报告审核 */}
        {stage === 'report' && (
          <Row gutter={16}>
            <Col span={12}>
              <Card title="AI 分析原文" style={{ height: 'calc(100vh - 140px)', overflow: 'auto' }}>
                <Paragraph
                  style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 13 }}
                >
                  {aiResult}
                </Paragraph>
              </Card>
            </Col>
            <Col span={12}>
              <Card
                title="最终报告（可编辑）"
                extra={
                  <Space>
                    <Button onClick={() => setStage('select_frames')}>重新选帧</Button>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      loading={publishing}
                      onClick={publishReport}
                    >
                      确认发布
                    </Button>
                  </Space>
                }
                style={{ height: 'calc(100vh - 140px)' }}
                bodyStyle={{
                  display: 'flex',
                  flexDirection: 'column',
                  height: 'calc(100% - 57px)',
                  padding: 12,
                }}
              >
                <TextArea
                  value={finalReport}
                  onChange={e => setFinalReport(e.target.value)}
                  style={{ flex: 1, fontFamily: 'monospace', fontSize: 13, resize: 'none' }}
                />
              </Card>
            </Col>
          </Row>
        )}
      </Content>
    </Layout>
  )
}
