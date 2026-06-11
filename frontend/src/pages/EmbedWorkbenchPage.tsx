/**
 * HIS 嵌入模式入口（pages/EmbedWorkbenchPage.tsx）
 *
 * 访问路径：/embed?token=<JWT>&encounter_id=<UUID>
 *
 * 职责：URL 参数 → 设置 token / 拉嵌入会话 / 写 embedStore → 跳 /workbench
 *
 * 为什么不直接渲染工作台：
 *   把"嵌入模式 setup"和"工作台渲染"解耦，WorkbenchPage 零改动风险。
 *   现有 SaaS 用户访问 /workbench 行为完全不变；只有嵌入入口写了
 *   embedStore.isEmbed=true 后，WorkbenchPage 内部按 isEmbed 决定是否
 *   显示 AutoFillButton 等嵌入专属 UI。
 */

import { useEffect, useState } from 'react'
import { useSearchParams, Navigate } from 'react-router-dom'
import { Spin, Result } from 'antd'
import { useAuthStore } from '@/store/authStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useEmbedStore } from '@/store/embedStore'
import type { EmbedSession } from '@/store/embedStore'
import { desktopAgent } from '@/services/desktopAgent'
import api from '@/services/api'

/**
 * 解析 JWT 的 exp 声明（秒级 epoch）→ 毫秒级 epoch；解析失败返回 null。
 * 仅做 base64 解码读字段，不验签（验签是后端的事，前端只用于提前提示过期）。
 */
function parseJwtExpiresAt(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

export default function EmbedWorkbenchPage() {
  const [params] = useSearchParams()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  const token = params.get('token')
  const encounterId = params.get('encounter_id')
  // api 层捕获到嵌入态 401 时跳回 /embed?expired=1，在这里给医生明确提示
  const expiredFlag = params.get('expired')

  useEffect(() => {
    if (expiredFlag) {
      setError('嵌入会话已过期（有效期 4 小时），请回到 HIS 重新触发 AI 助手')
      setLoading(false)
      return
    }
    if (!token || !encounterId) {
      setError('缺少 token 或 encounter_id 参数')
      setLoading(false)
      return
    }

    // token 已过期的直接拦截（医生从浏览器历史/书签重新打开旧链接的场景），
    // 不发请求就给出明确指引，避免落到通用 401 报错
    const tokenExpiresAt = parseJwtExpiresAt(token)
    if (tokenExpiresAt !== null && tokenExpiresAt <= Date.now()) {
      setError('嵌入会话已过期（有效期 4 小时），请回到 HIS 重新触发 AI 助手')
      setLoading(false)
      return
    }

    // 1. 用 URL token 绑定到 authStore（跳过登录页）
    //    Agent 签发 token 时 sub=医生ID，相当于代理登录
    useAuthStore.setState({ token })
    desktopAgent.setToken(token)

    // 2. 拉嵌入会话上下文（项目里 axios 拦截器已把 response.data 当返回值，所以 cast 即可）
    ;(api.get(`/embed/session/${encounterId}`) as unknown as Promise<EmbedSession>)
      .then(session => {
        // 后端 /embed/start 必然返回带 patient_id 的会话（找已有或新建），
        // null 只在 TypeScript schema 容错语义下出现，运行时拿到 null 视为异常
        if (!session.patient_id) {
          setError('嵌入会话缺少患者 ID，请重新从 HIS 触发 AI 助手')
          return
        }
        // 把 token 过期时刻一并入库，供 API 层 401 时判断"是过期还是别的问题"
        useEmbedStore.getState().setEmbed(session, parseJwtExpiresAt(token))
        // 用 setActive 而不是 setState：encounterId 变化时它会自动 reset 4 个子 store
        // (inquiry / record / qc / aiSuggestion)，避免上次 SaaS 测试残留的 inquiry
        // 数据污染嵌入会话（AutoFillButton collectFields 会误读到旧字段）。
        useActiveEncounterStore.getState().setActive({
          patientId: session.patient_id,
          encounterId: session.encounter_id,
          visitType: session.visit_type as 'outpatient' | 'emergency' | 'inpatient',
          isFirstVisit: session.is_first_visit,
          isPatientReused: false,
          previousRecordContent: null,
        })
        setReady(true)
      })
      .catch((e: { response?: { status?: number } }) => {
        if (e.response?.status === 503) {
          setError('HIS 嵌入模式当前已关闭，请联系管理员开启')
        } else if (e.response?.status === 404) {
          setError('嵌入会话不存在或已过期')
        } else if (e.response?.status === 401) {
          setError('Token 无效或已过期，请重新从 HIS 触发 AI 助手')
        } else {
          setError('加载嵌入会话失败')
        }
      })
      .finally(() => setLoading(false))
  }, [token, encounterId, expiredFlag])

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
        }}
      >
        <Spin size="large" tip="正在打开嵌入工作台...">
          <div style={{ minHeight: 60, minWidth: 60 }} />
        </Spin>
      </div>
    )
  }

  if (error) {
    return (
      <Result
        status="error"
        title="无法加载嵌入工作台"
        subTitle={error}
        extra={<a href="https://mediscribe.cn">回 MediScribe 主页</a>}
      />
    )
  }

  if (ready) {
    // 跳到工作台，replace=true 让浏览器后退不回到 /embed（避免 token 残留 URL）
    return <Navigate to="/workbench" replace />
  }

  return null
}
