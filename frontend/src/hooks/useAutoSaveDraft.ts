/**
 * 病历编辑器 auto-save hook（hooks/useAutoSaveDraft.ts）
 *
 * 治本目标：
 *   医生在编辑器里输入到一半，浏览器崩溃 / 不小心关标签 / 网络中断 / logout 时
 *   不丢数据。每 5 秒把当前 recordContent 防抖保存到后端，后端 UPSERT 当前
 *   draft 版本（不爆版本号）。
 *
 * 行为约定：
 *   - 5 秒防抖：医生连续输入时只发最后一次的内容，不刷请求
 *   - 跳空：recordContent 空 / 跟上次保存内容一样 → 不发请求
 *   - 跳已签发：isFinal=true 时不再 auto-save（医生已签发的病历不允许覆盖）
 *   - 失败兜底：网络失败 → IndexedDB 队列存草稿，下次成功时一并补发
 *   - 乐观锁：保存成功后记录 updated_at，下次发请求带回；后端检测到不一致返 409
 *   - encounter 切换：切到新接诊时上次草稿失效，从新草稿基线开始
 *
 * 状态对外：
 *   - savedAt：最后一次成功保存时间戳，状态条显示"X 秒前已保存"
 *   - savingState：'idle' / 'saving' / 'saved' / 'queued' / 'conflict'
 *
 * 不做的事：
 *   - 不做编辑历史快照（每次只保留当前内容，历史靠版本号机制）
 *   - 不做实时协作 OT/CRDT（医生场景不需要多人同时编辑同一份病历）
 */
import { useEffect, useRef, useState } from 'react'
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useRecordStore } from '@/store/recordStore'
import { useRecordAutoSaveTrigger } from '@/store/recordAutoSaveTrigger'
import {
  enqueueDraft,
  flushDraftQueue,
  removeDraftByKey,
  type DraftPayload,
} from '@/services/draftQueue'

const DEBOUNCE_MS = 5000

// 类型移到 store 定义（避免循环导入），这里 re-export 保持旧引用不变
export type { AutoSaveState } from '@/store/recordAutoSaveTrigger'
import type { AutoSaveState } from '@/store/recordAutoSaveTrigger'

export interface UseAutoSaveDraftOptions {
  /** 当前接诊 ID，无则不启用 auto-save（首次进入工作台还没接诊上下文） */
  encounterId: string | null
  /** 病历类型（outpatient / admission_note 等），切换时 auto-save 基线重置 */
  recordType: string
  /** 当前编辑器内容（主控信号，本 hook 据此防抖触发） */
  recordContent: string
  /** 病历是否已签发——签发后只读，不再 auto-save */
  isFinal: boolean
}

