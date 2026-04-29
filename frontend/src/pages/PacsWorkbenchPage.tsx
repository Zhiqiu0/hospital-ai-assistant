/**
 * PACS 影像工作台页面（pages/PacsWorkbenchPage.tsx）
 *
 * 4 阶段状态机：list → select_frames → analyzing → report，
 * 各阶段渲染拆到 pages/pacs/ 子目录下独立组件文件，本文件只保留：
 *   - 业务 state 与 handlers（上传 / 取帧 / 分析 / 发布 / 删除）
 *   - 阶段路由（按 stage 选择渲染哪个子组件）
 *   - 顶栏 + Steps 进度指示器
 */
import { useState, useEffect, useCallback } from 'react'
import { Layout, Button, message, Card, Typography, Tag, Steps } from 'antd'
import { ScanOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import StudyListStage from './pacs/StudyListStage'
import SelectFramesStage from './pacs/SelectFramesStage'
import AnalyzingStage from './pacs/AnalyzingStage'
import ReportStage from './pacs/ReportStage'
import type { Frame, Study, Stage } from './pacs/types'

const { Header, Content } = Layout
const { Title, Text } = Typography

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
      new Set(
        frames
          .filter((_, i) => i % step === 0)
          .slice(0, 10)
          .map(f => f.instance_uid)
      )
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
      // G4 合并：PUT /report?publish=true 同时签发；不再走独立 POST /publish 端点
      await api.put(`/pacs/${currentStudy.study_id}/report`, {
        final_report: finalReport,
        publish: true,
      })
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
                {
                  title: '选择关键帧',
                  description: stage === 'select_frames' ? '勾选需要 AI 分析的影像帧' : undefined,
                },
                {
                  title: 'AI 分析',
                  description: stage === 'analyzing' ? '通义千问视觉模型分析中' : undefined,
                },
                {
                  title: '报告审核',
                  description: stage === 'report' ? '核对并发布最终报告' : undefined,
                },
              ]}
            />
          </Card>
        )}

        {stage === 'list' && (
          <StudyListStage
            patients={patients}
            selectedPatient={selectedPatient}
            setSelectedPatient={setSelectedPatient}
            uploading={uploading}
            uploadProgress={uploadProgress}
            handleUpload={handleUpload}
            loadingStudies={loadingStudies}
            studies={studies}
            loadStudies={loadStudies}
            openStudy={openStudy}
            deleteStudy={deleteStudy}
            statusTag={statusTag}
          />
        )}

        {stage === 'select_frames' && currentStudy && (
          <SelectFramesStage
            currentStudy={currentStudy}
            frames={frames}
            selectedFrames={selectedFrames}
            previewFrame={previewFrame}
            setPreviewFrame={setPreviewFrame}
            loadingFrames={loadingFrames}
            toggleFrame={toggleFrame}
            selectAll={selectAll}
            selectSuggested={selectSuggested}
            clearSelection={clearSelection}
            setStage={setStage}
            runAnalysis={runAnalysis}
          />
        )}

        {stage === 'analyzing' && <AnalyzingStage selectedFramesCount={selectedFrames.size} />}

        {stage === 'report' && (
          <ReportStage
            aiResult={aiResult}
            finalReport={finalReport}
            setFinalReport={setFinalReport}
            publishing={publishing}
            publishReport={publishReport}
            setStage={setStage}
          />
        )}
      </Content>
    </Layout>
  )
}
