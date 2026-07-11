/**
 * 住院问诊面板底部操作区（inpatientInquiry/InpatientInquiryFooter.tsx）
 * 从 InpatientInquiryPanel 抽出，仅负责渲染，状态由父组件通过 props 传入：
 *   - 未锁定（病历草稿空）→ 显示"保存问诊+档案"按钮
 *   - 已锁定（病历草稿已生成）→ 切换为绿色状态行，提示后续走语音「插入病历」
 * 锁定状态把按钮 disabled 改成"按钮消失"，避免医生疑惑「为什么点不了」。
 * 病历草稿本身有 quick_save 自动落库，不需要再有手动保存按钮。
 */
import { Button } from 'antd'
import { SaveOutlined, CheckOutlined } from '@ant-design/icons'

interface InpatientInquiryFooterProps {
  isInputLocked: boolean
  isDirty: boolean
  profileDirty: boolean
  saving: boolean
  profileSaving: boolean
  hasSavedInquiry: boolean
  saveAll: () => void
}

export default function InpatientInquiryFooter({
  isInputLocked,
  isDirty,
  profileDirty,
  saving,
  profileSaving,
  hasSavedInquiry,
  saveAll,
}: InpatientInquiryFooterProps) {
  return (
    <div
      style={{
        padding: '10px 16px',
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}
    >
      {isInputLocked ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 12px',
            borderRadius: 8,
            background: '#dcfce7',
            border: '1px solid #86efac',
            fontSize: 12,
            color: '#166534',
            lineHeight: 1.6,
          }}
        >
          <CheckOutlined style={{ color: '#22c55e', flexShrink: 0 }} />
          <span>
            病历草稿已生成并自动保存。可继续录音补录，AI 整理后点「插入病历」即可写入对应章节。
          </span>
        </div>
      ) : (
        (() => {
          // 与门诊 InquiryPanel 保存按钮保持完全一致的视觉/文案
          const anyDirty = isDirty || profileDirty
          const anySaving = saving || profileSaving
          let label: string
          if (anyDirty) {
            const parts: string[] = []
            if (profileDirty) parts.push('档案')
            if (isDirty) parts.push('问诊')
            label = `保存${parts.join('+')}`
          } else if (hasSavedInquiry) {
            label = '已保存'
          } else {
            label = '尚未填写问诊'
          }
          return (
            <Button
              type="primary"
              icon={anyDirty ? <SaveOutlined /> : hasSavedInquiry ? <CheckOutlined /> : undefined}
              block
              disabled={!anyDirty}
              loading={anySaving}
              onClick={saveAll}
              style={{
                borderRadius: 8,
                height: 36,
                fontWeight: 600,
                background: anyDirty
                  ? 'linear-gradient(135deg, #2563eb, #3b82f6)'
                  : hasSavedInquiry
                    ? '#86efac'
                    : '#e5e7eb',
                border: 'none',
                color: anyDirty ? 'var(--surface)' : hasSavedInquiry ? '#166534' : '#6b7280',
                transition: 'all 0.3s',
              }}
            >
              {label}
            </Button>
          )
        })()
      )}
    </div>
  )
}
