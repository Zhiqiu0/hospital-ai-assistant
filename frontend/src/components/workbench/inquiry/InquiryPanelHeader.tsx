/**
 * 问诊面板顶栏（components/workbench/inquiry/InquiryPanelHeader.tsx）
 *
 * 内容：面板标题 + 就诊类型 Tag + 初诊/复诊切换
 */
import { Radio, Tag } from 'antd'

interface InquiryPanelHeaderProps {
  isInputLocked: boolean
  isPatientReused: boolean
  isFirstVisit: boolean
  visitTypeLabel: string
  visitTypeColor: string
  visitNatureColor: string
  currentVisitType: string
  setVisitMeta: (firstVisit: boolean, visitType: string) => void
  setIsDirty: (dirty: boolean) => void
}

export default function InquiryPanelHeader({
  isInputLocked,
  isPatientReused,
  isFirstVisit,
  visitTypeLabel,
  visitTypeColor,
  visitNatureColor,
  currentVisitType,
  setVisitMeta,
  setIsDirty,
}: InquiryPanelHeaderProps) {
  return (
    <div
      style={{
        padding: '12px 16px 10px',
        borderBottom: '1px solid var(--border-subtle)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>问诊录入</div>
          <div style={{ fontSize: 11, color: 'var(--text-4)', marginTop: 1 }}>
            填写后保存，AI自动同步建议
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Tag color={visitTypeColor} style={{ margin: 0, fontSize: 11 }}>
            {visitTypeLabel}
          </Tag>
          <Radio.Group
            size="small"
            value={isFirstVisit}
            onChange={e => {
              setVisitMeta(e.target.value, currentVisitType)
              setIsDirty(true)
            }}
            optionType="button"
            buttonStyle="solid"
            disabled={isInputLocked || isPatientReused}
          >
            <Radio.Button
              value={true}
              style={{
                fontSize: 11,
                padding: '0 8px',
                height: 24,
                lineHeight: '22px',
                borderColor: visitNatureColor,
                background: isFirstVisit ? visitNatureColor : undefined,
              }}
            >
              初诊
            </Radio.Button>
            <Radio.Button
              value={false}
              style={{ fontSize: 11, padding: '0 8px', height: 24, lineHeight: '22px' }}
            >
              复诊
            </Radio.Button>
          </Radio.Group>
        </div>
      </div>
    </div>
  )
}
