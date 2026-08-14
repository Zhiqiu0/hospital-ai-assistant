/**
 * 接诊响应统一接入工具（store/encounterIntake.ts）
 *
 * 后端 `quick-start` 与 `workspace snapshot` 接口都返回 `patient` + `patient_profile`
 * 两段数据。前端有 4 处入口需要把这两段数据同步到 patientCacheStore：
 *   1. WorkbenchPage（门诊/急诊新建/复诊）
 *   2. hooks/inquiryPanel/useEmergencyFlow（急诊→住院转入）
 *   3. NewInpatientEncounterModal（住院新建）
 *   4. pages/inpatientWorkbench/encounterCreated（住院工作台建档回调）
 *
 * 把这段重复逻辑收口到本文件，调用方只需一行 `applyQuickStartResult(res)`，
 * 既避免了 4 处实现分叉，也方便后续扩展（如增加埋点 / 缓存预热）。
 * （历史：旧 workbenchStore 及其指针字段已在迁移完成后整体删除。）
 */

import { usePatientCacheStore } from './patientCacheStore'
import { useActiveEncounterStore } from './activeEncounterStore'
import { useInquiryStore } from './inquiryStore'
import { useRecordStore } from './recordStore'
import { useQCStore } from './qcStore'
import { useAISuggestionStore } from './aiSuggestionStore'
import type { PatientProfile, VisitType } from '@/domain/medical'
import type {
  InquiryData,
  QCIssue,
  ExamSuggestion,
  InquirySuggestion,
  DiagnosisItem,
} from './types'
import { genderCode } from '@/utils/gender'

/** quick-start 与 snapshot 共有的最小字段集合 */
export interface EncounterIntakePayload {
  encounter_id?: string | null
  patient?: {
    id: string
    name: string
    gender?: string | null
    age?: number | null
    phone?: string | null
    birth_date?: string | null
  } | null
  /** 后端 patient_profile 含 8 个 profile_* 字段 + updated_at；可为 null */
  patient_profile?: (PatientProfile & { updated_at?: string | null }) | null
  visit_type?: string | null
  patient_reused?: boolean
  previous_record_content?: string | null
  /** 就诊时间：病案首页的法定字段，不能拿签发时间顶替 */
  visited_at?: string | null
}

/** quick-start 响应专用：含初诊/复诊判断、上次病历参考 */
export interface QuickStartResult extends EncounterIntakePayload {
  encounter_id: string
  patient: NonNullable<EncounterIntakePayload['patient']>
  resumed?: boolean
}

/** snapshot 响应专用：含 active_record / inquiry，可能 inquiry 为 null */
export interface SnapshotResult extends EncounterIntakePayload {
  /** 接诊问诊数据（医生填的字段） */
  inquiry?: Partial<InquiryData> | null
  /** 当前活跃病历的最新版本（含 content 文本） */
  active_record?: {
    record_id?: string
    record_type?: string
    status?: string
    content?: string
    /** ISO 字符串，后端 _serialize_record 返回，用于状态条显示"X 分钟前保存" */
    updated_at?: string | null
  } | null
  /** 最新 QC 跑出来的问题列表（logout 重登也能恢复） */
  latest_qc_issues?: QCIssue[] | null
  /**
   * 各类 AI 建议产物（追问 / 检查 / 诊断），key=task_type
   *
   * 后端只存 LLM 原始输出，没有"医生临时勾选"状态（selectedOptions / isOrdered），
   * 所以追问/检查这两类用 Partial 包一层避免 id 等字段缺失时报错；前端在
   * applySnapshotResult 内做"恢复缺省值"合并。
   */
  latest_ai_suggestions?: {
    inquiry?: { suggestions?: Partial<InquirySuggestion>[] }
    exam?: { suggestions?: Partial<ExamSuggestion>[] }
    diagnosis?: { diagnoses?: DiagnosisItem[] }
  } | null
}

/**
 * 把后端 patient + patient_profile 写入 patientCacheStore。
 * patient 缺失时整体跳过，避免悬空 profile。
 */
function syncPatientToCache(payload: EncounterIntakePayload): void {
  const patient = payload.patient
  if (!patient) return
  const cache = usePatientCacheStore.getState()
  // 把后端 patient 形状收敛到 domain 层 Patient 类型
  cache.upsertPatient({
    id: patient.id,
    name: patient.name,
    gender: genderCode(patient.gender),
    age: patient.age ?? null,
    phone: patient.phone ?? null,
    birth_date: patient.birth_date ?? null,
  })
  if (payload.patient_profile) {
    // 剥离 updated_at 之外仍写入；patientCache 的 PatientProfile 类型本身允许 updated_at
    cache.upsertProfile(patient.id, payload.patient_profile)
  }
}

