/** 签发和修订共用的最终诊断核对区；仅允许选主诊断，名称以正文为准。 */
import { Alert, Button, Checkbox, Radio, Space, Typography } from 'antd'
import type { DiagnosisConfirmationState } from '@/hooks/useDiagnosisConfirmation'

export default function DiagnosisConfirmation({
  state,
  disabled = false,
}: {
  state: DiagnosisConfirmationState
  disabled?: boolean
}) {
  if (state.loading) return <Alert type="info" message="正在核对最终正文中的诊断…" />
  if (state.error)
    return (
      <Alert
        type="error"
        message={state.error}
        action={
          <Button onClick={state.reload} disabled={disabled}>
            重新核对
          </Button>
        }
      />
    )
  if (!state.preview) return null
  const { diagnoses, projection_error: error } = state.preview
  return (
    <div
      style={{ margin: '12px 0', padding: 12, border: '1px solid var(--border)', borderRadius: 8 }}
    >
      <Typography.Text strong>最终正文诊断核对</Typography.Text>
      {error ? (
        <Alert
          style={{ marginTop: 8 }}
          type="warning"
          message={
            state.fullTextOnly
              ? '本份病历将只向医院系统回写全文'
              : '未能识别诊断列表，请人工核查正文'
          }
          description={
            state.fullTextOnly
              ? `${error.replace(/^HIS回写失败：/, '')}。系统未能从正文中可靠拆出各项内容，签发后医院系统会收到完整的病历全文，但不含拆分字段和诊断编码。可以直接签发；如需一并回写，请按上述原因修改正文后重新核对。`
              : `${error}。本地病历仍可确认提交。`
          }
        />
      ) : diagnoses.length ? (
        <>
          <div style={{ margin: '8px 0' }}>以下诊断来自最终正文，请选择一项主诊断：</div>
          <Radio.Group
            value={state.primary}
            onChange={e => state.selectPrimary(e.target.value)}
            disabled={disabled}
          >
            <Space direction="vertical">
              {diagnoses.map((item, index) => (
                <Radio key={`${index}:${item.name}`} value={index}>
                  {item.name}
                  {item.code ? `（${item.code}）` : '（未匹配编码）'}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </>
      ) : (
        <div style={{ marginTop: 8 }}>正文未识别到诊断，请确认本次文书内容完整。</div>
      )}
      <div style={{ marginTop: 12 }}>
        <Checkbox
          checked={state.confirmed}
          disabled={disabled || !state.canConfirm}
          onChange={e => state.setConfirmed(e.target.checked)}
        >
          {diagnoses.length && !error
            ? '我已核对以上诊断及主诊断，与最终正文一致'
            : '我已人工核查正文，确认继续提交'}
        </Checkbox>
      </div>
    </div>
  )
}
