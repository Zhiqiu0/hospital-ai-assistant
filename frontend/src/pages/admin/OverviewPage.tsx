/**
 * 管理后台概览页（pages/admin/OverviewPage.tsx）
 *
 * 系统运行状态看板：
 *   - 关键指标：GET /admin/stats/overview（今日/累计接诊、AI 调用、质控问题）
 *   - 系统健康：GET /health/deep 的真实探活结果（DB / Redis / AI 凭证）
 *
 * 只在挂载时取一次数（无自动刷新定时器）。
 *
 * 2026-08-31 空系统冷启动审计修正：健康横幅此前是**硬编码的绿色**
 * "系统运行正常 — 数据库连接正常，AI 服务正常"，没有任何数据源，且指标
 * 请求的 .catch 把失败整个吞掉——接口全挂、四张卡全 0 时页面照样宣称一切正常。
 * 假信息比没信息更糟，改为按 /health/deep 的 deps 实际渲染，取不到就说取不到。
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
  { label: '质控评分标准', path: '/admin/qc-rules', color: '#d97706', bg: '#fffbeb' },
  { label: '数据统计', path: '/admin/stats', color: 'var(--text-3)', bg: 'var(--surface-2)' },
  { label: '操作日志', path: '/admin/audit-logs', color: '#7c3aed', bg: '#f5f3ff' },
]

/**
 * /admin/stats/overview 概览数字——key 与 STAT_CONFIG.key 对齐，
 * 字段全部 optional：样本为 0 时后端可能不返回某些键。
 */
interface OverviewStats {
  today_encounters?: number
  total_encounters?: number
  total_ai_tasks?: number
  high_risk_issues?: number
  [key: string]: number | undefined
}

/** GET /health/deep 的响应形状（main.py 的 health_check_deep）。
 *  关键依赖任一异常返回 503，body 结构不变。 */
interface HealthDeep {
  status: string
  deps: { db?: string; redis?: string; ai_credential?: string }
}

/** deps → 中文提示（只说探活结果，不臆断"一切正常"） */
function describeHealth(
  health: HealthDeep | null,
  failed: boolean
): { text: string; type: 'success' | 'warning' | 'error' } {
  if (!health) {
    return failed
      ? { text: '无法获取系统健康状态（健康检查接口不可达）', type: 'warning' }
      : { text: '正在检测系统健康状态…', type: 'warning' }
  }
  const d = health.deps || {}
  const bad: string[] = []
  if (d.db && d.db !== 'ok') bad.push('数据库')
  if (d.redis === 'error') bad.push('Redis 缓存/事件总线')
  if (d.ai_credential === 'missing') bad.push('AI 凭证未配置')
  if (bad.length) {
    return { text: `系统异常 — ${bad.join('、')}不可用，请立即检查`, type: 'error' }
  }
  const note = d.redis === 'unconfigured' ? '（Redis 未配置）' : ''
  return { text: `系统运行正常 — 数据库、AI 凭证探活通过${note}`, type: 'success' }
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<OverviewStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [statsFailed, setStatsFailed] = useState(false)
  const [health, setHealth] = useState<HealthDeep | null>(null)
  const [healthFailed, setHealthFailed] = useState(false)

  useEffect(() => {
    api
      .get('/admin/stats/overview')
      .then(data => {
        // 响应拦截器已 unwrap response.data，但 axios 静态类型仍是 AxiosResponse，
        // 走一层 unknown 再断言到实际形状（项目内统一做法）。
        setStats(data as unknown as OverviewStats)
      })
      .catch(() => setStatsFailed(true))
      .finally(() => setLoading(false))

    // 真实健康探活（/health/deep 是匿名可达的监控端点，见 main.py）：
    // 关键依赖任一异常时返回 503，axios 走 catch——此时也要如实展示
    api
      .get('/health/deep')
      .then(d => setHealth(d as unknown as HealthDeep))
      .catch(err => {
        const body = err as { deps?: HealthDeep['deps']; status?: string }
        setHealth(body?.deps ? (body as unknown as HealthDeep) : null)
        setHealthFailed(true)
      })
  }, [])

  const healthMessage = describeHealth(health, healthFailed)

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0, color: 'var(--text-1)' }}>
          系统概览
        </Title>
        <Text type="secondary" style={{ fontSize: 13 }}>
          实时运营数据监控
        </Text>
      </div>

      <Alert
        message={healthMessage.text}
        type={healthMessage.type}
        showIcon
        style={{ marginBottom: 20, borderRadius: 8 }}
      />
      {statsFailed && (
        <Alert
          message="运营指标加载失败，下方数字不可信——请刷新或检查后端状态"
          type="warning"
          showIcon
          style={{ marginBottom: 20, borderRadius: 8 }}
        />
      )}

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
                    <span style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 500 }}>
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
                    color: 'var(--surface)',
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
        title={
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-1)' }}>快速导航</span>
        }
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