/**
 * 把后端 visit_type 字符串收敛到 VisitType 联合类型。
 * 未知值默认归为 outpatient，避免类型不匹配造成路由分支错乱。
 */
function normalizeVisitType(raw?: string | null): VisitType {
  if (raw === 'emergency' || raw === 'inpatient' || raw === 'outpatient') return raw
  return 'outpatient'
}

/**
 * 处理 quick-start 响应：写患者缓存 + 设置 activeEncounterStore。
 * 只负责"接入"两个 store，不与调用方的其他清理/跳转逻辑耦合。
 */
export function applyQuickStartResult(res: QuickStartResult): void {
  syncPatientToCache(res)
  useActiveEncounterStore.getState().setActive({
    patientId: res.patient.id,
    encounterId: res.encounter_id,
    visitType: normalizeVisitType(res.visit_type),
    // patient_reused=true 表示复诊，对应 isFirstVisit=false
    isFirstVisit: !res.patient_reused,
    isPatientReused: !!res.patient_reused,
    previousRecordContent: res.previous_record_content ?? null,
    visitedAt: res.visited_at ?? null,
  })
}

/**
 * 处理 workspace snapshot 响应：写所有相关 store + 患者缓存 + activeEncounterStore。
 *
 * ★ 治本：兑现"snapshot 恢复 = 把所有 store 灌满"的承诺。
 *   过去的实现只填了 patientCache + activeEncounter，logout 重登时
 *   inquiry / record / qc / aiSuggestion 4 个 store 全是空的——给医生
 *   "数据丢了"的错觉。
 *
 *   现在把后端 snapshot 返回的 inquiry / active_record /
 *   latest_qc_issues / latest_ai_suggestions 一并灌回前端 store，
 *   做到"DB 有什么 → 前端就显示什么"。
 *
 * 与 applyQuickStartResult 相比，snapshot 没有 patient_reused 概念，
 * 这里默认按"复诊场景"处理（isFirstVisit=false），等待调用方按业务再修正。
 */
