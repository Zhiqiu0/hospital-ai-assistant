/**
 * 按文书类型拉取服务端草稿（hooks/useDraftByTypeLoader.ts）
 *
 * 解决问题（2026-08-21 第四轮走查实锤）：
 *   住院一次接诊有多份文书（入院记录/首程/日常病程…），后端草稿按
 *   (encounter, record_type) 分行存；前端切文书类型时只认本地 draftsByType
 *   会话缓存——刷新后缓存为空，切到"入院记录"看到的是空编辑器，而服务端
 *   明明存着完整草稿。医生会以为入院记录丢了，甚至重写一份把它覆盖。
 *
 * 触发条件（全部满足才拉）：
 *   - 有接诊上下文
 *   - 编辑器为空（本地 draftsByType 恢复出内容 / 医生正在写 → 本地优先）
 *   - 不在 AI 生成中（流式内容分片写入，短暂为空的瞬间不能拉）
 *
 * 拉回后同步三件事：正文 + 该文书自身的签发只读状态（setRecordType 切换时
 * 重置 isFinal，等待这里灌入真实状态——见 recordStore 第六轮注释）+
 * auto-save 乐观锁基线（拿正确 updated_at，防假 409）。
 */
import { useEffect } from 'react'
import api from '@/services/api'
import { message } from '@/services/messageBridge'
import { useRecordStore } from '@/store/recordStore'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'

interface DraftByTypeRes {
  exists: boolean
  record_id?: string
  status?: string
  content?: string
  updated_at?: string | null
  submitted_at?: string | null
}

export function useDraftByTypeLoader(encounterId: string | null, recordType: string) {
  useEffect(() => {
    if (!encounterId || !recordType) return
    const store = useRecordStore.getState()
    if (store.isGenerating) return
    // 本地已有内容时**仍然要拉**（2026-09-02 多设备实测修正）：只是不灌正文，
    // 而是把服务端那份的 updated_at 取回来当乐观锁基线。
    //
    // 原实现在这里直接 return，于是"本地有缓存内容"的那台设备根本不知道服务端
    // 版本号，它的乐观锁基线是 null，而后端对 expected_updated_at 为空的请求会
    // 跳过校验直接 UPSERT。实测复现：诊室电脑写好整份病历并保存，平板（本地缓存
    // 里只有两个字）一次自动保存就把它整份顶掉，两边都是 200，医生毫无察觉。
    // 「本地优先」是对的——不能打断正在写字的医生；但本地优先不等于不知道服务端
    // 到哪一版了。基线对齐后，那一发若撞上另一台的改动会得到 409，走既有的冲突
    // 提示 + forceOverwrite 另起一版流程，被盖内容留在历史版本里。
    const localHasContent = !!store.recordContent
    let cancelled = false
    api
      .get(
        `/medical-records/draft-by-type?encounter_id=${encodeURIComponent(encounterId)}&record_type=${encodeURIComponent(recordType)}`
      )
      .then(res => {
        if (cancelled) return
        const d = res as unknown as DraftByTypeRes | null
        if (!d?.exists || !d.content) return
        // 迟到守卫：请求在途时医生可能已切类型 / 换了接诊——丢弃
        const cur = useRecordStore.getState()
        if (cur.recordType !== recordType) return
        if (useActiveEncounterStore.getState().encounterId !== encounterId) return
        // 本地有内容（发起时就有，或请求在途时医生开始手写）：只对齐基线，
        // 绝不覆盖医生正在写的字
        if (localHasContent || cur.recordContent) {
          if (d.updated_at) {
            useRecordAutoSaveTrigger.getState().syncBaseline(d.updated_at, d.content, false)
          }
          return
        }
        cur.setRecordContent(d.content)
        cur.setFinal(d.status === 'submitted', d.submitted_at ?? null)
        cur.markSaved(d.content, Date.now())
        if (d.updated_at) {
          useRecordAutoSaveTrigger.getState().syncBaseline(d.updated_at, d.content)
        }
      })
      .catch(() => {
        // 拉取失败必须告知（2026-08-29 离线审计修复）：静默留空正是本 hook
        // 头注声明要防的事故的复活路——部署窗口/断网时切到"入院记录"拉取
        // 失败 → 编辑器空 → 医生以为没写过、重写一份 → auto-save 以空基线
        // 覆盖服务端原稿。明确提示"有稿没拉到"，医生就不会重写。
        if (cancelled) return
        if (useActiveEncounterStore.getState().encounterId !== encounterId) return
        message.warning('草稿加载失败，可能已有内容未显示——请稍后切换文书重试，不要直接重写')
      })
    return () => {
      cancelled = true
    }
  }, [encounterId, recordType])
}
