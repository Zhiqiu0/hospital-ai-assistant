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
 * 把队列里的所有草稿尝试补发一次。
 * sender 由调用方注入（hook 内部的 performSave）；返回 true 表示发送成功，
 * 此时从队列里删除该条；失败则保留，下次 flush 再试。
 */
export async function flushDraftQueue(
  sender: (payload: DraftPayload) => Promise<boolean>
): Promise<void> {
  let items: QueuedItem[]
  try {
    items = await listQueuedDrafts()
  } catch {
    // IDB 不可用降级——直接返回，不影响主流程
    return
  }
  for (const item of items) {
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
