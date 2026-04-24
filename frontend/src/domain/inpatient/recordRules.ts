/**
 * 住院文书类型规则（domain/inpatient/recordRules.ts）
 *
 * 定义每种住院文书的显示标签、图标颜色、书写截止要求。
 * 用于时间轴展示和合规提醒。
 */

export type InpatientNoteType =
  | 'admission_note'    // 入院记录
  | 'first_course'      // 首次病程记录
  | 'daily_course'      // 日常病程记录
  | 'surgery_pre'       // 术前小结
  | 'surgery_post'      // 术后病程
  | 'discharge'         // 出院小结

export interface NoteTypeRule {
  label: string
  color: string          // Ant Design tag 颜色
  bgColor: string        // 时间轴条目背景
  /** 入院后多少小时内必须完成（null = 无硬性截止）*/
  deadlineHours: number | null
  /** 是否可重复书写（日常病程可多次，入院记录只有1份）*/
  repeatable: boolean
}

export const NOTE_TYPE_RULES: Record<InpatientNoteType | string, NoteTypeRule> = {
  admission_note: {
    label: '入院记录',
    color: 'blue',
    bgColor: '#eff6ff',
    deadlineHours: 24,
    repeatable: false,
  },
  first_course: {
    label: '首次病程',
    color: 'cyan',
    bgColor: '#ecfeff',
    deadlineHours: 8,
    repeatable: false,
  },
  daily_course: {
    label: '日常病程',
    color: 'green',
    bgColor: '#f0fdf4',
    deadlineHours: null,
    repeatable: true,
  },
  surgery_pre: {
    label: '术前小结',
    color: 'orange',
    bgColor: '#fff7ed',
    deadlineHours: null,
    repeatable: false,
  },
  surgery_post: {
    label: '术后病程',
    color: 'volcano',
    bgColor: '#fff1f0',
    deadlineHours: 6,
    repeatable: false,
  },
  discharge: {
    label: '出院小结',
    color: 'purple',
    bgColor: '#faf5ff',
    deadlineHours: 24,
    repeatable: false,
  },
}

export function getNoteRule(noteType: string): NoteTypeRule {
  return NOTE_TYPE_RULES[noteType] ?? {
    label: noteType,
    color: 'default',
    bgColor: 'var(--surface-2)',
    deadlineHours: null,
    repeatable: true,
  }
}
