/**
 * 诊断编码联想输入框（inquiry/DiagnosisCodeInput.tsx，2026-08-21 阶段2）
 *
 * AutoComplete 封装：按名称/拼音首字母/编码前缀远程联想医保 2.0 字典
 * （ICD-10 / 中医病证 GB/T 15657-2021），选中同时带回编码；也允许自由
 * 文本输入（字典没有的罕见诊断），此时编码留空、保存时后端再做名称
 * 精确匹配兜底补码。
 *
 * 手输改动会清掉已选编码（名称变了编码即失效——宁可无码不可错码）。
 */
import { useRef, useState } from 'react'
import { AutoComplete } from 'antd'
import api from '@/services/api'

export interface CodeOption {
  code: string
  name: string
  code_type: string
}

interface Props {
  /** 字典类型：ICD10 / TCD_DIS / TCD_SYN（ICD9CM3 供后续手术模块） */
  codeType: 'ICD10' | 'TCD_DIS' | 'TCD_SYN' | 'ICD9CM3'
  value: string
  disabled?: boolean
  placeholder?: string
  /** 当前已选编码（展示在候选高亮/回显用，可空） */
  code?: string | null
  /** 值变化：手输 → code=null；选中候选 → 带 code */
  onChange: (name: string, code: string | null, codeTypeValue: string | null) => void
  style?: React.CSSProperties
  size?: 'small' | 'middle'
}

export default function DiagnosisCodeInput({
  codeType,
  value,
  disabled,
  placeholder,
  code,
  onChange,
  style,
  size,
}: Props) {
  const [options, setOptions] = useState<
    { value: string; label: React.ReactNode; item: CodeOption }[]
  >([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 迟到响应守卫：快速连续输入时旧请求后到不覆盖新候选
  const seqRef = useRef(0)

  const doSearch = (term: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!term.trim()) {
      setOptions([])
      return
    }
    const seq = ++seqRef.current
    debounceRef.current = setTimeout(async () => {
      try {
        const res = (await api.get(
          `/diagnosis-codes/search?q=${encodeURIComponent(term.trim())}&code_type=${codeType}&limit=12`
        )) as unknown as CodeOption[]
        if (seq !== seqRef.current) return
        setOptions(
          (res || []).map(item => ({
            value: item.name,
            item,
            label: (
              <span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{item.name}</span>
                <span style={{ color: 'var(--text-4)', fontSize: 11, fontFamily: 'monospace' }}>
                  {item.code}
                </span>
              </span>
            ),
          }))
        )
      } catch {
        /* 检索失败静默——仍可自由输入 */
      }
    }, 250)
  }

  return (
    <AutoComplete
      value={value}
      disabled={disabled}
      options={options}
      style={{ width: '100%', ...style }}
      size={size}
      placeholder={placeholder}
      onSearch={term => {
        // 手输：编码失效清空（名称变了码即不可信）
        onChange(term, null, null)
        doSearch(term)
      }}
      onSelect={(_v, option) => {
        const item = (option as { item: CodeOption }).item
        onChange(item.name, item.code, item.code_type)
      }}
      // 已配码时输入框右侧微标提示（title 提示完整编码）
      suffixIcon={
        code ? (
          <span title={`已配码 ${code}`} style={{ fontSize: 10, color: '#16a34a' }}>
            ✓码
          </span>
        ) : undefined
      }
    />
  )
}

/**
 * antd Form 兼容包装（中医病/证输入框用）：Form 注入 value/onChange(string)，
 * 联想选中只回填规范名称——编码由保存时后端按名称精确匹配补
 * （中医国标名标准化程度高，精确匹配命中率足够；前端不必再存一份码）。
 */
export function FormDiagnosisNameInput({
  codeType,
  value,
  onChange,
  disabled,
  placeholder,
  style,
}: {
  codeType: 'ICD10' | 'TCD_DIS' | 'TCD_SYN'
  value?: string
  onChange?: (v: string) => void
  disabled?: boolean
  placeholder?: string
  style?: React.CSSProperties
}) {
  return (
    <DiagnosisCodeInput
      codeType={codeType}
      value={value || ''}
      disabled={disabled}
      placeholder={placeholder}
      style={style}
      onChange={name => onChange?.(name)}
    />
  )
}
