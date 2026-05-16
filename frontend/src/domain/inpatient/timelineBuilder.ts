/**
 * 住院时间轴构建（domain/inpatient/timelineBuilder.ts）
 *
 * 把入院记录（MedicalRecord）+ 病程记录（ProgressNote）合并成
 * 按时间排序的统一时间轴条目列表，供 InpatientTimeline 组件渲染。
 */

import { getNoteRule } from './recordRules'

export type TimelineItemType = 'medical_record' | 'progress_note'

export interface TimelineItem {
  id: string
  type: TimelineItemType
  noteType: string        // admission_note / first_course / daily_course / ...
  label: string           // 显示文字
  color: string           // tag 颜色
  bgColor: string
  recordedAt: string      // ISO 字符串
  status: string          // draft / submitted
  title?: string | null
  content: string
}

/**
 * 入院记录后端原始形状（来自 /encounters/{id}/workspace.active_record
 * 或 InpatientTimeline 本地构造）。字段全部 optional：后端返回多源、本地兜底
 * 可能只有最小子集。沿用与 domain/medical/types.ts MedicalRecord 兼容的命名。
 */
export interface MedicalRecordRaw {
  id?: string
  record_type?: string | null
  status?: string | null
  content?: string | null
  submitted_at?: string | null
  created_at?: string | null
}

/**
 * 病程记录后端原始形状（来自 /encounters/{id}/progress-notes items[]）。
 * 字段全部 optional：列表接口在不同写入态下字段会缺。
 */
export interface ProgressNoteRaw {
  id?: string
  note_type?: string | null
  title?: string | null
  status?: string | null
  content?: string | null
  recorded_at?: string | null
  created_at?: string | null
}

/** 将后端返回的 medical_record 转换为时间轴条目 */
export function medicalRecordToItem(r: MedicalRecordRaw): TimelineItem {
  const rule = getNoteRule(r.record_type || 'admission_note')
  return {
    id: r.id || '',
    type: 'medical_record',
    noteType: r.record_type || 'admission_note',
    label: rule.label,
    color: rule.color,
    bgColor: rule.bgColor,
    recordedAt: r.submitted_at || r.created_at || '',
    status: r.status || 'draft',
    title: null,
    content: r.content || '',
  }
}

/** 将后端返回的 progress_note 转换为时间轴条目 */
export function progressNoteToItem(n: ProgressNoteRaw): TimelineItem {
  const rule = getNoteRule(n.note_type || 'daily_course')
  return {
    id: n.id || '',
    type: 'progress_note',
    noteType: n.note_type || 'daily_course',
    label: n.title || rule.label,
    color: rule.color,
    bgColor: rule.bgColor,
    recordedAt: n.recorded_at || n.created_at || '',
    status: n.status || 'draft',
    title: n.title,
    content: n.content || '',
  }
}

/** 合并并按时间升序排列 */
export function buildTimeline(
  medicalRecords: MedicalRecordRaw[],
  progressNotes: ProgressNoteRaw[]
): TimelineItem[] {
  const items: TimelineItem[] = [
    ...medicalRecords.map(medicalRecordToItem),
    ...progressNotes.map(progressNoteToItem),
  ]
  return items.sort((a, b) => {
    const ta = a.recordedAt ? new Date(a.recordedAt).getTime() : 0
    const tb = b.recordedAt ? new Date(b.recordedAt).getTime() : 0
    return ta - tb
  })
}
