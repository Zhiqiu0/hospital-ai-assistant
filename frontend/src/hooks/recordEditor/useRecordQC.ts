/**
 * AI 质控动作（hooks/recordEditor/useRecordQC.ts）
 *
 * 职责：病历"AI 质控"动作编排——
 *   - SSE 多事件分发（rule_issues / llm_issues / done）写入 qcStore
 *   - done 事件后按评分等级弹出汇总提示
 *   - handleQC 接受 contentOverride，供补全完成后自动重新质控复用
 *
 * 拆分来源：2026-06-11 Round 5 从 hooks/useRecordEditor.ts（约 500 行）拆出，
 * 纯搬家不改逻辑。
 */
import { message } from '@/services/messageBridge'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { useActiveEncounterStore, useCurrentPatient } from '@/store/activeEncounterStore'
import type { QCIssue, GradeScore, ScoreReport } from '@/store/types'
import type { RecordEditorShared } from './useRecordEditorShared'

/**
 * SSE 事件 - 质控流的统一对象形状。
 * 后端会按 type 分发不同 payload：
 *   rule_issues: 携带 issues / pass / grade_score
 *   llm_issues:  追加质量建议（不影响 pass）
 *   done:        最终摘要 + 评分汇总
 */
interface QCStreamEvent {
  type?: string
  issues?: QCIssue[]
  pass?: boolean
  grade_score?: number
  grade_level?: GradeScore['grade_level']
  must_fix_count?: number
  summary?: string
  /** 后端按 PDF 大项结构化产出的评分报告（rule_issues 事件携带） */
  score_report?: ScoreReport
}

export function useRecordQC(shared: RecordEditorShared) {
  const { runSSE } = shared
  const { recordType } = useRecordStore()
  const { setQCing, setQCResult, appendQCIssues, setQCSummary, setQCLlmLoading, startQCRun } =
    useQCStore()
  const currentPatient = useCurrentPatient()
  const currentEncounterId = useActiveEncounterStore(s => s.encounterId)

  const handleQC = async (contentOverride?: string) => {
    const qcContent = contentOverride ?? useRecordStore.getState().recordContent
    if (!qcContent.trim()) {
      message.warning('病历内容为空，无法质控')
      return
    }
    setQCing(true)
    startQCRun()
    // finalData 收集 done 事件的载荷，跨 onEvent 闭包累积——用 QCStreamEvent 类型化
    let finalData: QCStreamEvent | null = null
    try {
      // 质控接口推回多种事件类型（rule_issues / llm_issues / done），
      // 用 streamSSE 的通用 onEvent 分发器统一处理
      await runSSE(
        '/api/v1/ai/quick-qc',
        {
          content: qcContent,
          record_type: recordType,
          // 患者基础信息（C 方案 FHIR PatientMeta）—— 让规则引擎正确判定"基础信息齐全"
          patient_name: currentPatient?.name || '',
          patient_gender: currentPatient?.gender || '',
          patient_age: currentPatient?.age != null ? String(currentPatient.age) : '',
          is_first_visit: useActiveEncounterStore.getState().isFirstVisit,
          encounter_id: currentEncounterId || undefined,
        },
        {
          // streamSSE 的 onEvent 参数本身是泛型对象，这里把它收敛到 QCStreamEvent
          onEvent: (raw: unknown) => {
            const obj = (raw || {}) as QCStreamEvent
            if (obj.type === 'rule_issues') {
              const gs: GradeScore | null =
                obj.grade_score != null && obj.grade_level
                  ? {
                      grade_score: obj.grade_score,
                      grade_level: obj.grade_level,
                      must_fix_count: obj.must_fix_count,
                    }
                  : null
              // score_report 在此一并入 store——A 方案分组渲染的数据源
              setQCResult(obj.issues || [], '', obj.pass ?? false, gs, obj.score_report ?? null)
              setQCLlmLoading(true)
            } else if (obj.type === 'llm_issues') {
              appendQCIssues(obj.issues || [])
            } else if (obj.type === 'done') {
              finalData = obj
              setQCSummary(obj.summary || '')
              setQCLlmLoading(false)
            }
          },
        }
      )
      if (finalData) {
        // TS 在闭包外无法推断回调里赋值的 finalData，借助 const 收敛非 null 视图
        const done: QCStreamEvent = finalData
        const totalIssues = useQCStore.getState().qcIssues.length
        if (done.grade_level === '合格' || done.grade_level === '甲级') {
          message.success(`质控通过！评分 ${done.grade_score} 分（${done.grade_level}）`)
        } else if (done.grade_score != null) {
          message.warning(
            `评分 ${done.grade_score} 分（${done.grade_level}），发现 ${totalIssues} 个问题，请查看右侧质控提示`
          )
        } else if (done.pass) {
          message.success('质控通过！')
        } else {
          message.warning(`发现 ${totalIssues} 个问题，请查看右侧质控提示`)
        }
      }
    } catch (e) {
      if ((e as { name?: string })?.name !== 'AbortError') message.error('质控失败，请重试')
      setQCLlmLoading(false)
    } finally {
      setQCing(false)
      setQCLlmLoading(false)
    }
  }

  return { handleQC }
}
