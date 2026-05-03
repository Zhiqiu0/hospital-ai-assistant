/**
 * 病历 auto-save 强制 flush 触发器（store/recordAutoSaveTrigger.ts）
 *
 * 解决问题：
 *   useAutoSaveDraft 走 5 秒防抖落盘 record——医生在编辑器手输 5 秒不动才存。
 *   但 ExamSuggestionTab 的「写入/已写入」按钮 setRecordContent 后用户立即
 *   刷新，5 秒防抖来不及触发 → 后端 record 没更新 → snapshot 拉回旧值
 *   覆盖前端章节内容 → 病历章节里的「已写入项」消失（用户报告 bug）。
 *
 * 设计取舍：
 *   - 不让 ExamSuggestionTab 直接 PUT auto-save-draft：
 *     useAutoSaveDraft 内部维护 lastUpdatedAtRef 做乐观锁；外部直接 PUT
 *     绕过它，会导致下一次 5s 防抖触发时带 stale updated_at → 后端 409 →
 *     toast 误报"病历已被其他设备修改"。
 *   - 改用全局信号触发 useAutoSaveDraft 自身立即 flush：
 *     ref 状态都在 hook 内部维护，乐观锁保持完整，无副作用。
 *
 * 用法：
 *   - ExamSuggestionTab 等需要"立即落盘 record"的场景：
 *       useRecordAutoSaveTrigger.getState().triggerFlush()
 *   - useAutoSaveDraft：监听 forceFlushSignal 变化 → 清防抖 + 立即 performSave
 */

import { create } from 'zustand'

interface State {
  /** 单调递增的信号；外部递增即触发 useAutoSaveDraft 立即落盘当前 recordContent */
  forceFlushSignal: number
  triggerFlush: () => void
}

export const useRecordAutoSaveTrigger = create<State>(set => ({
  forceFlushSignal: 0,
  triggerFlush: () => set(s => ({ forceFlushSignal: s.forceFlushSignal + 1 })),
}))
