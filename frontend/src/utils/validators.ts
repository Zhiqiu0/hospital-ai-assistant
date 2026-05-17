/**
 * 患者身份信息字段校验（utils/validators.ts）
 *
 * 与后端 backend/app/core/validators/identity.py 一一对应的 TS 实现：
 *   - 同一份 shared/identity_cases.json 同时被后端 pytest 与前端 vitest 加载，
 *     用同一组用例驱动两端测试，确保规则一致。
 *   - normalize + validate 双阶段：先标准化（去空白连字符、末位 X 大写），再校验。
 *   - 空值三态（null / undefined / "   "）统一归一成 null，与后端一致。
 *
 * 设计原则与后端相同：本文件是前端的"单一权威"，所有表单（admin/门诊/住院）
 * 通过 idCardRule() / phoneRule() 工厂函数引入 AntD Form rules，不允许在
 * 各表单里自己抄正则。
 */

// GB 11643-1999 加权因子（17 位身份证从左到右每位的权重）
const ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2] as const
// 加权和 mod 11 → 校验码字符的映射表（index 即余数 0..10）
const ID_CARD_CHECKSUM_MAP = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2'] as const

// 身份证基础格式：18 位，前 17 位数字，末位数字或大写 X
const ID_CARD_FORMAT_RE = /^\d{17}[\dX]$/
// 中国大陆手机号：1 开头 + 第二位 3-9 + 后 9 位数字
const PHONE_RE = /^1[3-9]\d{9}$/

export type ValidateMode = 'strict' | 'lenient'

// ── 标准化函数 ────────────────────────────────────────────────────────────

/** 身份证标准化：去除空白与连字符，末位 x → X，空值三态归一为 null。 */
export function normalizeIdCard(value: string | null | undefined): string | null {
  if (value == null) return null
  if (typeof value !== 'string') return value
  // 去除所有空白字符与连字符（用户从 Excel 复制粘贴常带这些）
  const cleaned = value.replace(/[\s-]/g, '')
  if (!cleaned) return null
  // 末位 x 大写化（GB 11643 规定校验码若为 10 写作 X，大小写都常见）
  if (cleaned.endsWith('x') || cleaned.endsWith('X')) {
    return cleaned.slice(0, -1) + 'X'
  }
  return cleaned
}

/** 手机号标准化：去除所有非数字字符，剥离 +86 国家码，空值归一。 */
export function normalizePhone(value: string | null | undefined): string | null {
  if (value == null) return null
  if (typeof value !== 'string') return value
  // 去除所有非数字字符（空格、连字符、括号、+ 号等）
  let cleaned = value.replace(/\D/g, '')
  if (!cleaned) return null
  // 剥离国家码 86
  if (cleaned.startsWith('86') && cleaned.length === 13) {
    cleaned = cleaned.slice(2)
  }
  return cleaned
}

// ── 校验函数 ────────────────────────────────────────────────────────────

function computeIdCardChecksum(first17: string): string {
  let total = 0
  for (let i = 0; i < 17; i++) {
    total += parseInt(first17[i], 10) * ID_CARD_WEIGHTS[i]
  }
  return ID_CARD_CHECKSUM_MAP[total % 11]
}

export interface ValidationResult {
  ok: boolean
  /** 校验通过时的标准化值（与后端落库值一致） */
  value?: string | null
  /** 校验失败时的中文错误信息 */
  message?: string
}

/**
 * 身份证号校验。返回结构化结果而非抛异常，方便 AntD Form rule 包装。
 *
 * @param value 用户输入的原始字符串（内部会先 normalize）
 * @param mode strict（推荐默认，跑 GB 11643 校验码）/ lenient（仅查格式）
 */
export function validateIdCard(
  value: string | null | undefined,
  mode: ValidateMode = 'strict',
): ValidationResult {
  const normalized = normalizeIdCard(value)
  if (normalized == null) return { ok: true, value: null }
  if (!ID_CARD_FORMAT_RE.test(normalized)) {
    return { ok: false, message: '身份证号格式错误：应为 18 位（17 位数字 + 1 位数字或 X）' }
  }
  // 第 7-14 位（索引 6-13）是出生日期 YYYYMMDD
  const year = parseInt(normalized.slice(6, 10), 10)
  const month = parseInt(normalized.slice(10, 12), 10)
  const day = parseInt(normalized.slice(12, 14), 10)
  // year 下限 1880 是医疗档案合理上界（长寿患者场景），上限 2099 留余量
  if (
    !(year >= 1880 && year <= 2099 && month >= 1 && month <= 12 && day >= 1 && day <= 31)
  ) {
    return {
      ok: false,
      message: `身份证号内含出生日期不合法：${normalized.slice(6, 14)}`,
    }
  }
  if (mode === 'strict') {
    const expected = computeIdCardChecksum(normalized.slice(0, 17))
    if (normalized[17] !== expected) {
      return { ok: false, message: '身份证号校验码错误（GB 11643-1999），请检查是否输错' }
    }
  }
  return { ok: true, value: normalized }
}

/** 中国大陆手机号校验。返回结构化结果。 */
export function validatePhone(value: string | null | undefined): ValidationResult {
  const normalized = normalizePhone(value)
  if (normalized == null) return { ok: true, value: null }
  if (!PHONE_RE.test(normalized)) {
    return { ok: false, message: '手机号格式错误：应为 11 位、以 1[3-9] 开头的中国大陆手机号' }
  }
  return { ok: true, value: normalized }
}

// ── AntD Form rules 工厂 ─────────────────────────────────────────────────

/** AntD Form rule 类型最小子集（避免依赖 antd 类型导出，让本文件可独立测试）。 */
interface AntdRule {
  validator: (_: unknown, value: unknown) => Promise<void>
}

/**
 * AntD Form 身份证校验规则工厂。
 *
 * 用法：rules={[idCardRule()]} 或 rules={[idCardRule({ required: true })]}
 *   - required=true：空值会报"请输入身份证号"
 *   - required=false（默认）：空值放行，由 Pydantic 选填语义统一处理
 */
export function idCardRule(opts: { required?: boolean; mode?: ValidateMode } = {}): AntdRule {
  const { required = false, mode = 'strict' } = opts
  return {
    validator: async (_: unknown, value: unknown) => {
      if (value == null || value === '') {
        if (required) throw new Error('请输入身份证号')
        return
      }
      if (typeof value !== 'string') throw new Error('身份证号必须是字符串')
      const result = validateIdCard(value, mode)
      if (!result.ok) throw new Error(result.message)
    },
  }
}

/** AntD Form 手机号校验规则工厂。required 控制是否必填。 */
export function phoneRule(opts: { required?: boolean } = {}): AntdRule {
  const { required = false } = opts
  return {
    validator: async (_: unknown, value: unknown) => {
      if (value == null || value === '') {
        if (required) throw new Error('请输入手机号')
        return
      }
      if (typeof value !== 'string') throw new Error('手机号必须是字符串')
      const result = validatePhone(value)
      if (!result.ok) throw new Error(result.message)
    },
  }
}
