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
 *
 * 2026-06-11 Round 5.5 拆分：左侧品牌宣传面板（BrandPanel）与系统选择卡
 * （SystemSelector）移至 ./login/ 子目录，本文件保留登录表单与错误处理逻辑。
 */
import { useState } from 'react'
import { Form, Input, Button } from 'antd'
import { message } from '@/services/messageBridge'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as Sentry from '@sentry/react'
import { useAuthStore, clearPatientScopedData } from '@/store/authStore'
import { resetAllWorkbench } from '@/store/activeEncounterStore'
import api from '@/services/api'
import { scenes, neutral, radius, spacing, typography } from '@/theme/tokens'
import BrandPanel from './login/BrandPanel'
import SystemSelector, { type SystemType } from './login/SystemSelector'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setSystemType } = useAuthStore()
  const resetWorkbench = resetAllWorkbench
  const [selectedSystem, setSelectedSystem] = useState<SystemType>('outpatient')

  const theme = selectedSystem === 'inpatient' ? scenes.inpatient : scenes.outpatient

  // axios 拦截器把 error.response?.data reject 出来；既可能含 detail（业务错误），
  // 也可能仍是 AxiosError（网络层错误）。本地视图取并集，运行期按字段实际存在与否取值。
  type LoginErrorShape = {
    detail?: string
    code?: string
    message?: string
    response?: { status?: number }
  }
  const resolveLoginErrorMessage = async (username: string, error: unknown) => {
    const err = (error || {}) as LoginErrorShape
    // 诊断 breadcrumb：把 axios error 形态记下来，方便下次同类 bug 排查
    // 不记 username 内容（PII），仅记 error 形态
    const errorShape = {
      hasResponse: !!err.response,
      httpStatus: err.response?.status,
      errorCode: err.code,
      errorMessage: err.message?.slice(0, 200),
      hasDetail: !!err.detail,
    }

    const detail = err.detail
    let finalToast: string
    let checkUsernameResult: 'skipped' | 'success' | 'failed' = 'skipped'

    if (detail && detail !== '用户名或密码错误') {
      finalToast = detail
    } else {
      try {
        const res = (await api.get('/auth/check-username', { params: { username } })) as {
          exists?: boolean
        }
        checkUsernameResult = 'success'
        finalToast = res.exists ? '密码不正确' : '账号不存在'
      } catch {
        checkUsernameResult = 'failed'
        finalToast = detail || '登录失败，请稍后重试'
      }
    }

    // 上报到 Sentry：完整记录"用户看到的 toast" + "实际错误形态"，
    // 下次同样的"网络错误弹错 toast"问题，看 Sentry event 一眼就能识别
    Sentry.addBreadcrumb({
      category: 'auth',
      level: 'warning',
      message: 'login failed → toast resolved',
      data: { ...errorShape, checkUsernameResult, finalToast },
    })

    return finalToast
  }

  // /auth/login 响应：JWT + 用户信息（role 驱动跳转目标）
  interface LoginResponse {
    access_token: string
    user: {
      id: string
      username: string
      real_name: string
      role: string
      department_id?: string
      department_name?: string
      must_change_password?: boolean
    }
  }

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const res = (await api.post('/auth/login', values)) as LoginResponse
      // 换人登录才清工作台（2026-08-13 第二轮审计修复）：原先无条件清，
      // 导致「token 到期被踢回登录页 → 同一医生重登」时，他没保存完的问诊
      // 表单/病历草稿被连带清掉，等于凭空丢失一段工作。换成别的医生登录时
      // 仍然必须清（跨医生看到彼此患者数据是隐私事故）。
      const lastUserId = useAuthStore.getState().lastUserId
      if (lastUserId !== res.user.id) {
        resetWorkbench()
        // 换医生登录必须连跨患者 PHI 一起清（2026-08-13 第五轮审计修复）：
        // 这条路径不经过 clearAuth，原先只清工作台 store，患者缓存/语音转写/
        // 档案草稿里还留着上一位医生的患者数据。诊室电脑多人共用是医院常态，
        // 不登出直接换人登录比正常登出更常见。
        clearPatientScopedData()
      }
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
    } catch (error) {
      message.error(await resolveLoginErrorMessage(values.username, error))
    }
  }

  const isInpatient = selectedSystem === 'inpatient'

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* 左侧品牌区（纯展示，见 ./login/BrandPanel.tsx） */}
      <BrandPanel selectedSystem={selectedSystem} />

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

        {/* 系统选择卡片（见 ./login/SystemSelector.tsx） */}
        <SystemSelector value={selectedSystem} onChange={setSelectedSystem} />

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
