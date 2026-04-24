/**
 * 登录页面（pages/LoginPage.tsx）
 *
 * 系统统一登录入口：
 *   - POST /auth/login 成功后将 access_token 存入 authStore
 *   - 根据 user.role 分发：admin → /admin  radiologist → /pacs
 *     其他按 systemType 去门诊或住院工作台
 *   - 登录接口有速率限制（5次/分钟/账号），超限返回 429
 *
 * 视觉：全部颜色从 theme/tokens.ts 读取，按 selectedSystem 切换门诊青 / 住院深青主题。
 * 图标：使用 antd SVG 图标替代 emoji（无障碍 + 专业度）。
 */
import { useState } from 'react'
import { Form, Input, Button, message } from 'antd'
import {
  UserOutlined,
  LockOutlined,
  MedicineBoxOutlined,
  HomeOutlined,
  AppstoreOutlined,
  ThunderboltOutlined,
  MessageOutlined,
  SafetyOutlined,
  FileTextOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useWorkbenchStore } from '@/store/workbenchStore'
import api from '@/services/api'
import { scenes, neutral, radius, spacing, typography } from '@/theme/tokens'

type SystemType = 'outpatient' | 'inpatient'

const FEATURES: Record<SystemType, { icon: React.ReactNode; title: string; desc: string }[]> = {
  outpatient: [
    { icon: <ThunderboltOutlined />, title: 'AI 病历生成', desc: '一键生成标准化病历草稿' },
    { icon: <MessageOutlined />, title: '智能追问建议', desc: '自动提示关键问诊问题' },
    { icon: <SafetyOutlined />, title: 'AI 质控检查', desc: '实时检测病历规范问题' },
  ],
  inpatient: [
    { icon: <FileTextOutlined />, title: '住院病历生成', desc: '符合浙江省2021版质控标准' },
    { icon: <ExperimentOutlined />, title: '专项评估辅助', desc: 'VTE风险、营养、心理一键评估' },
    { icon: <SafetyOutlined />, title: 'AI 质控检查', desc: '按百分制评分标准实时检测' },
  ],
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setSystemType } = useAuthStore()
  const resetWorkbench = useWorkbenchStore(s => s.reset)
  const [selectedSystem, setSelectedSystem] = useState<SystemType>('outpatient')

  const theme = selectedSystem === 'inpatient' ? scenes.inpatient : scenes.outpatient

  const resolveLoginErrorMessage = async (username: string, error: any) => {
    const detail = error?.detail
    if (detail && detail !== '用户名或密码错误') return detail
    try {
      const res: any = await api.get('/auth/check-username', { params: { username } })
      return res.exists ? '密码不正确' : '账号不存在'
    } catch {
      return detail || '登录失败，请稍后重试'
    }
  }

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const res: any = await api.post('/auth/login', values)
      resetWorkbench()
      setAuth(res.access_token, res.user)
      setSystemType(selectedSystem)
      const adminRoles = ['super_admin', 'hospital_admin', 'dept_admin']
      if (adminRoles.includes(res.user.role)) {
        navigate('/admin')
      } else if (res.user.role === 'radiologist') {
        navigate('/pacs')
      } else {
        navigate(selectedSystem === 'inpatient' ? '/inpatient' : '/workbench')
      }
    } catch (error: any) {
      message.error(await resolveLoginErrorMessage(values.username, error))
    }
  }

  const isInpatient = selectedSystem === 'inpatient'

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* 左侧品牌区 */}
      <div
        style={{
          flex: 1,
          background: `linear-gradient(145deg, ${theme.primaryDark} 0%, ${theme.primary} 50%, ${theme.accentLight} 100%)`,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '60px 48px',
          position: 'relative',
          overflow: 'hidden',
          transition: 'background 0.4s ease',
        }}
      >
        {/* 装饰圆 */}
        <div
          style={{
            position: 'absolute',
            top: -80,
            right: -80,
            width: 320,
            height: 320,
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.06)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            bottom: -60,
            left: -60,
            width: 240,
            height: 240,
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.05)',
          }}
        />

        <div style={{ position: 'relative', textAlign: 'center', color: 'var(--surface)' }}>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: 20,
              background: 'rgba(255,255,255,0.18)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 24px',
              backdropFilter: 'blur(10px)',
              border: '1px solid rgba(255,255,255,0.25)',
            }}
          >
            <MedicineBoxOutlined style={{ fontSize: 34, color: 'var(--surface)' }} />
          </div>
          <h1
            style={{
              fontSize: 32,
              fontWeight: 800,
              letterSpacing: '-0.5px',
              marginBottom: 8,
              fontFamily: typography.fontHeading,
            }}
          >
            MediScribe
          </h1>
          <p style={{ fontSize: 16, opacity: 0.85, marginBottom: 48 }}>
            {isInpatient ? '住院部临床智能助手系统' : '门诊临床接诊智能助手系统'}
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, textAlign: 'left' }}>
            {FEATURES[selectedSystem].map(f => (
              <div
                key={f.title}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  background: 'rgba(255,255,255,0.1)',
                  borderRadius: radius.lg,
                  padding: '14px 16px',
                  border: '1px solid rgba(255,255,255,0.15)',
                  backdropFilter: 'blur(4px)',
                }}
              >
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: radius.md,
                    background: 'rgba(255,255,255,0.18)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 18,
                    color: 'var(--surface)',
                    flexShrink: 0,
                  }}
                >
                  {f.icon}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{f.title}</div>
                  <div style={{ fontSize: 12, opacity: 0.75, marginTop: 2 }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 右侧登录表单 */}
      <div
        style={{
          width: 440,
          background: neutral.surface,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '60px 48px',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.06)',
        }}
      >
        <div style={{ marginBottom: 32 }}>
          <h2
            style={{
              fontSize: 24,
              fontWeight: 700,
              color: neutral.text1,
              marginBottom: 6,
              fontFamily: typography.fontHeading,
            }}
          >
            欢迎回来
          </h2>
          <p style={{ color: neutral.text3, fontSize: 14 }}>请选择系统并登录您的账号</p>
        </div>

        {/* 系统选择卡片 */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: neutral.text2, marginBottom: 10 }}>
            选择登录系统
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {(
              [
                {
                  key: 'outpatient',
                  label: '门诊系统',
                  icon: <AppstoreOutlined />,
                  desc: '门诊接诊 · 病历书写',
                },
                {
                  key: 'inpatient',
                  label: '住院系统',
                  icon: <HomeOutlined />,
                  desc: '住院管理 · 入院记录',
                },
              ] as const
            ).map(s => {
              const active = selectedSystem === s.key
              const sceneTheme = s.key === 'inpatient' ? scenes.inpatient : scenes.outpatient
              return (
                <button
                  type="button"
                  key={s.key}
                  onClick={() => setSelectedSystem(s.key)}
                  aria-pressed={active}
                  style={{
                    flex: 1,
                    padding: '14px 12px',
                    borderRadius: radius.lg,
                    cursor: 'pointer',
                    border: `2px solid ${active ? sceneTheme.primary : neutral.border}`,
                    background: active ? sceneTheme.primaryLight : neutral.surface2,
                    transition: 'all 0.2s',
                    textAlign: 'center',
                  }}
                >
                  <div
                    style={{
                      fontSize: 22,
                      marginBottom: 4,
                      color: active ? sceneTheme.primary : neutral.text3,
                    }}
                  >
                    {s.icon}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: active ? sceneTheme.primary : neutral.text2,
                    }}
                  >
                    {s.label}
                  </div>
                  <div style={{ fontSize: 11, color: neutral.text4, marginTop: 2 }}>{s.desc}</div>
                </button>
              )
            })}
          </div>
        </div>

        <Form onFinish={onFinish} size="large" layout="vertical">
          <Form.Item
            label={<span style={{ fontWeight: 500, color: neutral.text2 }}>用户名</span>}
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              prefix={<UserOutlined style={{ color: neutral.text4 }} />}
              placeholder="请输入用户名"
              style={{ borderRadius: radius.md, height: 44 }}
              autoComplete="username"
            />
          </Form.Item>
          <Form.Item
            label={<span style={{ fontWeight: 500, color: neutral.text2 }}>密码</span>}
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: neutral.text4 }} />}
              placeholder="请输入密码"
              style={{ borderRadius: radius.md, height: 44 }}
              autoComplete="current-password"
            />
          </Form.Item>
          <Form.Item style={{ marginTop: spacing.sm }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              style={{
                height: 44,
                borderRadius: radius.md,
                fontWeight: 600,
                fontSize: 15,
                background: `linear-gradient(135deg, ${theme.primary}, ${theme.accentLight})`,
                border: 'none',
                boxShadow: `0 4px 14px rgba(${theme.shadowRgba},0.35)`,
              }}
            >
              登录{isInpatient ? '住院系统' : '门诊系统'}
            </Button>
          </Form.Item>
        </Form>

        <p style={{ textAlign: 'center', color: neutral.text4, fontSize: 12, marginTop: 24 }}>
          © 2025 MediScribe · 临床智能辅助系统
        </p>
      </div>
    </div>
  )
}
