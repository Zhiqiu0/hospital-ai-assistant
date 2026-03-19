import { create } from 'zustand'

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
}

export interface QCIssue {
  issue_type?: string          // 'completeness' | 'insurance' | 'format' | 'logic' etc.
  risk_level: 'high' | 'medium' | 'low'
  field_name: string
  issue_description: string
  suggestion: string
  score_impact?: string
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
  isGenerating: boolean
  isPolishing: boolean
  isQCing: boolean
  qcIssues: QCIssue[]
  qcSummary: string
  qcPass: boolean | null
  examSuggestions: ExamSuggestion[]
  isExamLoading: boolean
  currentPatient: PatientInfo | null
  currentEncounterId: string | null
  setInquiry: (data: InquiryData) => void
  setRecordContent: (content: string) => void
  setRecordType: (type: string) => void
  setGenerating: (v: boolean) => void
  setPolishing: (v: boolean) => void
  setQCing: (v: boolean) => void
  setQCResult: (issues: QCIssue[], summary: string, pass: boolean) => void
  setExamSuggestions: (items: ExamSuggestion[]) => void
  setExamLoading: (v: boolean) => void
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
}

export const useWorkbenchStore = create<WorkbenchState>((set) => ({
  inquiry: defaultInquiry,
  inquirySavedAt: 0,
  recordContent: '',
  recordType: 'outpatient',
  isGenerating: false,
  isPolishing: false,
  isQCing: false,
  qcIssues: [],
  qcSummary: '',
  qcPass: null,
  examSuggestions: [],
  isExamLoading: false,
  currentPatient: null,
  currentEncounterId: null,
  isFinal: false,
  finalizedAt: null,
  setInquiry: (data) => set({ inquiry: data, inquirySavedAt: Date.now() }),
  setRecordContent: (content) => set({ recordContent: content }),
  setRecordType: (type) => set({ recordType: type }),
  setGenerating: (v) => set({ isGenerating: v }),
  setPolishing: (v) => set({ isPolishing: v }),
  setQCing: (v) => set({ isQCing: v }),
  setQCResult: (issues, summary, pass) => set({ qcIssues: issues, qcSummary: summary, qcPass: pass }),
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
    qcIssues: [],
    qcSummary: '',
    qcPass: null,
    examSuggestions: [],
    currentPatient: null,
    currentEncounterId: null,
    isFinal: false,
    finalizedAt: null,
  }),
}))
