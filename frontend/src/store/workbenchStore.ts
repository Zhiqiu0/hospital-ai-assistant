/**
 * 接诊工作台状态 Store（store/workbenchStore.ts）
 *
 * 使用 zustand + persist 中间件管理工作台全局状态：
 *
 * 主要状态分组：
 *   问诊数据   : inquiry（InquiryData）— 医生填写的所有问诊字段（门诊/住院/中医均含）
 *   病历内容   : recordContent（文本）、recordType（病历类型）
 *   接诊元信息 : currentPatient、currentEncounterId、isFirstVisit、currentVisitType
 *   AI 状态    : isGenerating、isPolishing、isQCing、qcRunId、qcLlmLoading
 *   质控结果   : qcIssues、qcSummary、qcPass、gradeScore
 *   建议结果   : examSuggestions、inquirySuggestions
 *   签发状态   : isFinal、finalizedAt
 *
 * persist 配置：
 *   name: 'medassist-workbench' → 存储到 localStorage（页面刷新后恢复工作台）
 *   partialize: 只持久化核心字段（排除 isGenerating 等 UI 中间态），
 *               防止刷新后仍显示"生成中"按钮状态
 *
 * qcRunId 设计：
 *   每次点击「质控」按钮调用 startQCRun()，会生成新的 runId（timestamp）。
 *   QCIssuePanel 监听 qcRunId 变化来重置每条 issue 的用户操作状态（resolved/ignored）。
 *   appendQCIssues 不更新 runId，LLM 建议追加时不触发用户状态重置。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface InquiryData {
  chief_complaint: string
  history_present_illness: string
  past_history: string
  allergy_history: string
  personal_history: string
  physical_exam: string
  initial_impression: string
  marital_history?: string
  menstrual_history?: string
  family_history?: string
  history_informant?: string
  current_medications?: string
  rehabilitation_assessment?: string
  religion_belief?: string
  pain_assessment?: string
  vte_risk?: string
  nutrition_assessment?: string
  psychology_assessment?: string
  auxiliary_exam?: string
  admission_diagnosis?: string
  // 门诊中医四诊
  tcm_inspection?: string
  tcm_auscultation?: string
  tongue_coating?: string
  pulse_condition?: string
  // 门诊诊断细化
  western_diagnosis?: string
  tcm_disease_diagnosis?: string
  tcm_syndrome_diagnosis?: string
  // 治疗意见
  treatment_method?: string
  treatment_plan?: string
  followup_advice?: string
  precautions?: string
  // 急诊附加
  observation_notes?: string
  patient_disposition?: string
  // 时间
  visit_time?: string
  onset_time?: string
}

export interface QCIssue {
  source?: 'rule' | 'llm' // rule=结构性必须修复，llm=质量建议
  issue_type?: string // 'completeness' | 'insurance' | 'format' | 'logic' etc.
  risk_level: 'high' | 'medium' | 'low'
  field_name: string
  issue_description: string
  suggestion: string
  score_impact?: string
}

export interface GradeScore {
  grade_score: number // 0-100
  grade_level: '甲级' | '乙级' | '丙级'
  strengths?: string[]
}

/** AI 诊断建议条目（供 InquirySuggestionTab 使用，持久化到 localStorage） */
export interface DiagnosisItem {
  name: string
  confidence: 'high' | 'medium' | 'low'
  reasoning: string
  next_steps: string
}

export interface ExamSuggestion {
  exam_name: string
  category: 'basic' | 'differential' | 'high_risk'
  reason: string
  /** 医生是否已开单，纯前端标记，刷新不丢失 */
  isOrdered?: boolean
}

export interface InquirySuggestion {
  id: string
  text: string
  priority: 'high' | 'medium' | 'low'
  is_red_flag: boolean
  category: string
  options: string[]
  selectedOptions: string[]
}

export interface PatientInfo {
  id: string
  name: string
  gender?: string
  age?: number | null
}

