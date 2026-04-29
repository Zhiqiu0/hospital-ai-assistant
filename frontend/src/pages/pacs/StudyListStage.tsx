/**
 * 影像列表阶段（pages/pacs/StudyListStage.tsx）
 *
 * 内容：
 *   - 上传影像卡片（患者选择 + Upload 按钮 + 进度条）
 *   - 检查列表卡片（每条研究一行，按状态显示「开始分析/审核报告/已发布」）
 *
 * 已发布的研究禁删（医疗审计合规），其他状态有删除按钮。
 */
import {
  Card,
  Row,
  Col,
  Select,
  Upload,
  Button,
  Progress,
  Space,
  Tag,
  Typography,
  Spin,
  Popconfirm,
} from 'antd'
import { UploadOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons'
import type { Study } from './types'

const { Text } = Typography

interface StudyListStageProps {
  patients: any[]
  selectedPatient: string
  setSelectedPatient: (id: string) => void
  uploading: boolean
  uploadProgress: number
  handleUpload: (file: File) => boolean | Promise<boolean>
  loadingStudies: boolean
  studies: Study[]
  loadStudies: () => void
  openStudy: (id: string, autoAll?: boolean) => void
  deleteStudy: (id: string) => void
  statusTag: (s: string) => React.ReactNode
}

export default function StudyListStage({
  patients,
  selectedPatient,
  setSelectedPatient,
  uploading,
  uploadProgress,
  handleUpload,
  loadingStudies,
  studies,
  loadStudies,
  openStudy,
  deleteStudy,
  statusTag,
}: StudyListStageProps) {
  return (
    <>
      {/* 上传影像 */}
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
          支持 ZIP / RAR / 7Z / TAR / TAR.GZ / TBZ / ISO 等常见压缩格式，系统自动解压并 STOW 到
          Orthanc
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
                      {s.total_frames} 张切片 · {new Date(s.created_at).toLocaleString('zh-CN')}
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
  )
}
