/**
 * 住院时间轴构建回归测试（2026-08-14 第八轮审计）
 *
 * 审计员用后端真实返回形状实跑出三个连在一起的问题：
 *   ① 后端 _serialize_record 的主键字段叫 record_id，前端读的是 r.id
 *      → 所有病历条目 id 恒为空串，而 InpatientTimeline 用它做 React key
 *      （全部重复）和 selectedId 比对 → 点任意一份病历，全部病历同时高亮
 *   ② getNoteRule 只认 ProgressNote 那套 key，MedicalRecord 的 record_type
 *      全部 miss → 兜底把原始英文 key 当中文标签返回
 *      → 时间轴上直接显示 "course_record" 给医生看
 *   ③ recordedAt 取 submitted_at || created_at，而后端压根不返回 created_at
 *      → 未签发草稿 recordedAt 为空串，排序按 0 处理
 *      → 草稿一律排到入院记录之前的最顶端且不显示日期
 */
import { describe, expect, it } from 'vitest'

import { buildTimeline, type MedicalRecordRaw, type ProgressNoteRaw } from './timelineBuilder'

/** 后端 _serialize_record 的真实形状 */
const records: MedicalRecordRaw[] = [
  {
    record_id: 'rec-admission',
    record_type: 'admission_note',
    status: 'submitted',
    submitted_at: '2026-08-01T09:00:00',
    created_at: '2026-08-01T08:30:00',
    content: '入院记录正文',
  },
  {
    record_id: 'rec-course-1',
    record_type: 'course_record',
    record_no: 1,
    status: 'submitted',
    submitted_at: '2026-08-02T10:00:00',
    created_at: '2026-08-02T09:00:00',
    content: '第一天病程',
  },
  {
    record_id: 'rec-discharge',
    record_type: 'discharge_record',
    status: 'editing',
    submitted_at: null,
    created_at: '2026-08-30T15:00:00',
    content: '出院记录草稿',
  },
]

const notes: ProgressNoteRaw[] = [
  {
    id: 'note-1',
    note_type: 'daily_course',
    status: 'submitted',
    recorded_at: '2026-08-03T10:00:00',
    content: '第二天病程',
  },
]

describe('buildTimeline', () => {
  it('每个条目都有唯一 id（否则时间轴点一个全高亮）', () => {
    const items = buildTimeline(records, notes)
    const ids = items.map(i => i.id)

    expect(ids).toHaveLength(4)
    expect(ids.every(id => id !== '')).toBe(true)
    expect(new Set(ids).size).toBe(4)
  })

  it('病历类型显示中文标签，不是英文 key', () => {
    const items = buildTimeline(records, [])
    const labels = items.map(i => i.label)

    expect(labels).toContain('入院记录')
    expect(labels).toContain('日常病程')
    expect(labels).toContain('出院记录')
    // 任何一个还是原始 key 就说明映射缺了
    expect(labels.some(l => /^[a-z_]+$/.test(l))).toBe(false)
  })

  it('未签发草稿按创建时间排，不会窜到最顶端', () => {
    const items = buildTimeline(records, notes)

    // 入院记录（8/1）必须在最前，出院草稿（8/30 创建）在最后
    expect(items[0].id).toBe('rec-admission')
    expect(items[items.length - 1].id).toBe('rec-discharge')
  })

  it('草稿条目有可显示的时间，不是空串', () => {
    const items = buildTimeline(records, [])
    const draft = items.find(i => i.id === 'rec-discharge')

    expect(draft?.recordedAt).toBeTruthy()
  })

  it('兼容只有 id 没有 record_id 的本地构造条目', () => {
    const items = buildTimeline(
      [{ id: 'local-1', record_type: 'admission_note', submitted_at: '2026-08-01T09:00:00' }],
      []
    )
    expect(items[0].id).toBe('local-1')
  })
})