interface WorkbenchState {
  inquiry: InquiryData
  inquirySavedAt: number
  recordContent: string
  recordType: string
  isFirstVisit: boolean
  currentVisitType: string // 'outpatient' | 'emergency' | 'inpatient'
  isGenerating: boolean
  isPolishing: boolean
  isQCing: boolean
  /** 病历在上次质控后是否被修改过（true 时按钮显示「重新质控」） */
  isQCStale: boolean
  qcRunId: string // 每次点击质控时更新，QCIssuePanel 监听此值来重置操作状态
  qcLlmLoading: boolean // LLM 质量建议是否还在加载中
  qcIssues: QCIssue[]
  qcSummary: string
  qcPass: boolean | null
  gradeScore: GradeScore | null
  examSuggestions: ExamSuggestion[]
  isExamLoading: boolean
  inquirySuggestions: InquirySuggestion[]
  setInquirySuggestions: (items: InquirySuggestion[]) => void
  /** AI 诊断建议列表，持久化到 localStorage（刷新后保留） */
  diagnosisSuggestions: DiagnosisItem[]
  setDiagnosisSuggestions: (items: DiagnosisItem[]) => void
  /** 当前已写入病历的诊断名称，用于「已写入」高亮显示 */
  appliedDiagnosis: string | null
  setAppliedDiagnosis: (name: string | null) => void
  currentPatient: PatientInfo | null
  currentEncounterId: string | null
  setInquiry: (data: InquiryData) => void
  updateInquiryFields: (data: InquiryData) => void
  setVisitMeta: (isFirstVisit: boolean, visitType: string) => void
  setRecordContent: (content: string) => void
  setRecordType: (type: string) => void
  setGenerating: (v: boolean) => void
  setPolishing: (v: boolean) => void
  setQCing: (v: boolean) => void
  /** 开始新一轮质控：生成新 runId，清空上一轮结果 */
  startQCRun: () => void
  setQCResult: (
    issues: QCIssue[],
    summary: string,
    pass: boolean | null,
    gradeScore?: GradeScore | null
  ) => void
  /** 追加 LLM 质量建议（不触发 runId 变化，不清空用户操作状态） */
  appendQCIssues: (issues: QCIssue[]) => void
  setQCSummary: (summary: string) => void
  setQCLlmLoading: (v: boolean) => void
  setExamSuggestions: (items: ExamSuggestion[]) => void
  setExamLoading: (v: boolean) => void
  pendingGenerate: boolean
  setPendingGenerate: (v: boolean) => void
  isFinal: boolean
  finalizedAt: string | null
  setFinal: (v: boolean) => void
  setCurrentEncounter: (patient: PatientInfo | null, encounterId: string | null) => void
  appendInquiryNote: (note: string) => void
  setInitialImpression: (text: string) => void
  appendToRecord: (text: string) => void
  reset: () => void
}

const defaultInquiry: InquiryData = {
  chief_complaint: '',
  history_present_illness: '',
  past_history: '',
  allergy_history: '',
  personal_history: '',
  physical_exam: '',
  initial_impression: '',
  marital_history: '',
  menstrual_history: '',
  family_history: '',
  history_informant: '',
  current_medications: '',
  rehabilitation_assessment: '',
  religion_belief: '',
  pain_assessment: '',
  vte_risk: '',
  nutrition_assessment: '',
  psychology_assessment: '',
  auxiliary_exam: '',
  admission_diagnosis: '',
  tcm_inspection: '',
  tcm_auscultation: '',
  tongue_coating: '',
  pulse_condition: '',
  western_diagnosis: '',
  tcm_disease_diagnosis: '',
  tcm_syndrome_diagnosis: '',
  treatment_method: '',
  treatment_plan: '',
  followup_advice: '',
  precautions: '',
  observation_notes: '',
  patient_disposition: '',
  visit_time: '',
  onset_time: '',
}

