/**
 * PACS 影像工作台页面（pages/PacsWorkbenchPage.tsx）
 *
 * 放射科/影像科专用工作台，主要功能：
 *   - 影像上传：支持 DICOM(.dcm)、JPG/PNG，调用 POST /pacs/upload
 *   - 影像列表：GET /pacs/images，展示缩略图、检查类型、患者信息
 *   - DICOM 查看：点击影像调用 GET /pacs/images/{id}/dicom-url，
 *     在内嵌 iframe 或新标签打开 OHIF Viewer
 *   - AI 报告生成：POST /ai/generate-radiology-report，SSE stream
 *   - 报告编辑与提交：PUT /pacs/reports/{id}
 *
 * 角色权限：
 *   放射科技师（radiologist）：上传影像、查看全部影像
 *   普通医生（doctor）：只能查看自己接诊患者的影像
 *
 * 进度展示：
 *   大文件上传使用 Ant Design Progress 组件显示上传进度（onUploadProgress）。
 */
import { useState, useEffect, useRef, useCallback } from 'react'
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

const { Header, Content } = Layout
const { Title, Text, Paragraph } = Typography
const { TextArea } = Input

// ─── 类型 ────────────────────────────────────────────────────────────────────

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

// ─── Cornerstone 影像查看器 ──────────────────────────────────────────────────

function DicomViewer({ studyId, filename }: { studyId: string; filename: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [wc, setWc] = useState(50)
  const [ww, setWw] = useState(350)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadImage = useCallback(
    (wcVal: number, wwVal: number, customWin: boolean) => {
      if (!filename) return
      setLoading(true)
      setError('')
      const url = customWin
        ? `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(filename)}?wc=${wcVal}&ww=${wwVal}`
        : `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(filename)}`
      const img = new Image()
      img.onload = () => {
        if (!canvasRef.current) return
        const canvas = canvasRef.current
        canvas.width = img.width
        canvas.height = img.height
        const ctx = canvas.getContext('2d')
        ctx?.drawImage(img, 0, 0)
        setLoading(false)
      }
      img.onerror = () => {
        setError('影像加载失败')
        setLoading(false)
      }
      img.src = url
    },
    [studyId, filename]
  )

  useEffect(() => {
    setWc(50)
    setWw(350)
    loadImage(50, 350, false)
  }, [studyId, filename])

  const handleWcChange = (val: number) => {
    setWc(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadImage(val, ww, true), 400)
  }

  const handleWwChange = (val: number) => {
    setWw(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadImage(wc, val, true), 400)
  }

  return (
    <div
      style={{
        background: '#000',
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative',
        minHeight: 400,
      }}
    >
      {loading && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Spin tip="加载影像..." />
        </div>
      )}
      {error && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: '#fff' }}>{error}</Text>
        </div>
      )}
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block', maxHeight: 480 }}
      />
      <div
        style={{
          padding: '8px 12px',
          background: '#111',
          display: 'flex',
          gap: 16,
          alignItems: 'center',
        }}
      >
        <Text style={{ color: '#999', fontSize: 12 }}>窗位(WC)</Text>
        <input
          type="range"
          min={-200}
          max={400}
          value={wc}
          onChange={e => handleWcChange(Number(e.target.value))}
          style={{ flex: 1 }}
        />
        <Text style={{ color: '#fff', fontSize: 12, minWidth: 30 }}>{wc}</Text>
        <Text style={{ color: '#999', fontSize: 12 }}>窗宽(WW)</Text>
        <input
          type="range"
          min={1}
          max={2000}
          value={ww}
          onChange={e => handleWwChange(Number(e.target.value))}
          style={{ flex: 1 }}
        />
        <Text style={{ color: '#fff', fontSize: 12, minWidth: 40 }}>{ww}</Text>
      </div>
    </div>
  )
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export default function PacsWorkbenchPage() {
  const { user } = useAuthStore()

  // 工作列表
  const [studies, setStudies] = useState<Study[]>([])
  const [loadingStudies, setLoadingStudies] = useState(false)

  // 上传
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [patients, setPatients] = useState<any[]>([])
  const [selectedPatient, setSelectedPatient] = useState<string>('')

  // 当前工作中的检查
  const [currentStudy, setCurrentStudy] = useState<any>(null)
  const [stage, setStage] = useState<Stage>('list')

  // 帧选择
  const [frames, setFrames] = useState<string[]>([])
  const [selectedFrames, setSelectedFrames] = useState<Set<string>>(new Set())
  const [previewFrame, setPreviewFrame] = useState<string>('')
  const [loadingFrames, setLoadingFrames] = useState(false)

  // AI 分析
  const [_analyzing, setAnalyzing] = useState(false)
  const [aiResult, setAiResult] = useState('')
  const [finalReport, setFinalReport] = useState('')
  const [publishing, setPublishing] = useState(false)

  // 加载患者列表
  useEffect(() => {
    api
      .get('/patients?page=1&page_size=100')
      .then((d: any) => {
        setPatients(d.items || d || [])
      })
      .catch(() => {})
  }, [])

  // 加载检查列表
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

  // ── 上传 ZIP ──────────────────────────────────────────────────────────────

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
        onUploadProgress: (e: any) => {
          setUploadProgress(Math.round((e.loaded / e.total) * 100))
        },
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

  // ── 打开检查 ──────────────────────────────────────────────────────────────

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

  // ── 全选 / 自动抽帧 ───────────────────────────────────────────────────────

  const selectAll = () => setSelectedFrames(new Set(frames))
  const selectSuggested = () => {
    const step = Math.max(1, Math.floor(frames.length / 10))
    setSelectedFrames(new Set(frames.filter((_, i) => i % step === 0).slice(0, 10)))
  }
  const clearSelection = () => setSelectedFrames(new Set())

  const toggleFrame = (fname: string) => {
    setSelectedFrames(prev => {
      const next = new Set(prev)
      next.has(fname) ? next.delete(fname) : next.add(fname)
      return next
    })
  }

  // ── AI 分析 ───────────────────────────────────────────────────────────────

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

  // ── 发布报告 ──────────────────────────────────────────────────────────────

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

  // ─── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <Layout style={{ height: '100vh', background: '#f5f5f5' }}>
      {/* 顶栏 */}
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
        <Title level={5} style={{ color: '#fff', margin: 0 }}>
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
        {/* ── 阶段：检查列表 ── */}
        {stage === 'list' && (
          <>
            {/* 上传区 */}
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

            {/* 检查列表 */}
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

        {/* ── 阶段：选帧 ── */}
        {stage === 'select_frames' && currentStudy && (
          <Row gutter={16}>
            {/* 左：缩略图网格 */}
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
                        <img
                          src={`/api/v1/pacs/${currentStudy.study_id}/thumbnail/${encodeURIComponent(fname)}`}
                          alt={fname}
                          style={{
                            width: '100%',
                            height: '100%',
                            objectFit: 'cover',
                            display: 'block',
                          }}
                          loading="lazy"
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
                            <CheckCircleOutlined style={{ color: '#fff', fontSize: 10 }} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </Col>

            {/* 右：预览 + 操作 */}
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

        {/* ── 阶段：AI 分析中 ── */}
        {stage === 'analyzing' && (
          <div style={{ textAlign: 'center', padding: 80 }}>
            <Spin size="large" />
            <br />
            <br />
            <Title level={4}>AI 正在分析影像...</Title>
            <Text type="secondary">
              正在将 {selectedFrames.size} 张关键帧发送给通义千问分析，请稍候
            </Text>
          </div>
        )}

        {/* ── 阶段：报告审核 ── */}
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
