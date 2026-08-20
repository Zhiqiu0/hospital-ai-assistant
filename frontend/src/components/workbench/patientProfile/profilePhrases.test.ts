/**
 * 常用句式追加逻辑测试（profilePhrases.ts）
 *
 * 覆盖：空值直接填 / 已有内容补逗号再接 / 末尾已有标点不重复补 / 已包含同句式不叠加 /
 * 每个配置字段的 key 都在档案字段表里（防拼错 key 导致标签永远不显示）。
 */
import { describe, it, expect } from 'vitest'
import {
  INQUIRY_PHRASES,
  PROFILE_PHRASES,
  REVISIT_HPI_PHRASES,
  appendPhrase,
} from './profilePhrases'
import { PROFILE_FIELDS } from './staleness'

describe('appendPhrase', () => {
  it('空值直接使用句式', () => {
    expect(appendPhrase('', '否认食物、药物过敏史。')).toBe('否认食物、药物过敏史。')
  })

  it('已有内容且末尾无标点时用逗号衔接', () => {
    expect(appendPhrase('高血压 5 年', '否认外伤史、手术史。')).toBe(
      '高血压 5 年，否认外伤史、手术史。'
    )
  })

  it('末尾已有标点则直接衔接，不重复补逗号', () => {
    expect(appendPhrase('高血压 5 年。', '否认外伤史、手术史。')).toBe(
      '高血压 5 年。否认外伤史、手术史。'
    )
  })

  it('已包含同一句式时不重复叠加', () => {
    const cur = '高血压 5 年，否认外伤史、手术史。'
    expect(appendPhrase(cur, '否认外伤史、手术史。')).toBe(cur)
  })
})

describe('PROFILE_PHRASES 配置', () => {
  it('每个配置的 key 都是真实档案字段', () => {
    const keys = new Set(PROFILE_FIELDS.map(f => f.key as string))
    for (const key of Object.keys(PROFILE_PHRASES)) {
      expect(keys.has(key), `句式表 key ${key} 不在 PROFILE_FIELDS 中`).toBe(true)
    }
  })

  it('句式文本非空且标签唯一', () => {
    for (const [key, list] of Object.entries(PROFILE_PHRASES)) {
      const labels = list.map(p => p.label)
      expect(new Set(labels).size, `${key} 标签重复`).toBe(labels.length)
      for (const p of list)
        expect(p.text.trim().length, `${key}/${p.label} 文本为空`).toBeGreaterThan(0)
    }
  })
})

describe('INQUIRY_PHRASES 配置', () => {
  it('现病史句式存在且文本非空、标签唯一', () => {
    const list = INQUIRY_PHRASES.history_present_illness
    expect(list.length).toBeGreaterThan(0)
    const labels = list.map(p => p.label)
    expect(new Set(labels).size).toBe(labels.length)
    for (const p of list) expect(p.text.trim().length).toBeGreaterThan(0)
  })
})

describe('REVISIT_HPI_PHRASES 配置', () => {
  it('复诊句式非空、标签唯一、含病史同前', () => {
    expect(REVISIT_HPI_PHRASES.length).toBeGreaterThan(0)
    const labels = REVISIT_HPI_PHRASES.map(p => p.label)
    expect(new Set(labels).size).toBe(labels.length)
    expect(REVISIT_HPI_PHRASES.some(p => p.text.includes('病史同前'))).toBe(true)
    for (const p of REVISIT_HPI_PHRASES) expect(p.text.trim().length).toBeGreaterThan(0)
  })
})
