/**
 * 语音结构化结果预览区（VoiceStructurePreview.tsx）
 * 追记模式下 AI 整理完成后展示 patch 内容，医生确认后点「插入病历」写入。
 *
 * 字段展示策略（与 inquiryUtils.applyVoicePatchToRecord 写入策略对齐）：
 *   - 章节级字段（FIELD_TO_SECTION）：直接显示一行
 *   - 行级字段（FIELD_TO_LINE_PREFIX，含生命体征/望闻舌脉/专项评估）：显示并标注章节归属
 *   - 嵌套对象 vital_signs：展开为各子字段（体温/脉搏/呼吸/...）独立显示
 *   只显示对患者有实际写入意义的字段——空值、未识别字段不渲染。
 */
import { Button, Typography } from 'antd'
import { MedicineBoxOutlined } from '@ant-design/icons'
import { InquiryData } from '@/store/types'
import { FIELD_NAME_LABEL, FIELD_TO_SECTION, FIELD_TO_LINE_PREFIX } from './qcFieldMaps'

const { Text } = Typography

interface Props {
  pendingPatch: Partial<InquiryData>
  onApply: () => void
  onCancel: () => void
}

interface DisplayEntry {
  key: string
  label: string
  section: string
  value: string
}

/** vital_signs 子字段中文标签（仅展示用，写入逻辑统一到 physical_exam_vitals 整行） */
const VITAL_SIGNS_LABEL: Record<string, string> = {
  temperature: '体温',
  pulse: '脉搏',
  respiration: '呼吸',
  bp_systolic: '收缩压',
  bp_diastolic: '舒张压',
  spo2: '血氧',
  height: '身高',
  weight: '体重',
}

/** 把 patch 拍平成可展示行：识别章节字段、行级字段、嵌套 vital_signs 三类。 */
function buildDisplayEntries(patch: Partial<InquiryData>): DisplayEntry[] {
  const result: DisplayEntry[] = []
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === '') continue
    // 嵌套 vital_signs：展开每个非空子字段独立成行
    if (k === 'vital_signs' && typeof v === 'object') {
      for (const [vsKey, vsVal] of Object.entries(v as Record<string, unknown>)) {
        if (vsVal == null || vsVal === '') continue
        result.push({
          key: vsKey,
          label: VITAL_SIGNS_LABEL[vsKey] || vsKey,
          section: '【体格检查】生命体征',
          value: String(vsVal),
        })
      }
      continue
    }
    if (typeof v !== 'string') continue
    // 章节级字段优先（FIELD_TO_SECTION 中 mapped 非空才算可写入）
    const sectionMapped = FIELD_TO_SECTION[k]
    if (sectionMapped) {
      result.push({
        key: k,
        label: FIELD_NAME_LABEL[k] || k,
        section: sectionMapped,
        value: v,
      })
      continue
    }
    // 行级字段（physical_exam_vitals / 望闻舌脉 / 专项评估七项）
    const lineCfg = FIELD_TO_LINE_PREFIX[k]
    if (lineCfg) {
      result.push({
        key: k,
        label: FIELD_NAME_LABEL[k] || k,
        section: `${lineCfg.section}·${lineCfg.prefix.replace(/[:：]$/, '')}`,
        value: v,
      })
    }
  }
  return result
}

export default function VoiceStructurePreview({ pendingPatch, onApply, onCancel }: Props) {
  const entries = buildDisplayEntries(pendingPatch)
  if (!entries.length) return null

  return (
    <div
      style={{
        marginTop: 10,
        background: '#f0fdf4',
        border: '1px solid #86efac',
        borderRadius: 8,
        padding: '10px 12px',
      }}
    >
      <Text strong style={{ fontSize: 12, color: '#166534', display: 'block', marginBottom: 6 }}>
        AI 整理结果（确认后插入病历）：
      </Text>
      {entries.map(e => (
        <div key={e.key} style={{ fontSize: 12, marginBottom: 4, lineHeight: 1.5 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {e.label}（{e.section}）：
          </Text>
          <Text style={{ fontSize: 12 }}>{e.value}</Text>
        </div>
      ))}
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <Button
          type="primary"
          size="small"
          icon={<MedicineBoxOutlined />}
          onClick={onApply}
          style={{ borderRadius: 6, background: '#16a34a', borderColor: '#16a34a' }}
        >
          插入病历
        </Button>
        <Button size="small" onClick={onCancel} style={{ borderRadius: 6 }}>
          取消
        </Button>
      </div>
    </div>
  )
}
