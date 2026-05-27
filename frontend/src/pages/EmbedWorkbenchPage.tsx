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

export default function EmbedWorkbenchPage() {
  const [params] = useSearchParams()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  const token = params.get('token')
  const encounterId = params.get('encounter_id')

  useEffect(() => {
    if (!token || !encounterId) {
      setError('缺少 token 或 encounter_id 参数')
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
        useEmbedStore.getState().setEmbed(session)
        // 把当前接诊塞进 activeEncounterStore，WorkbenchPage 接管后直接进入接诊状态
        // activeEncounterStore 仅记录 encounterId + visitType + isFirstVisit，
        // 患者档案 / 姓名等由 WorkbenchPage 内部根据 encounterId 自己拉
        useActiveEncounterStore.setState({
          encounterId: session.encounter_id,
          visitType: session.visit_type as 'outpatient' | 'emergency' | 'inpatient',
          isFirstVisit: session.is_first_visit,
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
  }, [token, encounterId])

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
        <Spin size="large" tip="正在打开嵌入工作台..." />
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
