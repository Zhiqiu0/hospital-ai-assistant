import { useState } from 'react'
import { Form, Input, Button, message } from 'antd'
import { UserOutlined, LockOutlined, MedicineBoxOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import api from '@/services/api'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setSystemType } = useAuthStore()
  const [selectedSystem, setSelectedSystem] = useState<'outpatient' | 'inpatient'>('outpatient')

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
      setAuth(res.access_token, res.user)
      setSystemType(selectedSystem)
      const adminRoles = ['super_admin', 'hospital_admin', 'dept_admin']
      if (adminRoles.includes(res.user.role)) {
        navigate('/admin')
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
      {/* Left panel — branding */}
      <div style={{
        flex: 1,
        background: isInpatient
          ? 'linear-gradient(145deg, #064e3b 0%, #065f46 50%, #047857 100%)'
          : 'linear-gradient(145deg, #1e40af 0%, #2563eb 50%, #3b82f6 100%)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '60px 48px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'background 0.4s ease',
      }}>
        <div style={{
          position: 'absolute', top: -80, right: -80,
          width: 320, height: 320, borderRadius: '50%',
          background: 'rgba(255,255,255,0.06)',
        }} />
        <div style={{
          position: 'absolute', bottom: -60, left: -60,
          width: 240, height: 240, borderRadius: '50%',
          background: 'rgba(255,255,255,0.05)',
        }} />

        <div style={{ position: 'relative', textAlign: 'center', color: '#fff' }}>
          <div style={{
            width: 72, height: 72, borderRadius: 20,
            background: 'rgba(255,255,255,0.18)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 24px',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(255,255,255,0.25)',
          }}>
            <MedicineBoxOutlined style={{ fontSize: 34, color: '#fff' }} />
          </div>
          <h1 style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 8 }}>
            MediScribe
          </h1>
          <p style={{ fontSize: 16, opacity: 0.85, marginBottom: 48 }}>
            {isInpatient ? '住院部临床智能助手系统' : '门诊临床接诊智能助手系统'}
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, textAlign: 'left' }}>
            {(isInpatient ? [
              { icon: '📋', title: '住院病历生成', desc: '符合浙江省2021版质控标准' },
              { icon: '🩺', title: '专项评估辅助', desc: 'VTE风险、营养、心理一键评估' },
              { icon: '🛡️', title: 'AI质控检查', desc: '按百分制评分标准实时检测' },
            ] : [
              { icon: '⚡', title: 'AI 病历生成', desc: '一键生成标准化病历草稿' },
              { icon: '💬', title: '智能追问建议', desc: '自动提示关键问诊问题' },
              { icon: '🛡️', title: 'AI 质控检查', desc: '实时检测病历规范问题' },
            ]).map((f) => (
              <div key={f.title} style={{
                display: 'flex', alignItems: 'flex-start', gap: 12,
                background: 'rgba(255,255,255,0.1)',
                borderRadius: 12, padding: '14px 16px',
                border: '1px solid rgba(255,255,255,0.15)',
                backdropFilter: 'blur(4px)',
              }}>
                <span style={{ fontSize: 22, lineHeight: 1 }}>{f.icon}</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{f.title}</div>
                  <div style={{ fontSize: 12, opacity: 0.75, marginTop: 2 }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — login form */}
      <div style={{
        width: 440,
        background: '#fff',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '60px 48px',
        boxShadow: '-4px 0 24px rgba(0,0,0,0.06)',
      }}>
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', marginBottom: 6 }}>
            欢迎回来
          </h2>
          <p style={{ color: '#64748b', fontSize: 14 }}>请选择系统并登录您的账号</p>
        </div>

        {/* 系统选择 */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 10 }}>
            选择登录系统
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {[
              { key: 'outpatient', label: '门诊系统', icon: '🏥', desc: '门诊接诊·病历书写' },
              { key: 'inpatient', label: '住院系统', icon: '🛏️', desc: '住院管理·入院记录' },
            ].map((s) => (
              <div
                key={s.key}
                onClick={() => setSelectedSystem(s.key as any)}
                style={{
                  flex: 1, padding: '14px 12px', borderRadius: 10, cursor: 'pointer',
                  border: `2px solid ${selectedSystem === s.key
                    ? (s.key === 'inpatient' ? '#065f46' : '#2563eb')
                    : '#e2e8f0'}`,
                  background: selectedSystem === s.key
                    ? (s.key === 'inpatient' ? '#f0fdf4' : '#eff6ff')
                    : '#f8fafc',
                  transition: 'all 0.2s',
                  textAlign: 'center',
                }}
              >
                <div style={{ fontSize: 24, marginBottom: 4 }}>{s.icon}</div>
                <div style={{
                  fontSize: 13, fontWeight: 700,
                  color: selectedSystem === s.key
                    ? (s.key === 'inpatient' ? '#065f46' : '#2563eb')
                    : '#374151',
                }}>{s.label}</div>
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{s.desc}</div>
              </div>
            ))}
          </div>
        </div>

        <Form onFinish={onFinish} size="large" layout="vertical">
          <Form.Item
            label={<span style={{ fontWeight: 500, color: '#374151' }}>用户名</span>}
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              prefix={<UserOutlined style={{ color: '#94a3b8' }} />}
              placeholder="请输入用户名"
              style={{ borderRadius: 8, height: 44 }}
            />
          </Form.Item>
          <Form.Item
            label={<span style={{ fontWeight: 500, color: '#374151' }}>密码</span>}
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined style={{ color: '#94a3b8' }} />}
              placeholder="请输入密码"
              style={{ borderRadius: 8, height: 44 }}
            />
          </Form.Item>
          <Form.Item style={{ marginTop: 8 }}>
            <Button
              type="primary"
              htmlType="submit"
              block
              style={{
                height: 44, borderRadius: 8, fontWeight: 600, fontSize: 15,
                background: isInpatient
                  ? 'linear-gradient(135deg, #065f46, #059669)'
                  : 'linear-gradient(135deg, #2563eb, #3b82f6)',
                border: 'none',
                boxShadow: isInpatient
                  ? '0 4px 14px rgba(6,95,70,0.35)'
                  : '0 4px 14px rgba(37,99,235,0.35)',
              }}
            >
              登录{isInpatient ? '住院系统' : '门诊系统'}
            </Button>
          </Form.Item>
        </Form>

        <p style={{ textAlign: 'center', color: '#94a3b8', fontSize: 12, marginTop: 24 }}>
          © 2025 MediScribe · 临床智能辅助系统
        </p>
      </div>
    </div>
  )
}
