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
