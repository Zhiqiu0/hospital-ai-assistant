/**
 * 病历类型注册表（domain/medical/recordTypes.ts）
 *
 * 所有可能的病历类型在这里集中注册，包含元数据（显示名称、适用场景、
 * AI prompt 路由键、QC 规则键）。
 *
 * 新增病历类型只需要在 RECORD_TYPES 里加一条，不需要改组件逻辑。
 * 组件通过 getRecordType(key) / getRecordTypesByScene(scene) 查询。
 */
import type { VisitType } from './types'

export type RecordTypeKey =
  | 'outpatient' // 门诊病历
  | 'emergency' // 急诊病历
  | 'admission_note' // 入院记录
  | 'first_course' // 首次病程记录
  | 'course_note' // 日常病程记录
  | 'senior_round' // 上级查房记录
  | 'procedure_note' // 操作记录（穿刺/内镜等）
  | 'consultation' // 会诊记录
  | 'discharge_summary' // 出院记录

export interface RecordTypeMeta {
  key: RecordTypeKey
  label: string // UI 显示名
  shortLabel?: string // 时间轴等紧凑场景
  scenes: ReadonlyArray<VisitType> // 适用场景（门诊/急诊/住院）
  /** AI prompt 路由键（后端 prompts_generation.py 查表用） */
  promptKey: string
  /** 是否每次住院最多一份（入院/出院这种）。日常病程可以每天一份 */
  singleton?: boolean
  /** 是否需要上级审核。true = 需要主治/主任签名 */
  requiresReview?: boolean
  /** 推荐写作时机（仅用于 UI 提示文字） */
  whenHint?: string
}

export const RECORD_TYPES: Record<RecordTypeKey, RecordTypeMeta> = {
  outpatient: {
    key: 'outpatient',
    label: '门诊病历',
    shortLabel: '门诊',
    scenes: ['outpatient'],
    promptKey: 'outpatient',
    singleton: true,
  },
  emergency: {
    key: 'emergency',
    label: '急诊病历',
    shortLabel: '急诊',
    scenes: ['emergency'],
    promptKey: 'emergency',
    singleton: true,
  },
  admission_note: {
    key: 'admission_note',
    label: '入院记录',
    shortLabel: '入院',
    scenes: ['inpatient'],
    promptKey: 'admission_note',
    singleton: true,
    whenHint: '入院后 24 小时内完成',
  },
  first_course: {
    key: 'first_course',
    label: '首次病程记录',
    shortLabel: '首次病程',
    scenes: ['inpatient'],
    promptKey: 'first_course_record',
    singleton: true,
    whenHint: '入院后 8 小时内完成',
  },
  course_note: {
    key: 'course_note',
    label: '日常病程记录',
    shortLabel: '日常病程',
    scenes: ['inpatient'],
    promptKey: 'course_record',
    whenHint: '至少每日一次',
  },
  senior_round: {
    key: 'senior_round',
    label: '上级查房记录',
    shortLabel: '上级查房',
    scenes: ['inpatient'],
    promptKey: 'senior_round',
    requiresReview: true,
  },
  procedure_note: {
    key: 'procedure_note',
    label: '操作记录',
    shortLabel: '操作',
    scenes: ['inpatient'],
    promptKey: 'procedure_note',
  },
  consultation: {
    key: 'consultation',
    label: '会诊记录',
    shortLabel: '会诊',
    scenes: ['inpatient'],
    promptKey: 'consultation',
  },
  discharge_summary: {
    key: 'discharge_summary',
    label: '出院记录',
    shortLabel: '出院',
    scenes: ['inpatient'],
    promptKey: 'discharge_record',
    singleton: true,
    whenHint: '办理出院时',
  },
}

/** 按 key 取元数据，未知 key 返回 undefined */
export function getRecordType(key: string): RecordTypeMeta | undefined {
  return RECORD_TYPES[key as RecordTypeKey]
}

/** 取某个场景下所有可用的病历类型 */
export function getRecordTypesByScene(scene: VisitType): RecordTypeMeta[] {
  return Object.values(RECORD_TYPES).filter(t => t.scenes.includes(scene))
}

/** 取某个类型的中文显示名（未知 key 返回 key 本身，安全降级） */
export function getRecordTypeLabel(key: string): string {
  return getRecordType(key)?.label ?? key
}