export const useWorkbenchStore = create<WorkbenchState>()(
  persist(
    set => ({
      inquiry: defaultInquiry,
      inquirySavedAt: 0,
      recordContent: '',
      recordType: 'outpatient',
      isFirstVisit: true,
      currentVisitType: 'outpatient',
      isGenerating: false,
      isPolishing: false,
      isQCing: false,
      isQCStale: false,
      qcRunId: '',
      qcLlmLoading: false,
      qcIssues: [],
      qcSummary: '',
      qcPass: null,
      gradeScore: null,
      examSuggestions: [],
      isExamLoading: false,
      inquirySuggestions: [],
      setInquirySuggestions: items => set({ inquirySuggestions: items }),
      diagnosisSuggestions: [],
      setDiagnosisSuggestions: items => set({ diagnosisSuggestions: items }),
      appliedDiagnosis: null,
      setAppliedDiagnosis: name => set({ appliedDiagnosis: name }),
      currentPatient: null,
      currentEncounterId: null,
      pendingGenerate: false,
      setPendingGenerate: v => set({ pendingGenerate: v }),
      isFinal: false,
      finalizedAt: null,
      setVisitMeta: (isFirstVisit, visitType) => set({ isFirstVisit, currentVisitType: visitType }),
      setInquiry: data => set({ inquiry: data, inquirySavedAt: Date.now() }),
      updateInquiryFields: data => set({ inquiry: data }),
      setRecordContent: content =>
        set(state => ({
          recordContent: content,
          // 病历内容变更后，若已有质控结果则标记结果已过时
          isQCStale: state.qcIssues.length > 0 || state.qcPass !== null ? true : state.isQCStale,
        })),
      setRecordType: type => set({ recordType: type }),
      setGenerating: v => set({ isGenerating: v }),
      setPolishing: v => set({ isPolishing: v }),
      setQCing: v => set({ isQCing: v }),
      startQCRun: () =>
        set({
          qcRunId: Date.now().toString(),
          qcIssues: [],
          qcSummary: '',
          qcPass: null,
          gradeScore: null,
          qcLlmLoading: false,
          isQCStale: false, // 新一轮质控开始，重置过时标记
        }),
      setQCResult: (issues, summary, pass, gradeScore = null) =>
        set({ qcIssues: issues, qcSummary: summary, qcPass: pass, gradeScore }),
      appendQCIssues: issues => set(state => ({ qcIssues: [...state.qcIssues, ...issues] })),
      setQCSummary: summary => set({ qcSummary: summary }),
      setQCLlmLoading: v => set({ qcLlmLoading: v }),
      setExamSuggestions: items => set({ examSuggestions: items }),
      setExamLoading: v => set({ isExamLoading: v }),
      setFinal: v =>
        set({ isFinal: v, finalizedAt: v ? new Date().toLocaleString('zh-CN') : null }),
      setCurrentEncounter: (patient, encounterId) =>
        set(state => ({
          currentPatient: patient,
          currentEncounterId: encounterId,
          // 切换到不同接诊时才清空检查建议，同一接诊刷新不清空
          examSuggestions: state.currentEncounterId !== encounterId ? [] : state.examSuggestions,
        })),
      appendToRecord: text =>
        set(state => ({
          recordContent: state.recordContent ? state.recordContent + '\n\n' + text : text,
        })),
      setInitialImpression: text =>
        set(state => ({
          inquiry: { ...state.inquiry, initial_impression: text },
        })),
      appendInquiryNote: note =>
        set(state => ({
          inquiry: {
            ...state.inquiry,
            history_present_illness: state.inquiry.history_present_illness
              ? state.inquiry.history_present_illness + '\n' + note
              : note,
          },
        })),
      reset: () =>
        set({
          inquiry: defaultInquiry,
          inquirySavedAt: 0,
          recordContent: '',
          recordType: 'outpatient',
          isFirstVisit: true,
          currentVisitType: 'outpatient',
          qcRunId: '',
          qcLlmLoading: false,
          isQCStale: false,
          qcIssues: [],
          qcSummary: '',
          qcPass: null,
          gradeScore: null,
          examSuggestions: [],
          inquirySuggestions: [],
          diagnosisSuggestions: [],
          appliedDiagnosis: null,
          currentPatient: null,
          currentEncounterId: null,
          isFinal: false,
          finalizedAt: null,
        }),
    }),
    {
      name: 'medassist-workbench',
      partialize: state => ({
        inquiry: state.inquiry,
        inquirySavedAt: state.inquirySavedAt,
        recordContent: state.recordContent,
        recordType: state.recordType,
        isFirstVisit: state.isFirstVisit,
        currentVisitType: state.currentVisitType,
        currentPatient: state.currentPatient,
        currentEncounterId: state.currentEncounterId,
        isFinal: state.isFinal,
        finalizedAt: state.finalizedAt,
        // 追问/诊断建议持久化，刷新后不丢失
        inquirySuggestions: state.inquirySuggestions,
        diagnosisSuggestions: state.diagnosisSuggestions,
        appliedDiagnosis: state.appliedDiagnosis,
        // 检查建议持久化（含已开单状态）
        examSuggestions: state.examSuggestions,
        // 质控结果持久化
        qcIssues: state.qcIssues,
        qcSummary: state.qcSummary,
        qcPass: state.qcPass,
        gradeScore: state.gradeScore,
        isQCStale: state.isQCStale,
      }),
    }
  )
)
