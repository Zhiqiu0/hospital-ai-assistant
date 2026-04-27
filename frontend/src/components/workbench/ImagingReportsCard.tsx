/**
 * 既往影像报告卡片（components/workbench/ImagingReportsCard.tsx）
 *
 * R1 sprint F-1：在接诊面板嵌入该患者的"已发布"影像报告列表，
 * 临床医生在写主诉前就能直接看到 CT/MR/X 光等检查结论，避免切换页面找资料。
 *
 * 数据来源：GET /api/v1/pacs/patient/{patient_id}/reports
 *   - 后端只返回 status=published 的检查 + 对应已发布报告
 *   - 后端已做权限校验：普通医生只能看自己有 encounter 的患者
 *
 * 设计：
 *   - 默认折叠（避免长报告挤占问诊面板空间），点击展开看完整文本
 *   - 报告时间 + modality 标签 + 部位 一目了然
 *   - 0 条时不渲染（不浪费视觉面积）
 */
import { useEffect, useState } from 'react'
import { Card, Tag, Typography, Spin, Collapse, Empty } from 'antd'
import { ScanOutlined } from '@ant-design/icons'
import api from '@/services/api'

const { Text, Paragraph } = Typography

interface ImagingReport {
  study_id: string
  modality: string | null
  body_part: string | null
  series_description: string | null
  total_frames: number
  created_at: string
  final_report: string | null
  published_at: string | null
}

interface Props {
  /** 当前患者 ID；为空时不发请求 */
  patientId: string | null | undefined
}

export default function ImagingReportsCard({ patientId }: Props) {
  const [reports, setReports] = useState<ImagingReport[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!patientId) {
      setReports([])
      return
    }
    setLoading(true)
    api
      .get(`/pacs/patient/${patientId}/reports`)
      .then((d: any) => setReports(Array.isArray(d) ? d : []))
      .catch(() => setReports([]))
      .finally(() => setLoading(false))
  }, [patientId])

  // 没患者上下文 / 无影像报告 → 不渲染（避免空卡片占面积）
  if (!patientId) return null
  if (!loading && reports.length === 0) return null

  return (
    <Card
      size="small"
      style={{ marginBottom: 10, borderRadius: 8 }}
      bodyStyle={{ padding: 8 }}
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <ScanOutlined style={{ color: '#0891B2' }} />
          既往影像报告
          {reports.length > 0 && <Tag color="cyan" style={{ marginLeft: 4 }}>{reports.length}</Tag>}
        </span>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 12 }}>
          <Spin size="small" />
        </div>
      ) : reports.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无影像" />
      ) : (
        <Collapse
          size="small"
          ghost
          items={reports.map(r => ({
            key: r.study_id,
            label: (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Tag color="blue" style={{ marginRight: 0 }}>{r.modality || '未知'}</Tag>
                <Text strong style={{ fontSize: 12 }}>
                  {r.body_part || r.series_description || '未标注部位'}
                </Text>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {r.published_at
                    ? new Date(r.published_at).toLocaleString('zh-CN', {
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                      })
                    : new Date(r.created_at).toLocaleDateString('zh-CN')}
                </Text>
              </div>
            ),
            children: r.final_report ? (
              <Paragraph
                style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: 12,
                  fontFamily: 'monospace',
                  background: 'var(--surface-2)',
                  padding: 8,
                  borderRadius: 6,
                  marginBottom: 0,
                }}
              >
                {r.final_report}
              </Paragraph>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                报告内容为空
              </Text>
            ),
          }))}
        />
      )}
    </Card>
  )
}
