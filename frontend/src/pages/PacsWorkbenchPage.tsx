/**
 * PACS 影像工作台页面（pages/PacsWorkbenchPage.tsx）
 * DicomViewer 已提取至 components/workbench/DicomViewer.tsx。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
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
  DeleteOutlined,
} from '@ant-design/icons'
import { Popconfirm } from 'antd'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { useAuthedImage } from '@/services/authedImage'
import DicomViewer from '@/components/workbench/DicomViewer'

/**
 * 受鉴权 PACS 缩略图组件。
 * R1 后路径参数为 SOPInstanceUID（DICOM 标准），不是文件名。
 * 后端已要求 Authorization 头（修复 PHI 泄露漏洞），
 * 这里用 useAuthedImage 把响应转成 blob URL 喂给原生 <img>。
 */
function AuthedThumbnail({
  studyId,
  instanceUid,
  seriesUid,
  style,
}: {
  studyId: string
  instanceUid: string
  /** 可选：传上来后端免一次反查（537 帧 study 加载从分钟级降到秒级） */
  seriesUid?: string
  style?: React.CSSProperties
}) {
  // IntersectionObserver lazy-fetch：未进入视口的缩略图不发请求。
  // rootMargin=0 仅视口内才加载，避免 537 张同时挤进浏览器 6 路并发队列。
  // 滚动时图按需补，比预加载远端图更重要——后端单帧 0.6s + 6 路并发，
  // 一屏 16 张图 ~2s 出齐，预加载只会把后面的请求排队压死前面的。
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = containerRef.current
    if (!el || inView) return
    const io = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setInView(true)
          io.disconnect()
        }
      },
      { rootMargin: '50px' }, // 仅视口边缘 50px 提前加载（滚动时不至于太突兀）
    )
    io.observe(el)
    return () => io.disconnect()
  }, [inView])

  const url =
    inView && (seriesUid
      ? `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(instanceUid)}?series_uid=${encodeURIComponent(seriesUid)}`
      : `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(instanceUid)}`)

  const { src, error } = useAuthedImage(url || null)
  return (
    <div ref={containerRef} style={style}>
      {error ? (
        <div
          style={{
            width: '100%',
            height: '100%',
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
      ) : src ? (
        <img
          src={src}
          alt={instanceUid.slice(-12)}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : null}
    </div>
  )
}

/** R1 后端返回的帧描述：SOPInstanceUID + 所属 series + DICOM InstanceNumber */
interface Frame {
  instance_uid: string
  series_uid: string
  instance_number: number
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
  // R1：frames 由 instance_uid + series_uid + instance_number 组成
  const [frames, setFrames] = useState<Frame[]>([])
  // selectedFrames / previewFrame 内容均为 instance_uid（字符串）
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
      // 后端返回 duplicate=true 表示同患者同 DICOM 包二次上传，幂等返回原 study_id
      if (res.duplicate) {
        message.info(res.message || '该影像之前已上传过，已为你定位到原记录')
      } else {
        message.success(`上传成功！共 ${res.total_frames} 张切片，正在后台生成缩略图...`)
      }
      loadStudies()
      openStudy(res.study_id, res.total_frames <= 10)
    } catch (e: any) {
      // 跨患者重复（HTTP 409）单独提示，让医生意识到是选错了患者
      if (e?.status === 409 || e?.response?.status === 409) {
        message.warning(e?.detail || e?.response?.data?.detail || '该影像已绑定其他患者')
      } else {
        message.error(e?.detail || '上传失败')
      }
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
      const allFrames: Frame[] = res.frames || []
      // 后端 suggested 是 instance_uid 字符串数组（已做智能非均匀抽样）
      const suggestedUids: string[] = res.suggested || []
      setFrames(allFrames)
      const allUids = allFrames.map(f => f.instance_uid)
      setSelectedFrames(new Set(autoAll ? allUids : suggestedUids))
      setPreviewFrame(allFrames[0]?.instance_uid || '')
      setStage('select_frames')
    } catch {
      message.error('加载切片列表失败')
    } finally {
      setLoadingFrames(false)
    }
  }

  const selectAll = () => setSelectedFrames(new Set(frames.map(f => f.instance_uid)))
  /** 调用后端 suggested 列表的本地兜底：等距抽样 10 帧 */
  const selectSuggested = () => {
    const step = Math.max(1, Math.floor(frames.length / 10))
    setSelectedFrames(
      new Set(frames.filter((_, i) => i % step === 0).slice(0, 10).map(f => f.instance_uid))
    )
  }
  const clearSelection = () => setSelectedFrames(new Set())
  const toggleFrame = (uid: string) =>
    setSelectedFrames(prev => {
      const next = new Set(prev)
      next.has(uid) ? next.delete(uid) : next.add(uid)
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

  /** 删除影像研究（含 Orthanc 端数据 + 业务表）。
   *  已发布的 study 后端会拒绝（409），前端只在未发布的状态下显示按钮。 */
  const deleteStudy = async (studyId: string) => {
    try {
      await api.delete(`/pacs/${studyId}`)
      message.success('已删除')
      loadStudies()
    } catch (e: any) {
      const detail = e?.detail || e?.response?.data?.detail || '删除失败'
      message.error(detail)
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
                    accept=".zip,.rar,.7z,.tar,.tar.gz,.tgz,.tar.bz2,.tbz,.tbz2,.tar.xz,.txz,.iso,.gz,.bz2,.xz"
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
                      上传压缩包
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
                支持 ZIP / RAR / 7Z / TAR / TAR.GZ / TBZ / ISO 等常见压缩格式，系统自动解压并 STOW 到 Orthanc
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
                      {/* 已发布的不可删（医疗审计合规），其他状态可删 */}
                      {s.status !== 'published' && (
                        <Popconfirm
                          title="确认删除该影像？"
                          description="将同时清理 Orthanc 中的 DICOM 文件和业务记录，不可恢复。"
                          okText="删除"
                          cancelText="取消"
                          okType="danger"
                          onConfirm={e => {
                            e?.stopPropagation()
                            deleteStudy(s.study_id)
                          }}
                          onCancel={e => e?.stopPropagation()}
                        >
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={e => e.stopPropagation()}
                          />
                        </Popconfirm>
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
                    {frames.map(frame => {
                      const uid = frame.instance_uid
                      const selected = selectedFrames.has(uid)
                      return (
                        <div
                          key={uid}
                          onClick={() => {
                            toggleFrame(uid)
                            setPreviewFrame(uid)
                          }}
                          style={{
                            cursor: 'pointer',
                            border: selected
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
                            instanceUid={uid}
                            seriesUid={frame.series_uid}
                            style={{
                              width: '100%',
                              height: '100%',
                              objectFit: 'cover',
                              display: 'block',
                            }}
                          />
                          {/* 左下角标 InstanceNumber，便于医生定位切片 */}
                          <div
                            style={{
                              position: 'absolute',
                              bottom: 2,
                              left: 4,
                              color: '#fff',
                              fontSize: 10,
                              textShadow: '0 0 2px #000',
                            }}
                          >
                            #{frame.instance_number}
                          </div>
                          {selected && (
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
                      )
                    })}
                  </div>
                )}
              </Card>
            </Col>
            <Col span={14}>
              <Card
                title={(() => {
                  // 把当前预览的 instance UID 翻成 InstanceNumber，更直观（UID 太长）
                  const cur = frames.find(f => f.instance_uid === previewFrame)
                  return `预览：第 ${cur?.instance_number ?? '-'} 帧`
                })()}
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
                styles={{
                  body: {
                    padding: 12,
                    height: 'calc(100% - 57px)', // 减去 ant-card-head 高度
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 12,
                  },
                }}
              >
                <div style={{ flex: 1, minHeight: 0 }}>
                  {previewFrame ? (
                    <DicomViewer
                      studyId={currentStudy.study_id}
                      instanceUid={previewFrame}
                      seriesUid={frames.find(f => f.instance_uid === previewFrame)?.series_uid}
                      // 把所有帧 UID + series UID 传过去做预加载
                      // 用户点缩略图切换时直接命中内存缓存，瞬时显示
                      preloadInstanceUids={frames.map(f => f.instance_uid)}
                      preloadSeriesUids={frames.map(f => f.series_uid)}
                    />
                  ) : (
                    <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                      点击左侧缩略图预览
                    </div>
                  )}
                </div>
                <Alert
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
