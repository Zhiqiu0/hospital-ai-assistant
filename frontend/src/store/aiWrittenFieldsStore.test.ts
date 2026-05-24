/**
 * aiWrittenFieldsStore 单测（store/aiWrittenFieldsStore.test.ts）
 *
 * 行为契约：
 *   1. addFields 去重 + 保持插入顺序
 *   2. addFields 空数组 / 空字符串 / null 安全
 *   3. removeField 不存在的字段安全
 *   4. clear 后 fields 为空
 *   5. 引用稳定性——无变化时 set 必须不触发重渲染（return state）
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useAiWrittenFieldsStore } from './aiWrittenFieldsStore'

describe('aiWrittenFieldsStore', () => {
  beforeEach(() => {
    useAiWrittenFieldsStore.getState().clear()
  })

  it('addFields 去重并保持插入顺序', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象', '脉象', '舌象', '中医诊断'])
    expect(useAiWrittenFieldsStore.getState().fields).toEqual([
      '舌象',
      '脉象',
      '中医诊断',
    ])
  })

  it('addFields 空数组 / 空字符串 / 空白安全', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields([])
    store.addFields([''])
    store.addFields(['  '])
    expect(useAiWrittenFieldsStore.getState().fields).toEqual([])
  })

  it('removeField 单个移除', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象', '脉象', '中医诊断'])
    store.removeField('脉象')
    expect(useAiWrittenFieldsStore.getState().fields).toEqual([
      '舌象',
      '中医诊断',
    ])
  })

  it('removeField 不存在的字段安全', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象'])
    store.removeField('不存在')
    expect(useAiWrittenFieldsStore.getState().fields).toEqual(['舌象'])
  })

  it('hasField 判定准确', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象'])
    expect(useAiWrittenFieldsStore.getState().hasField('舌象')).toBe(true)
    expect(useAiWrittenFieldsStore.getState().hasField('脉象')).toBe(false)
    expect(useAiWrittenFieldsStore.getState().hasField('')).toBe(false)
  })

  it('clear 清空 fields', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象', '脉象'])
    store.clear()
    expect(useAiWrittenFieldsStore.getState().fields).toEqual([])
  })

  it('无变化时 set 返回原 state（引用稳定）', () => {
    const store = useAiWrittenFieldsStore.getState()
    store.addFields(['舌象'])
    const before = useAiWrittenFieldsStore.getState().fields
    store.addFields(['舌象']) // 重复添加无变化
    const after = useAiWrittenFieldsStore.getState().fields
    expect(after).toBe(before) // 引用相同
  })
})
