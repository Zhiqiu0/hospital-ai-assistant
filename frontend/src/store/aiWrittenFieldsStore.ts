/**
 * AI 写入未确认字段追踪 store（store/aiWrittenFieldsStore.ts）
 *
 * 职责：
 *   记录"AI 写入到病历正文但医生还没看过/改过"的字段名集合。
 *   逐条修复 / 批量补全成功写入时调 addField，
 *   医生点击对应行 / 修改该行 / 撤回时调 removeField。
 *
 * 设计哲学（2026-05-24 治本）：
 *   逐条修复 + 批量补全共享同一状态池——"写入操作"统一、"确认条件"统一、
 *   UI 表现统一（顶部 chip + 侧边 gutter + 签发前弹窗都读这个 store）。
 *   逐条和批量没有特殊逻辑分支，只是 add 的 N 不同（N=1 vs N=多）。
 *
 *   消失条件三选一：
 *     a. 医生点击该行（光标落入）
 *     b. 医生改了该行任意字符
 *     c. 医生点逐条 issue 的"撤回"按钮（写入回滚 → 高亮回滚）
 *
 *   如果直到签发都没满足任一消失条件 → 高亮持续显示 + 签发前弹窗强提示。
 *
 * 数据形态：
 *   按"接诊维度"隔离——切换患者/接诊时 clear，避免上一个接诊的高亮残留。
 *   字段名用中文键（如 "舌象" / "中医诊断"），与后端 target_field /
 *   前端 FIELD_TO_LINE_PREFIX 对齐。
 *
 * 不挂 persist：
 *   高亮是"会话级"提示，刷新页面后清掉合理——医生回来再看病历正文本身
 *   即可，没有数据丢失风险。挂 persist 会让"刷新后还有高亮"反而困扰
 *   （医生以为是新写入的）。
 */
import { create } from 'zustand'

interface AiWrittenFieldsState {
  /** 当前接诊中 AI 写入但未确认的字段名集合（用 Set 语义但底层数组便于序列化） */
  fields: string[]

  /** 批量添加（去重，order 保留首次插入位置） */
  addFields: (names: string[]) => void
  /** 单个移除（点击/编辑/撤回时调） */
  removeField: (name: string) => void
  /** 整体清空（切接诊 / 签发完成时调） */
  clear: () => void
  /** 查询某字段是否被标记 */
  hasField: (name: string) => boolean
}

export const useAiWrittenFieldsStore = create<AiWrittenFieldsState>((set, get) => ({
  fields: [],

  addFields: names => {
    if (!names || names.length === 0) return
    set(state => {
      const existing = new Set(state.fields)
      const merged = [...state.fields]
      for (const name of names) {
        const trimmed = (name || '').trim()
        if (trimmed && !existing.has(trimmed)) {
          existing.add(trimmed)
          merged.push(trimmed)
        }
      }
      // 数量没变 → 不触发 re-render
      return merged.length === state.fields.length ? state : { fields: merged }
    })
  },

  removeField: name => {
    const trimmed = (name || '').trim()
    if (!trimmed) return
    set(state => {
      if (!state.fields.includes(trimmed)) return state
      return { fields: state.fields.filter(f => f !== trimmed) }
    })
  },

  clear: () => {
    set(state => (state.fields.length === 0 ? state : { fields: [] }))
  },

  hasField: name => {
    const trimmed = (name || '').trim()
    if (!trimmed) return false
    return get().fields.includes(trimmed)
  },
}))
