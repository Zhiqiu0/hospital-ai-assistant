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
  source?: 'rule' | 'llm'      // rule=结构性必须修复，llm=质量建议
  issue_type?: string          // 'completeness' | 'insurance' | 'format' | 'logic' etc.
  risk_level: 'high' | 'medium' | 'low'
  field_name: string
  issue_description: string
  suggestion: string
  score_impact?: string
}

export interface GradeScore {
  grade_score: number          // 0-100
  grade_level: '甲级' | '乙级' | '丙级'
  strengths?: string[]
}

export interface ExamSuggestion {
  exam_name: string
  category: 'basic' | 'differential' | 'high_risk'
  reason: string
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
  currentVisitType: string   // 'outpatient' | 'emergency' | 'inpatient'
  isGenerating: boolean
  isPolishing: boolean
  isQCing: boolean
  qcIssues: QCIssue[]
  qcSummary: string
  qcPass: boolean | null
  gradeScore: GradeScore | null
  examSuggestions: ExamSuggestion[]
  isExamLoading: boolean
  inquirySuggestions: any[]
  setInquirySuggestions: (items: any[]) => void
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
  setQCResult: (issues: QCIssue[], summary: string, pass: boolean, gradeScore?: GradeScore | null) => void
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
  (set) => ({
  inquiry: defaultInquiry,
  inquirySavedAt: 0,
  recordContent: '',
  recordType: 'outpatient',
  isFirstVisit: true,
  currentVisitType: 'outpatient',
  isGenerating: false,
  isPolishing: false,
  isQCing: false,
  qcIssues: [],
  qcSummary: '',
  qcPass: null,
  gradeScore: null,
  examSuggestions: [],
  isExamLoading: false,
  inquirySuggestions: [],
  setInquirySuggestions: (items) => set({ inquirySuggestions: items }),
  currentPatient: null,
  currentEncounterId: null,
  pendingGenerate: false,
  setPendingGenerate: (v) => set({ pendingGenerate: v }),
  isFinal: false,
  finalizedAt: null,
  setVisitMeta: (isFirstVisit, visitType) => set({ isFirstVisit, currentVisitType: visitType }),
  setInquiry: (data) => set({ inquiry: data, inquirySavedAt: Date.now() }),
  updateInquiryFields: (data) => set({ inquiry: data }),
  setRecordContent: (content) => set({ recordContent: content }),
  setRecordType: (type) => set({ recordType: type }),
  setGenerating: (v) => set({ isGenerating: v }),
  setPolishing: (v) => set({ isPolishing: v }),
  setQCing: (v) => set({ isQCing: v }),
  setQCResult: (issues, summary, pass, gradeScore = null) => set({ qcIssues: issues, qcSummary: summary, qcPass: pass, gradeScore }),
  setExamSuggestions: (items) => set({ examSuggestions: items }),
  setExamLoading: (v) => set({ isExamLoading: v }),
  setFinal: (v) => set({ isFinal: v, finalizedAt: v ? new Date().toLocaleString('zh-CN') : null }),
  setCurrentEncounter: (patient, encounterId) => set({ currentPatient: patient, currentEncounterId: encounterId }),
  appendToRecord: (text) => set((state) => ({
    recordContent: state.recordContent
      ? state.recordContent + '\n\n' + text
      : text,
  })),
  setInitialImpression: (text) => set((state) => ({
    inquiry: { ...state.inquiry, initial_impression: text },
  })),
  appendInquiryNote: (note) => set((state) => ({
    inquiry: {
      ...state.inquiry,
      history_present_illness: state.inquiry.history_present_illness
        ? state.inquiry.history_present_illness + '\n' + note
        : note,
    },
  })),
  reset: () => set({
    inquiry: defaultInquiry,
    inquirySavedAt: 0,
    recordContent: '',
    recordType: 'outpatient',
    isFirstVisit: true,
    currentVisitType: 'outpatient',
    qcIssues: [],
    qcSummary: '',
    qcPass: null,
    gradeScore: null,
    examSuggestions: [],
    inquirySuggestions: [],
    currentPatient: null,
    currentEncounterId: null,
    isFinal: false,
    finalizedAt: null,
  }),
  }),
  {
    name: 'medassist-workbench',
    partialize: (state) => ({
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
    }),
  }
))
