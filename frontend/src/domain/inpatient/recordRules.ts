/**
 * 住院文书类型规则（domain/inpatient/recordRules.ts）
 *
 * 定义每种住院文书的显示标签与图标颜色，用于时间轴展示。
 * 时限口径不在这里（2026-08-28 口径对拍清理）：原 deadlineHours 是与后端
 * record_deadlines.py 各写一份的第二真相源（数值已漂移且无消费点），
 * 已删除——时限一律吃后端 /compliance 接口。
 */

export type InpatientNoteType =
  | 'admission_note' // 入院记录
  | 'first_course' // 首次病程记录
  | 'daily_course' // 日常病程记录
  | 'surgery_pre' // 术前小结
  | 'surgery_post' // 术后病程
  | 'discharge' // 出院小结

export interface NoteTypeRule {
  label: string
  color: string // Ant Design tag 颜色
  bgColor: string // 时间轴条目背景
  /** 是否可重复书写（日常病程可多次，入院记录只有1份）*/
  repeatable: boolean
}

export const NOTE_TYPE_RULES: Record<InpatientNoteType | string, NoteTypeRule> = {
  // ── MedicalRecord 侧的 record_type（2026-08-14 第八轮审计修复）──────────────
  //
  // 本表原先只认 ProgressNote 那套 key（first_course / daily_course /
  // surgery_pre / surgery_post / discharge）。而住院时间轴上同时有
  // MedicalRecord 条目，它们的 record_type 是另一套命名
  // （course_record / first_course_record / discharge_record / senior_round…），
  // 全部 miss → getNoteRule 兜底把**原始英文 key 当中文标签**返回，
  // 时间轴上直接显示 "course_record"、"discharge_record" 给医生看。
  // 两套命名短期内不打算统一（改 record_type 会牵动 HIS 回写枚举），
  // 这里补齐映射，让展示层先正确。
  course_record: {
    label: '日常病程',
    color: 'green',
    bgColor: '#f0fdf4',
    repeatable: true,
  },
  first_course_record: {
    label: '首次病程',
    color: 'cyan',
    bgColor: '#ecfeff',
    repeatable: false,
  },
  senior_round: {
    label: '上级查房',
    color: 'purple',
    bgColor: '#faf5ff',
    repeatable: true,
  },
  discharge_record: {
    label: '出院记录',
    color: 'orange',
    bgColor: '#fff7ed',
    repeatable: false,
  },
  op_record: {
    label: '手术记录',
    color: 'red',
    bgColor: '#fef2f2',
    repeatable: true,
  },
  outpatient: {
    label: '门诊病历',
    color: 'blue',
    bgColor: '#eff6ff',
    repeatable: false,
  },

  admission_note: {
    label: '入院记录',
    color: 'blue',
    bgColor: '#eff6ff',
    repeatable: false,
  },
  first_course: {
    label: '首次病程',
    color: 'cyan',
    bgColor: '#ecfeff',
    repeatable: false,
  },
  daily_course: {
    label: '日常病程',
    color: 'green',
    bgColor: '#f0fdf4',
    repeatable: true,
  },
  surgery_pre: {
    label: '术前小结',
    color: 'orange',
    bgColor: '#fff7ed',
    repeatable: false,
  },
  surgery_post: {
    label: '术后病程',
    color: 'volcano',
    bgColor: '#fff1f0',
    repeatable: false,
  },
  discharge: {
    label: '出院小结',
    color: 'purple',
    bgColor: '#faf5ff',
    repeatable: false,
  },
}

export function getNoteRule(noteType: string): NoteTypeRule {
  return (
    NOTE_TYPE_RULES[noteType] ?? {
      label: noteType,
      color: 'default',
      bgColor: 'var(--surface-2)',
      repeatable: true,
    }
  )
}
