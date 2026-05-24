/**
 * validators.ts 单元测试。
 *
 * 加载 shared/identity_cases.json（与后端 pytest 同一份）驱动测试，
 * 防止前后端规则漂移：同一个号码后端 strict 通过，前端也必须 strict 通过。
 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  idCardRule,
  normalizeIdCard,
  normalizePhone,
  phoneRule,
  validateIdCard,
  validatePhone,
} from './validators'

// 仓库根 shared/identity_cases.json 与后端 pytest 同一份 fixture
const FIXTURE_PATH = path.resolve(__dirname, '../../../shared/identity_cases.json')
const cases = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8')) as {
  id_card: {
    valid_strict: string[]
    invalid_checksum: string[]
    invalid_format: string[]
    invalid_birth_date: string[]
    normalize: Array<{ input: string; expected: string | null }>
  }
  phone: {
    valid: string[]
    invalid: string[]
    normalize: Array<{ input: string; expected: string | null }>
  }
}

// ── 身份证：strict 模式合法用例 ───────────────────────────────────────────

describe('validateIdCard - strict 合法用例', () => {
  it.each(cases.id_card.valid_strict)('合法身份证 %s 通过校验', value => {
    const r = validateIdCard(value, 'strict')
    expect(r.ok).toBe(true)
    expect(r.value).toBe(value)
  })
})

// ── 身份证：校验码错误（strict 拒绝、lenient 通过）─────────────────────────

describe('validateIdCard - 校验码错误', () => {
  it.each(cases.id_card.invalid_checksum)('strict 拒绝校验码错的 %s', value => {
    const r = validateIdCard(value, 'strict')
    expect(r.ok).toBe(false)
    expect(r.message).toContain('校验码')
  })

  it.each(cases.id_card.invalid_checksum)('lenient 接受校验码错的 %s', value => {
    const r = validateIdCard(value, 'lenient')
    expect(r.ok).toBe(true)
  })
})

// ── 身份证：格式错误 ────────────────────────────────────────────────────

describe('validateIdCard - 格式错误', () => {
  it.each(cases.id_card.invalid_format)('任何模式都拒绝格式错误的 %s', value => {
    expect(validateIdCard(value, 'strict').ok).toBe(false)
    expect(validateIdCard(value, 'lenient').ok).toBe(false)
  })
})

// ── 身份证：出生日期非法 ────────────────────────────────────────────────

describe('validateIdCard - 出生日期非法', () => {
  it.each(cases.id_card.invalid_birth_date)('拒绝出生日期非法的 %s', value => {
    const r = validateIdCard(value, 'strict')
    expect(r.ok).toBe(false)
    expect(r.message).toContain('出生日期')
  })
})

// ── normalize 行为 ──────────────────────────────────────────────────────

describe('normalizeIdCard', () => {
  it.each(cases.id_card.normalize)('输入 $input → 标准化为 $expected', ({ input, expected }) => {
    expect(normalizeIdCard(input)).toBe(expected)
  })

  it('null 与 undefined 都归一为 null', () => {
    expect(normalizeIdCard(null)).toBeNull()
    expect(normalizeIdCard(undefined)).toBeNull()
  })
})

// ── 手机号 ─────────────────────────────────────────────────────────────

describe('validatePhone - 合法用例', () => {
  it.each(cases.phone.valid)('合法手机号 %s 通过校验', value => {
    const r = validatePhone(value)
    expect(r.ok).toBe(true)
    expect(r.value).toBe(value)
  })
})

describe('validatePhone - 非法用例', () => {
  it.each(cases.phone.invalid)('非法手机号 %s 被拒绝', value => {
    const r = validatePhone(value)
    expect(r.ok).toBe(false)
  })
})

describe('normalizePhone', () => {
  it.each(cases.phone.normalize)('输入 $input → 标准化为 $expected', ({ input, expected }) => {
    expect(normalizePhone(input)).toBe(expected)
  })

  it('null 与 undefined 都归一为 null', () => {
    expect(normalizePhone(null)).toBeNull()
    expect(normalizePhone(undefined)).toBeNull()
  })
})

// ── AntD Form rule 工厂 ─────────────────────────────────────────────────

describe('idCardRule / phoneRule', () => {
  it('idCardRule 空值且非必填时通过', async () => {
    const rule = idCardRule()
    await expect(rule.validator(null, '')).resolves.toBeUndefined()
    await expect(rule.validator(null, null)).resolves.toBeUndefined()
  })

  it('idCardRule 必填空值时报错', async () => {
    const rule = idCardRule({ required: true })
    await expect(rule.validator(null, '')).rejects.toThrow('请输入身份证号')
  })

  it('idCardRule 合法值通过', async () => {
    const rule = idCardRule()
    await expect(rule.validator(null, '11010519491231002X')).resolves.toBeUndefined()
  })

  it('idCardRule 校验码错时报错', async () => {
    const rule = idCardRule()
    await expect(rule.validator(null, '110105194912310020')).rejects.toThrow('校验码')
  })

  it('phoneRule 必填且空值时报错', async () => {
    const rule = phoneRule({ required: true })
    await expect(rule.validator(null, '')).rejects.toThrow('请输入手机号')
  })

  it('phoneRule 合法值通过', async () => {
    const rule = phoneRule()
    await expect(rule.validator(null, '13800138000')).resolves.toBeUndefined()
  })

  it('phoneRule 非法值报错', async () => {
    const rule = phoneRule()
    await expect(rule.validator(null, '12345')).rejects.toThrow('手机号格式错误')
  })
})
