/**
 * 西医诊断条目编辑器（inquiry/WesternDiagnosisEditor.tsx，2026-08-21 阶段1b）
 *
 * 病案首页质控落地：主要诊断选择错误是法定单项否决（扣10分）且直接决定
 * DRG 医保拨付——诊断从单文本框升级为条目列表，主诊断显式勾选、
 * 住院场景逐条标注"入院病情"（首页必填项，此前无落点）。
 *
 * 数据流：直接读写 diagnosisEntriesStore 的西医条目（不走 antd Form 字段）；
 * 保存问诊时由 composeDiagnosisItems 与中医文本字段合成完整列表 PUT 后端。
 * 中医疾病/证候仍是单条文本输入（各至多一条），不在本组件内。
 */
import { Button, Radio, Select, Tooltip } from 'antd'
import DiagnosisCodeInput from './DiagnosisCodeInput'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  useDiagnosisEntriesStore,
  selectWestern,
  type DiagnosisEntry,
} from '@/store/diagnosisEntriesStore'

/** 国家病案首页规范"入院病情"四值枚举（与后端 VALID_ADMISSION_CONDITIONS 一致） */
const ADMISSION_CONDITIONS = ['有', '临床未确定', '情况不明', '无']

interface Props {
  /** 住院场景显示逐条"入院病情"列（门急诊隐藏——首页概念仅住院有） */
  showAdmissionCondition?: boolean
  /** 表单锁定（病历已生成/已签发）时只读 */
  disabled?: boolean
}

export default function WesternDiagnosisEditor({
  showAdmissionCondition = false,
  disabled = false,
}: Props) {
  const entries = useDiagnosisEntriesStore(s => s.entries)
  const setWesternEntries = useDiagnosisEntriesStore(s => s.setWesternEntries)
  const western = selectWestern(entries)

  const update = (idx: number, patch: Partial<DiagnosisEntry>) => {
    const next = western.map((e, i) => (i === idx ? { ...e, ...patch } : e))
    setWesternEntries(next)
  }

  const setPrimary = (idx: number) => {
    // 主诊断唯一：勾选某条即取消其余（法定"主要诊断"单选语义）
    setWesternEntries(western.map((e, i) => ({ ...e, is_primary: i === idx })))
  }

  const remove = (idx: number) => {
    const removed = western[idx]
    const next = western.filter((_, i) => i !== idx)
    // 删掉的是主诊断且还有余项 → 第一条自动接任，保持"恰一主"不变量
    if (removed.is_primary && next.length > 0) next[0] = { ...next[0], is_primary: true }
    setWesternEntries(next)
  }

  const add = () => {
    setWesternEntries([
      ...western,
      {
        category: 'western',
        name: '',
        // 第一条自动为主诊断；后续追加默认"其他诊断"
        is_primary: western.length === 0,
        sort_order: western.length,
      },
    ])
  }

  return (
    <div>
      {western.map((entry, idx) => (
        <div key={idx} style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6 }}>
          <Tooltip title="主要诊断（本次医疗资源消耗最多、对健康危害最大的疾病；手术患者以手术疾病为主）">
            <Radio
              checked={entry.is_primary}
              disabled={disabled}
              onChange={() => setPrimary(idx)}
              style={{ marginRight: 0 }}
            />
          </Tooltip>
          {/* 编码联想（2026-08-21 阶段2）：选中候选自动带 ICD-10 医保码；
              手输自由文本码清空，保存时后端按名精确匹配兜底补码 */}
          <div style={{ flex: 1 }}>
            <DiagnosisCodeInput
              codeType="ICD10"
              value={entry.name}
              code={entry.code}
              disabled={disabled}
              placeholder={
                entry.is_primary ? '主要诊断，如：高血压3级（极高危）' : '其他诊断/合并症'
              }
              onChange={(name, code, codeTypeValue) =>
                update(idx, { name, code, code_type: codeTypeValue })
              }
              style={{ borderRadius: 6, fontSize: 13 }}
            />
          </div>
          {showAdmissionCondition && (
            <Select
              value={entry.admission_condition || undefined}
              disabled={disabled}
              placeholder="入院病情"
              options={ADMISSION_CONDITIONS.map(v => ({ value: v, label: v }))}
              onChange={v => update(idx, { admission_condition: v })}
              style={{ width: 104, fontSize: 12 }}
              size="small"
            />
          )}
          {!disabled && (
            <Button
              type="text"
              size="small"
              icon={<DeleteOutlined />}
              onClick={() => remove(idx)}
              style={{ color: 'var(--text-3)' }}
            />
          )}
        </div>
      ))}
      {!disabled && (
        <Button
          type="dashed"
          size="small"
          icon={<PlusOutlined />}
          onClick={add}
          style={{ fontSize: 12, width: '100%' }}
        >
          {western.length === 0 ? '添加西医诊断' : '添加其他诊断/合并症'}
        </Button>
      )}
      {western.length > 1 && (
        <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>
          ⚠️ 合并症/并发症请逐条列出不遗漏——漏填其他诊断是 DRG 分组偏差的首要原因
        </div>
      )}
    </div>
  )
}
