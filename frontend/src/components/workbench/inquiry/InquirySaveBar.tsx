/**
 * 问诊面板底栏：保存按钮 + 转住院按钮（components/workbench/inquiry/InquirySaveBar.tsx）
 *
 * 状态优先级（任一脏即"待保存"）：
 *   anyDirty=true                → 蓝色"保存（含未提交：档案/问诊/全部）"
 *   !anyDirty + hasSavedInquiry  → 绿色"已保存"
 *   !anyDirty + !hasSavedInquiry → 灰色"尚未填写"（disabled）
 *
 * 注：profile 单独保存过不算"已保存"，因为问诊是这块面板的主任务。
 */
import { Button, Modal, Tooltip } from 'antd'
import { SaveOutlined, CheckOutlined, MedicineBoxOutlined } from '@ant-design/icons'

interface InquirySaveBarProps {
  isInputLocked: boolean
  isPolishing: boolean
  isDirty: boolean
  hasSavedInquiry: boolean
  profileDirty: boolean
  profileSaving: boolean
  saving: boolean
  saveAll: () => void
  handleAdmitToInpatient: () => void
  /** 存在未签发的病历草稿时禁止转住院（A 方案，强制先签发） */
  hasUnsignedRecord: boolean
}

export default function InquirySaveBar({
  isInputLocked,
  isPolishing,
  isDirty,
  hasSavedInquiry,
  profileDirty,
  profileSaving,
  saving,
  saveAll,
  handleAdmitToInpatient,
  hasUnsignedRecord,
}: InquirySaveBarProps) {
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

  // 转住院按钮的二次确认（门诊/急诊都显示；住院工作台不渲染 InquiryPanel，不会错触发）
  const confirmAdmit = () => {
    Modal.confirm({
      title: '转入住院',
      content: '确认将当前患者转入住院？已填的问诊信息和已签发的病历会作为入院参考带入。',
      okText: '确认转住院',
      cancelText: '取消',
      onOk: () => handleAdmitToInpatient(),
    })
  }

  return (
    <div
      style={{
        padding: '10px 16px',
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {/* 转住院按钮：低频但关键，二级样式，左侧放置，避免抢主 CTA。
            A 方案（强制先签发）：有未签发病历草稿时禁用，要求医生先签发门诊
            病历再转住院，避免悬空草稿污染待办列表 / 责任界限模糊。
            润色中也禁用，避免打断流式调用。
            待医生测试反馈后再评估是否放宽（如改为弹窗二选一）。 */}
        <Tooltip title={hasUnsignedRecord ? '请先签发当前门诊病历后再转住院，避免悬空草稿' : ''}>
          <Button
            size="middle"
            icon={<MedicineBoxOutlined />}
            onClick={confirmAdmit}
            disabled={isPolishing || hasUnsignedRecord}
            style={{
              borderRadius: 8,
              height: 36,
              fontWeight: 500,
              color: '#059669',
              borderColor: '#bbf7d0',
              background: 'var(--surface)',
              flexShrink: 0,
            }}
          >
            转住院
          </Button>
        </Tooltip>
        {/* 锁定状态（病历草稿已生成）→ 保存按钮换成绿色状态行，提示后续走语音「插入病历」
            病历草稿本身有 quick_save 自动落库，不需要再有手动保存按钮。
            转住院按钮仍保留在左侧，门诊场景下医生仍可能在草稿生成后选择转住院。 */}
        {isInputLocked ? (
          <div
            style={{
              flex: 1,
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
              minHeight: 36,
            }}
          >
            <CheckOutlined style={{ color: '#22c55e', flexShrink: 0 }} />
            <span>
              病历草稿已生成并自动保存。可继续录音补录，AI 整理后点「插入病历」即可写入对应章节。
            </span>
          </div>
        ) : (
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
        )}
      </div>
    </div>
  )
}
