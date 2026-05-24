/**
 * AI 写入清单面板（components/workbench/AiWritePanel.tsx）
 *
 * 显示当前接诊中 AI 写入但医生还没确认的字段 chip 列表。
 *
 * 交互：
 *   - 点 chip 主体 → 派发 'ai-writepanel:jump' CustomEvent，RecordEditor 监听
 *      后跳转到病历正文对应行 + 闪烁 1.2s 提示。不调 removeField —— 点击 chip
 *      只是"查看"，医生需要点击病历该行 / 编辑该行才算"确认"。
 *   - 点 chip 的 × → removeField 直接从池里移除（医生明确放弃）
 *
 * 数据源：useAiWrittenFieldsStore.fields（"逐条修复 + 批量补全 + 撤回" 三种入口
 *        统一管理）
 *
 * 渲染策略：fields 空时返回 null，不占空间；非空时显示淡黄色提示横条。
 *
 * 与签发的关系：
 *   签发前 RecordEditor 会读 fields 判断是否需要弹"以下 N 处为 AI 补全，
 *   请确认"对话框。
 */
import { CloseOutlined, BulbOutlined } from '@ant-design/icons'
import { useAiWrittenFieldsStore } from '@/store/aiWrittenFieldsStore'

/** chip 跳转的 CustomEvent 名，RecordEditor 监听后调 setSelectionRange + focus */
export const AI_WRITE_JUMP_EVENT = 'ai-writepanel:jump'

export interface AiWriteJumpDetail {
  /** 要定位的字段名（与 store.fields 一致） */
  fieldName: string
}

export default function AiWritePanel() {
  const fields = useAiWrittenFieldsStore(s => s.fields)
  const removeField = useAiWrittenFieldsStore(s => s.removeField)

  if (fields.length === 0) return null

  const handleJump = (fieldName: string) => {
    const evt = new CustomEvent<AiWriteJumpDetail>(AI_WRITE_JUMP_EVENT, {
      detail: { fieldName },
    })
    window.dispatchEvent(evt)
  }

  return (
    <div
      data-testid="ai-write-panel"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: '#fffbe6', // 淡黄底，医疗场景下温和提示色
        borderTop: '1px solid #ffe58f',
        borderBottom: '1px solid #ffe58f',
        flexWrap: 'wrap',
      }}
    >
      <BulbOutlined style={{ color: '#d48806', fontSize: 14 }} />
      <span style={{ fontSize: 12, color: '#874d00', marginRight: 4 }}>
        本次 AI 补全 {fields.length} 项（点击 chip 查看，点 × 放弃；编辑该行后高亮消失）：
      </span>
      {fields.map(field => (
        <span
          key={field}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px 2px 10px',
            background: '#fff',
            border: '1px solid #ffd666',
            borderRadius: 12,
            fontSize: 12,
            color: '#874d00',
            cursor: 'default',
          }}
        >
          <span
            onClick={() => handleJump(field)}
            style={{ cursor: 'pointer' }}
            title="点击跳转到病历对应行"
          >
            {field}
          </span>
          <CloseOutlined
            onClick={() => removeField(field)}
            style={{ fontSize: 10, color: '#bfbfbf', cursor: 'pointer', padding: 2 }}
            title="放弃 AI 写入标记"
          />
        </span>
      ))}
    </div>
  )
}
