/** 最终正文诊断核对：确认只对同一次打开、同一文书和同一正文有效。 */
import { useEffect, useRef, useState } from 'react'
import api from '@/services/api'

export interface ConfirmedDiagnosis {
  name: string
  category?: 'western' | 'tcm_disease' | 'tcm_syndrome' | null
  is_primary: boolean
}
interface DiagnosisPreview {
  diagnoses: Array<ConfirmedDiagnosis & { code?: string | null; code_type?: string | null }>
  requires_confirmation: boolean
  projection_error: string | null
  his_writeback_required: boolean
}
interface PreviewInput {
  open: boolean
  content: string
  recordType: string
  encounterId?: string | null
  recordId?: string | null
  /** 文书选择代次用于识别切走再切回，不能仅比较 ID。 */
  selectionVersion?: number
}

export function useDiagnosisConfirmation(input: PreviewInput) {
  const { open, content, recordType, encounterId, recordId, selectionVersion } = input
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([
    open,
    content,
    recordType,
    encounterId,
    recordId,
    selectionVersion,
    retry,
  ])
  const [state, setState] = useState<{
    key: string
    preview: DiagnosisPreview | null
    error: string
    primary: number
    confirmed: boolean
  }>({ key: '', preview: null, error: '', primary: -1, confirmed: false })
  const request = useRef(0)
  useEffect(() => {
    const id = ++request.current
    setState({ key, preview: null, error: '', primary: -1, confirmed: false })
    if (!open) return
    // 输入修订正文时稍作合并；清除旧确认在渲染时已由 key 比较立即生效。
    const timer = setTimeout(() => {
      void api
        .post('/medical-records/diagnosis-preview', {
          encounter_id: encounterId || undefined,
          record_id: recordId || undefined,
          record_type: recordType,
          content,
        })
        .then(value => {
          if (request.current !== id) return
          const preview = value as unknown as DiagnosisPreview
          // 响应缺失不能当作“没有诊断”，否则会绕过实际的核对步骤。
          if (!Array.isArray(preview?.diagnoses)) throw new Error('诊断核对信息未完整返回，请重试')
          const primaries = preview.diagnoses.flatMap((item, index) =>
            item.is_primary ? [index] : []
          )
          setState({
            key,
            preview,
            error: '',
            primary: primaries.length === 1 ? primaries[0] : -1,
            confirmed: false,
          })
        })
        .catch(error => {
          if (request.current !== id) return
          const detail = (error as { detail?: unknown })?.detail
          setState({
            key,
            preview: null,
            error: typeof detail === 'string' ? detail : '诊断核对加载失败，请重试',
            primary: -1,
            confirmed: false,
          })
        })
    }, 250)
    return () => {
      clearTimeout(timer)
      request.current += 1
    }
  }, [key, open, content, recordType, encounterId, recordId])
  const current = state.key === key
  const preview = current ? state.preview : null
  const blocked = !!preview?.projection_error && preview.his_writeback_required
  const hasDiagnoses = !!preview?.diagnoses.length && !preview.projection_error
  const canConfirm = !!preview && !blocked && (!hasDiagnoses || state.primary >= 0)
  // 只回传名称、分类、主诊断，编码始终由服务端按最终正文重新匹配。
  const diagnoses = hasDiagnoses
    ? preview!.diagnoses.map((item, index) => ({
        name: item.name,
        category: item.category ?? null,
        is_primary: index === state.primary,
      }))
    : undefined
  return {
    preview,
    blocked,
    canConfirm,
    loading: open && !preview && !(current && state.error),
    error: current ? state.error : '',
    primary: current ? state.primary : -1,
    confirmed: current && state.confirmed,
    canSubmit: canConfirm && current && state.confirmed,
    diagnoses,
    selectPrimary: (primary: number) => setState(s => ({ ...s, primary, confirmed: false })),
    setConfirmed: (confirmed: boolean) => setState(s => ({ ...s, confirmed })),
    reload: () => setRetry(n => n + 1),
  }
}

export type DiagnosisConfirmationState = ReturnType<typeof useDiagnosisConfirmation>
