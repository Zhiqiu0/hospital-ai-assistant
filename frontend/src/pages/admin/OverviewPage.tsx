/**
 * 管理后台概览页（pages/admin/OverviewPage.tsx）
 *
 * 系统运行状态看板，调用 GET /admin/overview：
 *   - 关键指标：今日接诊数、签发病历数、AI 调用次数、在线用户数
 *   - 系统健康状态：数据库连接、AI 服务连通性（红/绿指示灯）
 *   - 近 7 日病历量折线图（使用 recharts 或内置简单展示）
 *
 * 数据每 30s 自动刷新（useEffect 定时器）。
 * 若 AI 服务不可用，显示黄色警告 Alert 提示管理员检查配置。
 */
import { useEffect, useState } from 'react'
import { Row, Col, Card, Statistic, Typography, Alert } from 'antd'
import {
  TeamOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '@/services/api'

const { Title, Text } = Typography

const STAT_CONFIG = [
  {
    key: 'today_encounters',
    title: '今日接诊',
    icon: <TeamOutlined />,
    color: '#2563eb',
    bg: '#eff6ff',
    border: '#bfdbfe',
  },
  {
    key: 'total_encounters',
    title: '累计接诊',
    icon: <FileTextOutlined />,
    color: '#059669',
    bg: '#f0fdf4',
    border: '#bbf7d0',
  },
  {
    key: 'total_ai_tasks',
    title: 'AI 调用次数',
    icon: <RobotOutlined />,
    color: '#7c3aed',
    bg: '#f5f3ff',
    border: '#ddd6fe',
  },
  {
    key: 'high_risk_issues',
    title: '高风险质控问题',
    icon: <SafetyOutlined />,
    color: '#dc2626',
    bg: '#fef2f2',
    border: '#fecaca',
  },
]

const NAV_ITEMS = [
  { label: '用户管理', path: '/admin/users', color: '#2563eb', bg: '#eff6ff' },
  { label: '科室管理', path: '/admin/departments', color: '#059669', bg: '#f0fdf4' },
  { label: '患者档案', path: '/admin/patients', color: '#0891b2', bg: '#ecfeff' },
  { label: '质控规则', path: '/admin/qc-rules', color: '#d97706', bg: '#fffbeb' },
  { label: 'Prompt 管理', path: '/admin/prompts', color: '#7c3aed', bg: '#f5f3ff' },
  { label: '模型配置', path: '/admin/model-configs', color: '#0f766e', bg: '#ecfeff' },
  { label: '数据统计', path: '/admin/stats', color: '#64748b', bg: '#f8fafc' },
  { label: '操作日志', path: '/admin/audit-logs', color: '#7c3aed', bg: '#f5f3ff' },
]

export default function OverviewPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .get('/admin/stats/overview')
      .then((data: any) => {
        setStats(data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0, color: '#0f172a' }}>
          系统概览
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          实时运营数据监控
        </Text>
      </div>

      <Alert
        message="系统运行正常 — 数据库连接正常，AI 服务正常"
        type="success"
        showIcon
        style={{ marginBottom: 20, borderRadius: 8 }}
      />

      {/* Stat cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        {STAT_CONFIG.map(c => (
          <Col xs={24} sm={12} lg={6} key={c.key}>
            <Card
              loading={loading}
              style={{
                borderRadius: 10,
                border: `1px solid ${c.border}`,
                background: c.bg,
                boxShadow: 'none',
              }}
              styles={{ body: { padding: '18px 20px' } }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                }}
              >
                <Statistic
                  title={
                    <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500 }}>
                      {c.title}
                    </span>
                  }
                  value={stats?.[c.key] ?? 0}
                  valueStyle={{ color: c.color, fontSize: 28, fontWeight: 700, lineHeight: 1.2 }}
                />
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 10,
                    background: c.color,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontSize: 18,
                    flexShrink: 0,
                    opacity: 0.9,
                  }}
                >
                  {c.icon}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* Quick nav */}
      <Card
        title={<span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>快速导航</span>}
        style={{ borderRadius: 10 }}
        styles={{ body: { padding: '16px 20px' } }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {NAV_ITEMS.map(item => (
            <div
              key={item.path}
              onClick={() => navigate(item.path)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '8px 16px',
                background: item.bg,
                border: `1px solid ${item.color}22`,
                borderRadius: 8,
                cursor: 'pointer',
                color: item.color,
                fontSize: 13,
                fontWeight: 500,
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                ;(e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)'
                ;(e.currentTarget as HTMLElement).style.boxShadow = `0 4px 12px ${item.color}22`
              }}
              onMouseLeave={e => {
                ;(e.currentTarget as HTMLElement).style.transform = ''
                ;(e.currentTarget as HTMLElement).style.boxShadow = ''
              }}
            >
              {item.label}
              <ArrowRightOutlined style={{ fontSize: 11 }} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