export function applySnapshotResult(res: SnapshotResult): void {
  syncPatientToCache(res)
  if (res.encounter_id && res.patient) {
    useActiveEncounterStore.getState().setActive({
      patientId: res.patient.id,
      encounterId: res.encounter_id,
      visitType: normalizeVisitType(res.visit_type),
      // 恢复接诊时无法判定初诊/复诊，沿用最保守的复诊态，避免误清空 previous_record
      isFirstVisit: false,
      isPatientReused: true,
      previousRecordContent: null,
    })
  }

  // ── 灌回 4 个工作台 store（业务核心数据） ────────────────────────
  // inquiry：医生填的问诊字段
  if (res.inquiry) {
    // updateInquiryFields 用部分字段补丁覆盖，不打"已保存"标记
    // （未保存状态由用户编辑触发，不由恢复触发）
    //
    // 后端 snapshot 返回的 inquiry 只含已填字段，是 Partial<InquiryData>；
    // store 签名要 InquiryData（43 字段全集）。这里用 unknown 桥接而非 any，
    // 让类型转换是受控的：缺失字段保持 undefined，下游字段访问全部走 `?? ''`
    // 兜底（store 内部所有字段都是 string | undefined）。
    useInquiryStore.getState().updateInquiryFields(res.inquiry as unknown as InquiryData)
  }

  // record：当前活跃病历的内容
  if (res.active_record) {
    const recordStore = useRecordStore.getState()
    if (res.active_record.record_type) {
      recordStore.setRecordType(res.active_record.record_type)
    }

    // ⚠️ 不无条件覆盖本地正文（2026-08-13 第五轮审计修复）
    // auto-save 是 5 秒防抖的，医生打完一段话立刻刷新页面（或断网重连触发水合）时，
    // 最后那几秒的内容还没落库。原先这里直接 setRecordContent(服务端内容)，
    // 等于把医生刚写的一段**静默回滚**成服务端旧版——医生不会收到任何提示，
    // 只会发现自己写的东西没了，而病历正是本产品最不能丢的东西。
    // 判据用**内容比对**而不是时间戳：医生打完话立刻刷新时，recordSavedAt 还是
    // 上一次保存的时刻、不会晚于服务端，靠时间戳判断会漏掉正要保护的那个场景。
    // current !== lastSaved 才准确表示"有未落库的本地编辑"。
    // （下面 qc 那段早就是"只在前端为空时才灌入"的写法，这里是同一个道理。）
    const localContent = recordStore.recordContent
    const localIsDirty = !!localContent && localContent !== recordStore.lastSavedContent

    if (!localIsDirty) {
      recordStore.setRecordContent(res.active_record.content || '')
    }
    recordStore.setFinal(res.active_record.status === 'submitted')
    // 把 DB 里的 updated_at 灌回 recordSavedAt——logout 重登 / 切设备时
    // 状态条立即显示"病历 X 分钟前保存"，而不是误报"草稿未保存"。
    // 本地有未保存编辑时不回灌，否则会把"本地更脏"这个事实抹掉，下次水合就覆盖了。
    if (!localIsDirty && res.active_record.updated_at) {
      const ts = Date.parse(res.active_record.updated_at)
      if (!isNaN(ts)) recordStore.markSaved(res.active_record.content || '', ts)
    }
  }

  // qc：最新一次 QC 跑出来的问题列表
  // ⚠️ 只在前端 store 为空时灌入——刷新时 zustand persist 已经从 localStorage
  // 恢复了 qcFixTexts（医生编辑的修复内容）和 qcWrittenIndices（已写入标记），
  // 直接 setQCResult 会触发 startQCRun 等价动作把这些临时编辑全冲掉。
  if (res.latest_qc_issues && res.latest_qc_issues.length > 0) {
    const qcStore = useQCStore.getState()
    if (qcStore.qcIssues.length === 0) {
      // pass 不能硬编码 false：
      //   后端 qc_stream_service.py 的判定是 blocking_count == 0
      //   （source='rule' / 'insurance' 才算 blocking，LLM 质量建议不算）。
      //   恢复时用同样口径重算，否则只剩 4 条 LLM 质量建议时
      //   左侧 toolbar 错误显示"结构未通过"，与右侧面板"必须修复 0 项"矛盾。
      const blockingCount = res.latest_qc_issues.filter(
        i => i.source === 'rule' || i.source == null
      ).length
      qcStore.setQCResult(res.latest_qc_issues, '', blockingCount === 0, null)
    }
  }

  // aiSuggestion：追问 / 检查 / 诊断三类建议
  // ⚠️ 合并而非覆盖——保留医生临时勾选状态：
  //   - examSuggestions.isOrdered（医生勾的"已开单"）
  //   - inquirySuggestions.selectedOptions（医生选的追问选项）
  // 后端 snapshot 拿不到这些临时状态（只存 LLM 原始 output），如果直接覆盖
  // 医生每次刷新 / 复诊点击都会丢勾选——这是用户报告的"举一反三"问题。
  const aiSug = res.latest_ai_suggestions
  if (aiSug) {
    const store = useAISuggestionStore.getState()

    // 追问：按 text 匹配前端已有项，保留 selectedOptions
    if (aiSug.inquiry?.suggestions) {
      const existingByText = new Map(store.inquirySuggestions.map(s => [s.text, s]))
      store.setInquirySuggestions(
        aiSug.inquiry.suggestions.map((s, idx) => {
          const existing = existingByText.get(s.text ?? '')
          // 补齐 InquirySuggestion 的必填字段；后端无值时给安全默认值
          return {
            text: s.text ?? '',
            priority: s.priority ?? 'medium',
            is_red_flag: s.is_red_flag ?? false,
            category: s.category ?? '',
            ...s,
            id: existing?.id ?? `restored-${idx}`,
            options: s.options || [],
            // 保留医生已选的选项；前端无该项时初始化空数组
            selectedOptions: existing?.selectedOptions ?? [],
          } as InquirySuggestion
        })
      )
    }

    // 检查建议：按 exam_name 匹配前端已有项，保留 isOrdered
    if (aiSug.exam?.suggestions) {
      const existingByName = new Map(store.examSuggestions.map(s => [s.exam_name, s]))
      store.setExamSuggestions(
        aiSug.exam.suggestions.map(
          s =>
            ({
              exam_name: s.exam_name ?? '',
              category: s.category ?? 'basic',
              reason: s.reason ?? '',
              ...s,
              // 保留医生标记的"已开单"状态，后端不存这个，前端独立维护
              isOrdered: existingByName.get(s.exam_name ?? '')?.isOrdered ?? s.isOrdered,
            }) as ExamSuggestion
        )
      )
    }

    // 诊断：直接灌（diagnoses 列表本身没有"局部勾选"状态，
    // appliedDiagnosis 是单独字段，不在此 list 里，不会被冲掉）
    if (aiSug.diagnosis?.diagnoses) {
      store.setDiagnosisSuggestions(aiSug.diagnosis.diagnoses)
    }
  }
}
