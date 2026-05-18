/**
 * 评分标准查看页（pages/admin/QCRulesPage.tsx）
 *
 * L3 治本路线（2026-05-18）：
 *   浙江省卫健委评分标准是国家法定标准，已迁移到后端 qc_engine.rubrics 代码常量。
 *   本页从原来的"质控规则 CRUD"改成"法定评分标准只读查看"。
 *
 * 接口：
 *   GET /admin/rubrics                 列出所有已注册的法定标准
 *   GET /admin/rubrics/{rubric_key}    取单份标准完整字段（含 11 大项扣分细则）
 *
 * UI 按 PDF 四列表格设计：项目 / 检查内容 / 评分说明 / 扣分及理由
 */
import { useEffect, useState } from 'react'
import { Table, Tag, Typography, Spin, Empty, Alert, Tabs, Space } from 'antd'
import { SafetyCertificateOutlined, FileTextOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'

const { Title, Text, Paragraph } = Typography

// 评分大项的一条扣分细则（对应 PDF 评分说明列的一行）
interface DeductionRuleView {
  code: string
  description: string
  deduct_points: number
}

// 单项否决规则（仅住院评分用，门诊为空）
interface VetoRuleView {
  code: string
  description: string
  deduct_points: number
}

// 评分大项（对应 PDF 一行：项目 + 分值 + 检查要求 + 扣分细则列表）
interface RubricItemView {
  name: string
  max_points: number
  description: string
  deduction_rules: DeductionRuleView[]
  veto_rules: VetoRuleView[]
}

// 等级阈值（门诊：合格/不合格；住院：甲乙丙）
interface GradeThresholdView {
  min_score: number
  label: string
}

// 完整评分标准
interface RubricView {
  name: string
  version: string
  record_scope: 'single' | 'encounter'
  total_points: number
  grade_thresholds: GradeThresholdView[]
  items: RubricItemView[]
}

// 列表项（GET /admin/rubrics 返回）
interface RubricSummary {
  key: string
  name: string
  version: string
  record_scope: 'single' | 'encounter'
  total_points: number
}

export default function QCRulesPage() {
  const [summaries, setSummaries] = useState<RubricSummary[]>([])
  const [activeKey, setActiveKey] = useState<string>('')
  const [rubric, setRubric] = useState<RubricView | null>(null)
  const [listLoading, setListLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)

  // 拉评分标准列表
  useEffect(() => {
    setListLoading(true)
    api
      .get<{ items: RubricSummary[] }>('/admin/rubrics')
      .then(res => {
        setSummaries(res.items || [])
        if (res.items && res.items.length > 0) {
          setActiveKey(res.items[0].key)
        }
      })
      .catch(() => message.error('加载评分标准列表失败'))
      .finally(() => setListLoading(false))
  }, [])

  // 切 tab 时拉单份标准详情
  useEffect(() => {
    if (!activeKey) return
    setDetailLoading(true)
    api
      .get<RubricView>(`/admin/rubrics/${activeKey}`)
      .then(res => setRubric(res))
      .catch(() => message.error('加载评分标准详情失败'))
      .finally(() => setDetailLoading(false))
  }, [activeKey])

  // PDF 四列表格：项目 / 检查内容 / 评分说明（扣分细则） / 扣分及理由（运行时填）
  const renderItemTable = (rubric: RubricView) => {
    const dataSource = rubric.items.map((item, idx) => ({
      key: idx,
      item,
    }))
    return (
      <Table
        size="middle"
        pagination={false}
        bordered
        dataSource={dataSource}
        columns={[
          {
            title: '项目',
            dataIndex: ['item', 'name'],
            width: 160,
            render: (_: unknown, row: { item: RubricItemView }) => (
              <Space direction="vertical" size={2}>
                <Text strong>{row.item.name}</Text>
                <Tag color="blue">{row.item.max_points} 分</Tag>
              </Space>
            ),
          },
          {
            title: '检查要求',
            dataIndex: ['item', 'description'],
            width: 320,
            render: (_: unknown, row: { item: RubricItemView }) => (
              <Text style={{ whiteSpace: 'pre-wrap' }}>{row.item.description}</Text>
            ),
          },
          {
            title: '评分说明（扣分细则）',
            render: (_: unknown, row: { item: RubricItemView }) => (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                {row.item.veto_rules.map(v => (
                  <div key={v.code}>
                    <Tag color="red">单项否决</Tag>
                    <Text>{v.description}</Text>
                    <Text type="danger" style={{ marginLeft: 8 }}>
                      扣 10 分（不累积）
                    </Text>
                  </div>
                ))}
                {row.item.deduction_rules.map(r => (
                  <div key={r.code}>
                    <Text>{r.description}</Text>
                    <Text type="warning" style={{ marginLeft: 8 }}>
                      扣 {r.deduct_points} 分
                    </Text>
                  </div>
                ))}
                {row.item.deduction_rules.length === 0 && row.item.veto_rules.length === 0 && (
                  <Text type="secondary">（暂无明细规则——数据未接入或该项无扣分细则）</Text>
                )}
              </Space>
            ),
          },
        ]}
      />
    )
  }

  const tabs = summaries.map(s => ({
    key: s.key,
    label: (
      <span>
        <FileTextOutlined /> {s.name}（{s.version}）
      </span>
    ),
    children: detailLoading ? (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin />
      </div>
    ) : rubric ? (
      <div>
        <Space direction="vertical" size="middle" style={{ width: '100%', marginBottom: 16 }}>
          <Alert
            type="info"
            showIcon
            icon={<SafetyCertificateOutlined />}
            message="法定评分标准 · 只读"
            description={
              <Space direction="vertical" size={4}>
                <Text>
                  本评分标准已迁移到代码常量（{rubric.name} {rubric.version}），按浙江省卫健委
                  PDF 1:1 映射，**不再支持在线编辑**——修改须走代码 PR review + 法律合规复核。
                </Text>
                <Text type="secondary">
                  总分：{rubric.total_points} 分 ·{' '}
                  评分对象：{rubric.record_scope === 'single' ? '单份病历' : '整个接诊（多文档综合）'}
                </Text>
                <Text type="secondary">
                  等级判定：
                  {rubric.grade_thresholds
                    .map((t, idx, arr) => {
                      // 最高等级显示 ≥ 自身阈值；其他等级显示 < 上一级阈值
                      // 否则会出现"不合格（≥0 分）"这种怪文案
                      if (idx === 0) return `${t.label}（≥${t.min_score} 分）`
                      const upper = arr[idx - 1].min_score
                      return `${t.label}（<${upper} 分）`
                    })
                    .join(' / ')}
                </Text>
              </Space>
            }
          />
        </Space>
        {renderItemTable(rubric)}
      </div>
    ) : (
      <Empty description="未加载到评分标准详情" />
    ),
  }))

  return (
    <div>
      <Space direction="vertical" size="small" style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          病历质控评分标准
        </Title>
        <Paragraph type="secondary" style={{ margin: 0 }}>
          浙江省卫健委发布的法定评分标准，由系统在病历质控时自动应用。
        </Paragraph>
      </Space>

      {listLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : summaries.length === 0 ? (
        <Empty description="暂无注册的评分标准" />
      ) : (
        <Tabs
          activeKey={activeKey}
          onChange={setActiveKey}
          items={tabs}
          destroyOnHidden
        />
      )}
    </div>
  )
}
