/**
 * 病历草稿失败队列（services/draftQueue.ts）
 *
 * 治本目标：
 *   编辑器 auto-save 网络失败时，不能让医生输入"消失"——存到本机
 *   IndexedDB 队列里，下次网络恢复 / 用户操作触发时一并补发。
 *
 * 设计：
 *   - IndexedDB store 名 'mediscribe_draft_queue'，按 (encounter_id, record_type)
 *     做 key——同一接诊+类型的多次失败，后写覆盖前写（auto-save 本来就是
 *     "最新内容覆盖"语义）
 *   - flushDraftQueue 由 hook 在接诊切换 / 主动重试时调用
 *
 * IDB 不可用降级：
 *   极少数场景（隐私模式 / 老浏览器）IDB 不可用 → enqueue 抛错，
 *   hook 内部捕获，仅记 warn 日志不阻断主流程
 */

const DB_NAME = 'mediscribe-drafts'
const DB_VERSION = 1
const STORE_NAME = 'queue'

export interface DraftPayload {
  encounter_id: string
  record_type: string
  content: string
  expected_updated_at: string | null
}

interface QueuedItem extends DraftPayload {
  /** 队列 key：encounter_id + ':' + record_type */
  id: string
  /** 入队时间戳，便于排查"很久前的草稿"场景 */
  enqueued_at: number
}

function makeKey(encounterId: string, recordType: string): string {
  return `${encounterId}:${recordType}`
}

/** 打开 IDB；不可用时抛 → 调用方捕获降级 */
async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('indexedDB unavailable'))
      return
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error || new Error('idb open failed'))
  })
}

/** 入队：若同 key 已存在则覆盖（auto-save 永远以最新内容为准） */
export async function enqueueDraft(payload: DraftPayload): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const item: QueuedItem = {
      ...payload,
      id: makeKey(payload.encounter_id, payload.record_type),
      enqueued_at: Date.now(),
    }
    const req = store.put(item)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('idb put failed'))
  })
}

/** 列出所有失败草稿（按入队时间倒序） */
async function listQueuedDrafts(): Promise<QueuedItem[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const store = tx.objectStore(STORE_NAME)
    const req = store.getAll()
    req.onsuccess = () => {
      const items = (req.result as QueuedItem[]) || []
      items.sort((a, b) => b.enqueued_at - a.enqueued_at)
      resolve(items)
    }
    req.onerror = () => reject(req.error || new Error('idb getAll failed'))
  })
}

/** 删除单条已成功补发的草稿 */
async function removeDraft(id: string): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const req = store.delete(id)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error || new Error('idb delete failed'))
  })
}

/**
 * 按 (encounter_id, record_type) 删除队列副本（2026-08-11 审计修复）。
 * auto-save 遇 409 乐观锁冲突时调用：该草稿基线已过时，留在队列里每次 flush 都会
 * 再次 409、无限重试并反复弹冲突提示，必须删掉。失败静默（IDB 不可用不阻断主流程）。
 */
export async function removeDraftByKey(encounterId: string, recordType: string): Promise<void> {
  try {
    await removeDraft(makeKey(encounterId, recordType))
  } catch {
    // IDB 不可用降级——忽略
  }
}

/**
 * 把队列里的所有草稿尝试补发一次。
 * sender 由调用方注入（hook 内部的 performSave）；返回 true 表示发送成功，
 * 此时从队列里删除该条；失败则保留，下次 flush 再试。
 */
// flush 互斥（2026-08-29 第八轮回归修复）：online 事件与切接诊可能同时触发
// flush，两轮并发重放同一条目会双发请求；单飞标志让后来者直接让位
// （条目还在队列里，下一次触发点会补上）。
let flushInFlight = false

export async function flushDraftQueue(
  sender: (payload: DraftPayload) => Promise<boolean>,
  options?: {
    /** 跳过该**接诊**的全部条目（2026-08-29 第九轮修正：原按接诊+类型双键
     *  跳过，但住院切换瞬间 recordStore.reset 把 recordType 归 outpatient，
     *  住院文书键必失配，防护对住院不生效。当前接诊的任何类型草稿都由
     *  编辑器的水合+防抖保存最新稿负责，按接诊整体跳过才对）：
     *  队列同键旧稿若并发重放，null 基线的旧稿后落会静默回滚新稿。 */
    skipEncounterId?: string
  }
): Promise<void> {
  if (flushInFlight) return
  flushInFlight = true
  try {
    await _flushAll(sender, options)
  } finally {
    flushInFlight = false
  }
}

async function _flushAll(
  sender: (payload: DraftPayload) => Promise<boolean>,
  options?: { skipEncounterId?: string }
): Promise<void> {
  let items: QueuedItem[]
  try {
    items = await listQueuedDrafts()
  } catch {
    // IDB 不可用降级——直接返回，不影响主流程
    return
  }
  for (const item of items) {
    if (options?.skipEncounterId && item.encounter_id === options.skipEncounterId) {
      continue
    }
    try {
      const ok = await sender({
        encounter_id: item.encounter_id,
        record_type: item.record_type,
        content: item.content,
        expected_updated_at: item.expected_updated_at,
      })
      if (ok) {
        await removeDraft(item.id)
      }
    } catch {
      // 单条失败不阻断后续条目，下次 flush 还会再试
    }
  }
}

/**
 * 清空整个离线草稿队列（2026-08-28 多标签页审计·登出清理）。
 *
 * 队列此前跨登出残留：上一位医生离线积压的病历正文（PHI）留在本机；
 * 换医生后 flush 撞后端归属校验 403 被静默丢弃——既留 PHI 又丢数据。
 * 登出即清：离线草稿本就是"同一医生稍后补传"的容错，不跨人保留。
 */
export async function clearDraftQueue(): Promise<void> {
  try {
    const db = await openDB()
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).clear()
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  } catch {
    /* IndexedDB 不可用时静默——队列本身也建不起来 */
  }
}
