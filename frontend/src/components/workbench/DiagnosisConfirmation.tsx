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
          type={state.blocked ? 'error' : 'warning'}
          message={
            state.blocked
              ? '诊断内容无法用于医院系统回写，请先修改正文'
              : '未能识别诊断列表，请人工核查正文'
          }
          description={
            state.blocked
              ? `${error}。修改完成后重新核对，再提交。`
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
