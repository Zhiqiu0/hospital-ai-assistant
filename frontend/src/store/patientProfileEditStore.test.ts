/**
 * patientProfileEditStore 单元测试
 *
 * 覆盖要点：
 *  - loadFromProfile：切换患者重置；同患者 + dirty 时不覆盖；同患者 + 不脏时同步
 *  - setField 标 dirty
 *  - mergeVoicePatch：仅合并非空 string 值，返回合并数量
 *  - mergeVoicePatch 空 patch 不改变状态
 *  - reset 清空所有
 */

import { describe, it, expect, beforeEach } from 'vitest'
import {
  usePatientProfileEditStore,
  EMPTY_PROFILE_FORM,
  profileToForm,
} from './patientProfileEditStore'

beforeEach(() => {
  usePatientProfileEditStore.getState().reset()
})

describe('patientProfileEditStore — loadFromProfile', () => {
  it('切换患者重置 form 与 dirty', () => {
    const s = usePatientProfileEditStore.getState()
    s.loadFromProfile('p1', { allergy_history: '青霉素' })
    s.setField('past_history', '高血压')
    expect(usePatientProfileEditStore.getState().isDirty).toBe(true)

    // 切换到 p2：丢弃 p1 草稿
    usePatientProfileEditStore.getState().loadFromProfile('p2', null)
    const next = usePatientProfileEditStore.getState()
    expect(next.loadedPatientId).toBe('p2')
    expect(next.form.past_history).toBe('')
    expect(next.form.allergy_history).toBe('')
    expect(next.isDirty).toBe(false)
  })

  it('同患者 + dirty 时不覆盖本地草稿', () => {
    const s = usePatientProfileEditStore.getState()
    s.loadFromProfile('p1', { allergy_history: '青霉素' })
    s.setField('allergy_history', '花粉')
    // 后端推送了新数据（如另一端同步），但本地 dirty，不应被覆盖
    usePatientProfileEditStore.getState().loadFromProfile('p1', { allergy_history: '海鲜' })
    expect(usePatientProfileEditStore.getState().form.allergy_history).toBe('花粉')
  })

  it('同患者 + 不脏时用最新 profile 同步', () => {
    const s = usePatientProfileEditStore.getState()
    s.loadFromProfile('p1', { allergy_history: '青霉素' })
    expect(usePatientProfileEditStore.getState().form.allergy_history).toBe('青霉素')
    // 后端 profile 更新（如另一端保存），本地未编辑过
    usePatientProfileEditStore.getState().loadFromProfile('p1', { allergy_history: '海鲜' })
    expect(usePatientProfileEditStore.getState().form.allergy_history).toBe('海鲜')
  })
})

describe('patientProfileEditStore — mergeVoicePatch', () => {
  it('合并语音 patch 中的 profile 字段，返回合并数量', () => {
    usePatientProfileEditStore.getState().loadFromProfile('p1', null)
    const result = usePatientProfileEditStore.getState().mergeVoicePatch({
      past_history: '颈椎病',
      allergy_history: '无过敏史',
      personal_history: '吸烟不喝酒',
      // 非 profile 字段被忽略
      chief_complaint: '头疼',
      // 空字符串被忽略
      family_history: '',
      // null/数字被忽略
      marital_history: null,
      religion_belief: 123,
    } as any)
    expect(result.mergedCount).toBe(3)
    const f = usePatientProfileEditStore.getState().form
    expect(f.past_history).toBe('颈椎病')
    expect(f.allergy_history).toBe('无过敏史')
    expect(f.personal_history).toBe('吸烟不喝酒')
    expect(f.family_history).toBe('')
    expect(usePatientProfileEditStore.getState().isDirty).toBe(true)
  })

  it('空 patch 或全无效字段：mergedCount=0 且不改变 dirty', () => {
    const result = usePatientProfileEditStore.getState().mergeVoicePatch({
      chief_complaint: '头疼',
    })
    expect(result.mergedCount).toBe(0)
    expect(usePatientProfileEditStore.getState().isDirty).toBe(false)
  })
})

describe('patientProfileEditStore — setField & reset', () => {
  it('setField 立即标 dirty', () => {
    usePatientProfileEditStore.getState().loadFromProfile('p1', null)
    usePatientProfileEditStore.getState().setField('past_history', 'X')
    expect(usePatientProfileEditStore.getState().isDirty).toBe(true)
    expect(usePatientProfileEditStore.getState().form.past_history).toBe('X')
  })

  it('reset 清空所有', () => {
    usePatientProfileEditStore.getState().loadFromProfile('p1', { past_history: 'X' })
    usePatientProfileEditStore.getState().setField('past_history', 'Y')
    usePatientProfileEditStore.getState().reset()
    const s = usePatientProfileEditStore.getState()
    expect(s.loadedPatientId).toBeNull()
    expect(s.isDirty).toBe(false)
    expect(s.form).toEqual(EMPTY_PROFILE_FORM)
  })
})

describe('profileToForm helper', () => {
  it('null/undefined 返回空表单', () => {
    expect(profileToForm(null)).toEqual(EMPTY_PROFILE_FORM)
    expect(profileToForm(undefined)).toEqual(EMPTY_PROFILE_FORM)
  })

  it('部分字段缺失补空字符串', () => {
    const form = profileToForm({ allergy_history: 'X' })
    expect(form.allergy_history).toBe('X')
    expect(form.past_history).toBe('')
    expect(form.menstrual_history).toBe('')
  })
})
