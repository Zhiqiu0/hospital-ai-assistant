/**
 * 选关键帧阶段（pages/pacs/SelectFramesStage.tsx）
 *
 * 内容：
 *   - 左侧 4 列网格缩略图（点击切换 / 多选送 AI）
 *   - 右侧 DicomViewer 大图预览
 *   - 顶栏支持自动抽帧 / 全选 / 清空 / 返回
 *   - 底部 Alert 显示选帧统计
 */
import { Card, Row, Col, Space, Button, Tag, Alert, Spin } from 'antd'
import { CheckCircleOutlined, SendOutlined } from '@ant-design/icons'
import DicomViewer from '@/components/workbench/DicomViewer'
import AuthedThumbnail from './AuthedThumbnail'
import type { Frame } from './types'

interface SelectFramesStageProps {
  currentStudy: any
  frames: Frame[]
  selectedFrames: Set<string>
  previewFrame: string
  setPreviewFrame: (uid: string) => void
  loadingFrames: boolean
  toggleFrame: (uid: string) => void
  selectAll: () => void
  selectSuggested: () => void
  clearSelection: () => void
  setStage: (s: 'list') => void
  runAnalysis: () => void
}

export default function SelectFramesStage({
  currentStudy,
  frames,
  selectedFrames,
  previewFrame,
  setPreviewFrame,
  loadingFrames,
  toggleFrame,
  selectAll,
  selectSuggested,
  clearSelection,
  setStage,
  runAnalysis,
}: SelectFramesStageProps) {
  // 把当前预览的 instance UID 翻成 InstanceNumber，更直观（UID 太长）
  const cur = frames.find(f => f.instance_uid === previewFrame)
  const previewTitle = `预览：第 ${cur?.instance_number ?? '-'} 帧`

  return (
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
                      border: selected ? '2px solid #1890ff' : '2px solid transparent',
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
          title={previewTitle}
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
              height: 'calc(100% - 57px)',
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
  )
}
