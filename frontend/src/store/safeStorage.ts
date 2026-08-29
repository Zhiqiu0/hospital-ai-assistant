/**
 * 配额安全 localStorage 包装（store/safeStorage.ts，2026-08-28 多标签页审计）
 *
 * zustand persist 的 set() 会同步执行 storage.setItem：localStorage 满
 * （QuotaExceededError）时，医生每次按键触发的 setRecordContent 都在业务
 * 调用栈里抛异常——内存已更新但持久化静默失效、控制台刷错，auto-save 的
 * markSaved 抛错还会被误判为保存失败而重复入队。
 *
 * 包一层 try/catch：写失败只告警一次并降级为"仅内存态"（刷新会丢本地缓存，
 * 但服务端 auto-save 才是数据安全的真正保障，本地 persist 只是体验加速层）。
 * 接给体积大户（病历正文/语音转写/问诊）即可，小槽写不满配额。
 */

let warned = false

export const safeLocalStorage = {
  getItem: (name: string): string | null => {
    try {
      return localStorage.getItem(name)
    } catch {
      return null
    }
  },
  setItem: (name: string, value: string): void => {
    try {
      localStorage.setItem(name, value)
    } catch {
      if (!warned) {
        warned = true
        // 不打 value（可能含病历正文/PHI），只报槽名
        console.warn(`[persist] localStorage 写入失败（可能已满），${name} 降级为仅内存态`)
      }
    }
  },
  removeItem: (name: string): void => {
    try {
      localStorage.removeItem(name)
    } catch {
      /* 删除失败无碍 */
    }
  },
}

/**
 * 尾防抖写入包装（2026-08-29 资源泄漏审计）：
 *
 * zustand persist 的写是**同步全量序列化**——recordStore 的 partialize 里
 * 正文有三份副本（recordContent/lastSavedContent/draftsByType），医生每次
 * 按键都全量 JSON.stringify + setItem，几万字病历单次写几百 KB，低配院内
 * 电脑连续录入会可感知卡顿。这里把写攒 500ms 尾防抖落盘：
 *   - getItem 读穿 pending（读到最新未落盘值，persist 水合语义不变）
 *   - pagehide 时同步 flush 全部 pending（关页签/刷新不丢最后一笔）
 * 数据安全底线不变：本地 persist 只是体验加速层，服务端 auto-save 才是
 * 真正的保障（同 safeLocalStorage 头注）。
 */
const DEBOUNCE_WRITE_MS = 500
const pendingWrites = new Map<string, string>()
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()

function flushPendingWrite(name: string): void {
  const v = pendingWrites.get(name)
  if (v === undefined) return
  pendingWrites.delete(name)
  const t = pendingTimers.get(name)
  if (t) {
    clearTimeout(t)
    pendingTimers.delete(name)
  }
  safeLocalStorage.setItem(name, v)
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    for (const name of Array.from(pendingWrites.keys())) flushPendingWrite(name)
  })
}

export const debouncedSafeLocalStorage = {
  getItem: (name: string): string | null => {
    const pending = pendingWrites.get(name)
    if (pending !== undefined) return pending
    return safeLocalStorage.getItem(name)
  },
  setItem: (name: string, value: string): void => {
    pendingWrites.set(name, value)
    const t = pendingTimers.get(name)
    if (t) clearTimeout(t)
    pendingTimers.set(
      name,
      setTimeout(() => flushPendingWrite(name), DEBOUNCE_WRITE_MS)
    )
  },
  removeItem: (name: string): void => {
    pendingWrites.delete(name)
    const t = pendingTimers.get(name)
    if (t) {
      clearTimeout(t)
      pendingTimers.delete(name)
    }
    safeLocalStorage.removeItem(name)
  },
}