export function useAutoSaveDraft({
  encounterId,
  recordType,
  recordContent,
  isFinal,
}: UseAutoSaveDraftOptions): {
  savedAt: number
  savingState: AutoSaveState
} {
  const [savedAt, setSavedAt] = useState(0)
  const [savingState, setSavingState] = useState<AutoSaveState>('idle')
  // 状态镜像到全局 store（2026-08-29 离线审计）：此前返回值没人消费，
  // 断网入队后状态栏仍显示绿色"已保存"，医生无从知道内容只在本机队列里。
  // 用 effect 声明式镜像而不是包一层 setter——包装函数每次渲染重建会破坏
  // eslint 对 performSave 的传递稳定性推断（exhaustive-deps 报 warning 挡 CI）
  useEffect(() => {
    useRecordAutoSaveTrigger.getState().setAutoSaveState(savingState)
  }, [savingState])
  // 上次成功保存的内容快照——用于"内容没变就不重发"判断
  const lastSavedContentRef = useRef<string>('')
  // 上次保存返回的 updated_at——给乐观锁带回
  const lastUpdatedAtRef = useRef<string | null>(null)
  // 防抖计时器
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 切接诊时重置基线
  const lastEncounterRef = useRef<string | null>(null)

  // 实际保存逻辑（被防抖 + 失败队列 flush 共用）
  // 必须声明在 useEffect 之前——effect 闭包里引用 performSave，
  // 后置 const 会触发 ESLint react-hooks/set-state-in-effect TDZ 报错
  const performSave = async (payload: DraftPayload): Promise<boolean> => {
    setSavingState('saving')
    try {
      // 后端 auto-save-draft 仅回 updated_at（用于乐观锁回填），形状收敛在内联接口
      const res = (await api.post('/medical-records/auto-save-draft', {
        encounter_id: payload.encounter_id,
        record_type: payload.record_type,
        content: payload.content,
        expected_updated_at: payload.expected_updated_at,
      })) as { updated_at?: string } | null
      // 基线守卫（2026-08-11 审计修复）：flush 补发的可能是「上一个接诊」的旧草稿，
      // 若无条件更新乐观锁基线，会把旧草稿的 updated_at 写进当前接诊，导致当前接诊
      // 后续保存永久 409 假冲突。仅当补发的正是当前接诊时才更新 ref/状态；否则也
      // 返回 true（让队列条目被 removeDraft 清掉），只跳过状态写入。
      if (payload.encounter_id === lastEncounterRef.current) {
        lastSavedContentRef.current = payload.content
        lastUpdatedAtRef.current = res?.updated_at ?? null
        const now = Date.now()
        setSavedAt(now)
        setSavingState('saved')
        // 同步到 recordStore，让 WorkbenchStatusBar / 其他组件能感知"已保存"状态
        // 同时记下「已落库的正文」，水合时据此判断本地是否有未保存编辑
        useRecordStore.getState().markSaved(payload.content, now)
      }
      // 成功即清同键队列残留（2026-08-29 离线审计修复）：断网时失败入队的旧稿
      // （尤其 expected=null 基线的）若不清，之后切接诊触发 flush 会以"跳过
      // 乐观锁"姿态重放，把服务端**更新的内容静默回滚成旧稿**。本次成功已
      // 覆盖同 (encounter, record_type) 的一切旧内容，队列副本必须作废。
      void removeDraftByKey(payload.encounter_id, payload.record_type)
      return true
    } catch (err) {
      // axios 错误形状收敛到本地视图：拦截器虽 reject error.response?.data，
      // 但 unknown 走 instanceof / response status 访问会触发 lint，
      // 这里直接用 inline 形状（status 通过 response 或 axios error 透出）
      const e = err as { response?: { status?: number }; status?: number }
      const status = e?.response?.status ?? e?.status
      // 409：乐观锁冲突——其他设备/标签页已经写过更新版。
      // 删掉该 (encounter, record_type) 的队列副本：其基线已过时，留着每次 flush 都会
      // 再 409、无限重试并反复弹提示。只对当前接诊弹冲突提示，避免补发旧草稿误导医生。
      if (status === 409) {
        void removeDraftByKey(payload.encounter_id, payload.record_type)
        if (payload.encounter_id === lastEncounterRef.current) {
          setSavingState('conflict')
          // 基线重置（2026-08-13 第二轮审计修复；2026-08-21 第四轮简化）：只提示
          // 不刷新基线会每 5 秒拿同一个过期 expected 反复撞 409——医生后续输入
          // 永久不落库。原实现重取 workspace.active_record.updated_at 当新基线，
          // 但 active_record 是"最近更新的那行"，住院多文书下不一定是当前正在写的
          // 类型，基线仍会错行。直接置 null 等价且永远正确：下次保存不带
          // expected → 后端跳过乐观锁校验 → 后写覆盖（医生正在写就该存下来）。
          lastUpdatedAtRef.current = null
          message.warning('病历已被其他设备修改，你的后续编辑将继续保存并覆盖')
        }
        return false
      }
      // 永久性拒绝（2026-08-13 第五轮审计修复）：403=病历已签发/无权写，
      // 404=接诊或病历已不存在。这些重试多少次都还是同样的结果，原先却和
      // 网络错误一样入失败队列——队列条目永远补发不成功，后续所有草稿都堵在
      // 它后面，医生的草稿保存链路被**永久毒化**且没有任何提示。
      // 直接清掉该条目并明确告知医生，让他知道为什么草稿不再保存。
      if (status === 403 || status === 404) {
        void removeDraftByKey(payload.encounter_id, payload.record_type)
        setSavingState('idle')
        if (payload.encounter_id === lastEncounterRef.current) {
          message.warning(
            status === 403
              ? '该病历已签发，草稿不再自动保存；如需更正请走病历修订'
              : '接诊已不存在，草稿已停止自动保存'
          )
        }
        return false
      }
      // 其他错误（网络 / 5xx）→ 入失败队列，下次成功时补发
      try {
        await enqueueDraft(payload)
        setSavingState('queued')
      } catch {
        // IndexedDB 也挂了——只能记日志，下次防抖触发还是会试

        // 只打状态与消息（2026-08-28 PHI 审计）：整个 AxiosError 展开即见
        // config.data（病历正文）与 Authorization 头，而触发场景（弱网）正是
        // 医生最可能截 F12 发群求助的时刻
        console.warn(
          'autosave: enqueue failed',
          (err as { status?: number })?.status ?? '',
          (err as { message?: string })?.message ?? ''
        )
      }
      return false
    }
  }

  // ── 立即落盘当前待保存内容（2026-08-14 第七轮审计 #32）─────────────────────
  //
  // 原先只有 5 秒尾防抖这一条路：医生敲完最后一个字的 5 秒内，只要
  // 切患者 / 退出登录 / 关标签页，这段内容就**从未被发出去过**——
  // 连失败队列都进不去（入队发生在 performSave 失败时，而它压根没被调用）。
  // 查房时一个患者写完直接点下一个是常态，5 秒窗口天天都在踩。
  //
  // 用 ref 存快照而非闭包：切接诊时 encounterId 已经变成新的了，
  // 必须把**上一个接诊**的内容存到**上一个接诊**的 id 上。
  const pendingRef = useRef<DraftPayload | null>(null)
  const flushPending = () => {
    const pending = pendingRef.current
    pendingRef.current = null
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    if (!pending) return
    if (pending.content === lastSavedContentRef.current) return
    // 失败时 performSave 内部会入 IndexedDB 队列，下次挂载时补发
    void performSave(pending)
  }

  // 接诊切换：先把上一份草稿落盘，再重置所有内部状态
  useEffect(() => {
    if (encounterId !== lastEncounterRef.current) {
      flushPending() // ← 必须在下面重置基线之前
      lastEncounterRef.current = encounterId
      lastSavedContentRef.current = ''
      lastUpdatedAtRef.current = null
      setSavedAt(0)
      setSavingState('idle')
      // 顺便尝试把上次会话堆积的失败队列发出去（网络刚恢复 / 重新登录场景）。
      // 跳过刚切到的当前键：该接诊内容随后由水合+防抖保存最新稿（同 onOnline 口径）
      void flushDraftQueue(performSave, {
        skipEncounterId: encounterId ?? undefined,
        skipRecordType: recordType,
      })
    }
    // 只在接诊真的变化时跑。flushPending 每次渲染都会重建，但它读的全是 ref
    // （pendingRef / lastSavedContentRef），闭包再旧拿到的也是最新值。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [encounterId])

  // 文书类型切换（2026-08-21 第四轮走查）：后端草稿按 (encounter, record_type)
  // 分行存，乐观锁基线 lastUpdatedAtRef 却是单值——住院切文书后拿旧类型行的
  // updated_at 去校验新类型的行，必产生假 409（"病历已被其他设备修改"误报）。
  // 处理与切接诊同构：先把旧类型的 pending 用旧基线落盘，再清基线（新类型首发
  // 不带 expected_updated_at → 后端跳过乐观锁校验，安全 UPSERT）。
  const lastRecordTypeRef = useRef<string>(recordType)
  useEffect(() => {
    if (recordType !== lastRecordTypeRef.current) {
      flushPending() // pending 快照里存的是旧类型 + 旧基线，落对行
      lastRecordTypeRef.current = recordType
      lastSavedContentRef.current = ''
      lastUpdatedAtRef.current = null
      setSavingState('idle')
    }
    // flushPending 读的全是 ref，闭包新旧无碍（同上）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordType])

  // 关标签页 / 切后台 / 卸载（含退出登录跳转）：来不及等防抖，立刻落盘。
  // pagehide 比 beforeunload 可靠（移动端与 bfcache 都会触发）；
  // visibilitychange→hidden 覆盖切走标签页但没关的情况。
  useEffect(() => {
    const onHide = () => flushPending()
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flushPending()
    }
    // 网络恢复即补发队列（2026-08-29 离线审计）：此前 flush 唯一触发点是
    // 切接诊——断网期间积压的草稿要等医生换患者才补传，中间全程状态是
    // "已暂存本机"。online 事件一到就补，医生停笔也能自动恢复。
    const onOnline = () => {
      // 跳过当前编辑键 + 立即补发当前稿（2026-08-29 第八轮回归修复）：
      // 恢复瞬间队列旧稿与防抖新稿并发在飞时，null 基线旧稿后落会静默
      // 回滚新稿。当前键交给 triggerFlush 立即发最新内容，队列只补别的接诊。
      void flushDraftQueue(performSave, {
        skipEncounterId: lastEncounterRef.current ?? undefined,
        skipRecordType: useRecordStore.getState().recordType,
      })
      useRecordAutoSaveTrigger.getState().triggerFlush()
    }
    window.addEventListener('pagehide', onHide)
    window.addEventListener('online', onOnline)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('pagehide', onHide)
      window.removeEventListener('online', onOnline)
      document.removeEventListener('visibilitychange', onVisibility)
      flushPending() // 组件卸载（路由跳走 / 退出登录）
    }
    // 只在挂载/卸载时装卸监听。flushPending 每次渲染都会重建，但它读的全是
    // ref（pendingRef / lastSavedContentRef），闭包再旧拿到的也是最新值，
    // 因此不需要跟着重新装卸——那样反而会在每次输入时反复增删事件监听。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 主防抖循环
  useEffect(() => {
    if (!encounterId) return
    if (isFinal) return
    if (!recordContent) return
    if (recordContent === lastSavedContentRef.current) return

    // 记下待保存快照，供 flushPending 在切接诊/关标签页时抢救（审计 #32）
    pendingRef.current = {
      encounter_id: encounterId,
      record_type: recordType,
      content: recordContent,
      expected_updated_at: lastUpdatedAtRef.current,
    }

    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => {
      const payload = pendingRef.current
      pendingRef.current = null
      if (payload) void performSave(payload)
    }, DEBOUNCE_MS)

    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
  }, [recordContent, encounterId, recordType, isFinal])

  // ── 服务端基线同步信号（2026-08-21 第四轮走查）──────────────────────────
  // AI 生成完成时后端已落库（save_ai_draft），done 事件带回 updated_at。
  // 这里把乐观锁基线 + 已保存内容一起对齐：生成内容不再被防抖重复上传，
  // 医生后续编辑带正确基线，不再假 409。
  const baselineSignal = useRecordAutoSaveTrigger(s => s.baselineSignal)
  const lastBaselineSignalRef = useRef(baselineSignal)
  useEffect(() => {
    if (baselineSignal === lastBaselineSignalRef.current) return
    lastBaselineSignalRef.current = baselineSignal
    const payload = useRecordAutoSaveTrigger.getState().baselinePayload
    if (!payload) return
    lastUpdatedAtRef.current = payload.updatedAt
    lastSavedContentRef.current = payload.content
    // 流式生成期间防抖排下的待发快照携带旧基线且内容已在服务端——作废
    pendingRef.current = null
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    // 同步 recordStore 的"已落库"标记，水合的 localIsDirty 判断与状态条同时受益
    useRecordStore.getState().markSaved(payload.content, Date.now())
    setSavingState('saved')
  }, [baselineSignal])

  // ── 强制 flush 信号：外部（如 ExamSuggestionTab 写入按钮）希望立即落盘 ─────
  // 防抖跳过等待，直接 performSave 当前 recordContent。乐观锁 ref 仍由本 hook
  // 维护，外部不需要也不能动，避免 409 误报。详见 recordAutoSaveTrigger.ts。
  const forceFlushSignal = useRecordAutoSaveTrigger(s => s.forceFlushSignal)
  // 跳过初次渲染（信号默认 0，不应触发）
  const lastFlushSignalRef = useRef(forceFlushSignal)
  useEffect(() => {
    if (forceFlushSignal === lastFlushSignalRef.current) return
    lastFlushSignalRef.current = forceFlushSignal
    if (!encounterId || isFinal) return
    // 直接读 store 拿最新 recordContent，绕开 closure（外部触发 flush 时 hook
    // closure 里的 recordContent 可能还是旧的）
    const latestContent = useRecordStore.getState().recordContent
    if (!latestContent) return
    if (latestContent === lastSavedContentRef.current) return
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    pendingRef.current = null // 这一发已经覆盖了待保存内容，别让 flushPending 再发一次
    void performSave({
      encounter_id: encounterId,
      record_type: recordType,
      content: latestContent,
      expected_updated_at: lastUpdatedAtRef.current,
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceFlushSignal])

  return { savedAt, savingState }
}
