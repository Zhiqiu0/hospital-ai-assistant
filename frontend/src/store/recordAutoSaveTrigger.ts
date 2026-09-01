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

/** auto-save 状态机（2026-08-29 离线审计：从 useAutoSaveDraft 移到这里定义，
 *  避免 store→hook 循环导入；hook 原样 re-export 保持旧引用不变） */
/**
 * 自动保存状态。
 * 'queued'  服务端保存失败但已暂存进 IndexedDB 队列，等待补传（内容安全）
 * 'failed'  服务端与 IndexedDB **双双失败**——内容此刻只活在本机 localStorage，
 *           关掉浏览器/换台电脑就没了。必须让医生看见（2026-09-01 可观测性审计）
 */
export type AutoSaveState = 'idle' | 'saving' | 'saved' | 'queued' | 'conflict' | 'failed'

interface State {
  /**
   * auto-save 实时状态（2026-08-29 离线审计修复）：此前 useAutoSaveDraft
   * 返回的 savingState 无任何组件消费，断网时保存失败入队，状态栏却仍显示
   * 绿色"N 分钟前保存"——医生对"内容其实只在本机队列里"毫无感知。
   * 镜像到全局 store 让 WorkbenchStatusBar 能直接读。
   */
  autoSaveState: AutoSaveState
  setAutoSaveState: (s: AutoSaveState) => void
  /** 单调递增的信号；外部递增即触发 useAutoSaveDraft 立即落盘当前 recordContent */
  forceFlushSignal: number
  triggerFlush: () => void
  /**
   * 服务端草稿基线同步（2026-08-21 第四轮走查）：
   *   AI 生成完成时后端已把全文落库（save_ai_draft），done 事件带回落库
   *   updated_at。若不同步给 useAutoSaveDraft，它的乐观锁基线仍是生成前的旧值，
   *   下一次 auto-save 必假 409（"病历已被其他设备修改"误报）。
   *   信号携带 {updatedAt, content}：hook 收到后把两个基线 ref 一起对齐。
   */
  baselineSignal: number
  /**
   * adoptContent=false 表示「只对齐乐观锁基线，不接管正文状态」——用于本地
   * 已有内容、但仍需知道服务端版本号的场景（多设备）。此时不能 markSaved：
   * 医生本地那份还没上传，状态条不该显示"已保存"。
   */
  baselinePayload: { updatedAt: string; content: string; adoptContent: boolean } | null
  syncBaseline: (updatedAt: string, content: string, adoptContent?: boolean) => void
}

export const useRecordAutoSaveTrigger = create<State>(set => ({
  autoSaveState: 'idle',
  setAutoSaveState: autoSaveState => set({ autoSaveState }),
  forceFlushSignal: 0,
  triggerFlush: () => set(s => ({ forceFlushSignal: s.forceFlushSignal + 1 })),
  baselineSignal: 0,
  baselinePayload: null,
  syncBaseline: (updatedAt, content, adoptContent = true) =>
    set(s => ({
      baselineSignal: s.baselineSignal + 1,
      baselinePayload: { updatedAt, content, adoptContent },
    })),
}))
