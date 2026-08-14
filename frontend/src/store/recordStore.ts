/**
 * 病历内容 Store（store/recordStore.ts）
 *
 * Audit Round 4 M1 拆分：负责病历正文 + AI 生成态 + 签发态。
 *
 * 职责（只管病历相关）：
 *   - recordContent（病历正文）+ recordType（门诊/住院/中医）
 *   - AI 运行态：isGenerating、isPolishing、pendingGenerate
 *   - 签发：isFinal、finalizedAt
 *
 * 不管什么：
 *   - 接诊元信息（visitType / isFirstVisit / isPatientReused / previousRecordContent）
 *     → 已经在 activeEncounterStore 里管，从那里读，避免双源
 *
 * 跨 store 联动：
 *   setRecordContent → 调用 useQCStore.markStale()，让上一轮质控结果显示"已过时"。
 *   单向依赖（record → qc），不会成环。
 *
 * 持久化（localStorage key: medassist-record）：
 *   recordContent / recordType / 签发态 持久化；
 *   isGenerating / isPolishing / pendingGenerate 是瞬态，不持久化。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useQCStore } from './qcStore'

interface RecordState {
  // ── 病历正文 ──────────────────────────────────────────────
  recordContent: string
  recordType: string

  // ── AI 运行态（不持久化） ─────────────────────────────────
  isGenerating: boolean
  isPolishing: boolean
  /** 等待 inquiry 保存完成后再触发生成 */
  pendingGenerate: boolean

  // ── 签发 ──────────────────────────────────────────────────
  isFinal: boolean
  /** 签发时刻（zh-CN 本地化字符串），与 isFinal 联动 */
  finalizedAt: string | null

  // ── auto-save 状态（5 秒防抖保存到后端 draft） ───────────
  /** 最后一次 auto-save 成功时间戳（毫秒），0=从未保存。状态条据此显示"刚刚保存"等。 */
  recordSavedAt: number

  /**
   * 本份正文所属的接诊 ID（2026-08-13 第五轮审计修复）。
   *
   * 为什么必须有：本 store 与 activeEncounterStore 是**两个独立的 localStorage 槽**，
   * 各自只有一个位置。医生开两个标签页分别看甲、乙两位患者时，接诊指针会被后开的
   * 那个覆盖成乙，而本 store 里可能还留着甲的病历正文；刷新后两个槽各自还原，
   * 界面就拼出「乙患者 + 甲患者的病历」，再被 auto-save 原样写进乙的接诊——
   * 病历写到错误患者身上是医疗事故级问题。
   * 打上归属标记后，还原时对不上就丢弃正文（宁可让医生重新拉取，也不能张冠李戴）。
   */
  ownerEncounterId: string | null

  /**
   * 上一次成功 auto-save 时的正文（2026-08-13 第五轮审计修复）。
   *
   * 用来精确判断「本地是否有未落库的编辑」：auto-save 是 5 秒防抖的，医生打完
   * 一段话立刻刷新时最后几秒的内容还没落库，而水合会用服务端旧版覆盖它——
   * 医生收不到任何提示，只会发现自己写的东西没了。
   * 靠时间戳判断不行：那时 recordSavedAt 还是上一次保存的时刻，不会晚于服务端。
   * 比对内容才准：current !== lastSaved 就说明有未保存的本地编辑。
   */
  lastSavedContent: string

  /**
   * 签发时冻结的病案首页快照（2026-08-14 第六轮审计修复）。
   *
   * 后端 workspace 快照的 active_record 里**一直有** patient_snapshot，
   * 但编辑器打印/导出把这个参数写死成 null——于是已签发病历打印时用的是
   * **实时患者数据**而不是冻结快照：患者签发后改了住址/电话，重新打印这份
   * 已签发病历，首页会跟着变。而首页冻结正是 2026-05-16 加快照机制的目的。
   */
  patientSnapshot: Record<string, unknown> | null

  // ── actions ───────────────────────────────────────────────
  setRecordContent: (content: string) => void
  /** 绑定正文归属的接诊（切换接诊 / 拉取到服务端病历时调用） */
  bindOwner: (encounterId: string | null) => void
  /** 校验归属：与当前接诊不符则丢弃正文并返回 false（刷新还原后调用） */
  assertOwner: (encounterId: string | null) => boolean
  setRecordType: (type: string) => void
  setGenerating: (v: boolean) => void
  setPolishing: (v: boolean) => void
  setPendingGenerate: (v: boolean) => void
  /**
   * 设置签发状态。
   *
   * signedAt 传后端返回的真实签发时间（2026-08-14 第六轮审计修复）：
   * 原实现无条件用 new Date()，而医生刷新页面水合已签发病历时也会走这里——
   * **签发时间被改成刷新那一刻**，打印出来的病历上写着错误的签发时刻，
   * 而后端明明返回了真实的 submitted_at。
   * 不传则用当前时间（医生本人刚点签发的场景，此刻就是签发时刻）。
   */
  setFinal: (v: boolean, signedAt?: string | null) => void
  setRecordSavedAt: (ts: number) => void
  /** auto-save 成功时记录「已落库的正文」，供水合判断本地是否更脏 */
  markSaved: (content: string, ts: number) => void
  setPatientSnapshot: (snap: Record<string, unknown> | null) => void
  /** 在病历末尾追加一段（带空行分隔，AI 续写流式输出用） */
  appendToRecord: (text: string) => void
  /** 重置到初始状态（切换接诊 / 登出时调用） */
  reset: () => void
}

export const useRecordStore = create<RecordState>()(
  persist(
    (set, get) => ({
      recordContent: '',
      recordType: 'outpatient',
      ownerEncounterId: null,
      lastSavedContent: '',
      patientSnapshot: null,

      isGenerating: false,
      isPolishing: false,
      pendingGenerate: false,

      isFinal: false,
      finalizedAt: null,

      recordSavedAt: 0,

      setRecordContent: content => {
        set({ recordContent: content })
        // 病历内容变化时通知 qcStore：上一轮质控结果已过时（按钮变"重新质控"）
        useQCStore.getState().markStale()
      },

      setRecordType: type =>
        set(state => {
          // 切换病历类型要连带重置"已签发"锁（2026-08-14 第六轮审计修复）：
          // isFinal 是**整个编辑器**的只读开关，而住院一次接诊要写入院记录、
          // 多份病程、出院小结等**多份文书**——签完第一份后 isFinal 恒为 true，
          // 医生切到"日常病程"仍然是只读，后续文书根本没法写。
          // 换类型 = 换一份文书，锁应当跟着新文书的真实状态走；新文书的
          // 已签发状态随后由水合/拉取病历时的 setFinal 灌入。
          if (type === state.recordType) return { recordType: type }
          return {
            recordType: type,
            isFinal: false,
            finalizedAt: null,
            recordContent: '',
            lastSavedContent: '',
            patientSnapshot: null,
            recordSavedAt: 0,
          }
        }),

      setGenerating: v => set({ isGenerating: v }),
      setPolishing: v => set({ isPolishing: v }),
      setPendingGenerate: v => set({ pendingGenerate: v }),

      setFinal: (v, signedAt) =>
        set({
          isFinal: v,
          finalizedAt: v
            ? signedAt
              ? new Date(signedAt).toLocaleString('zh-CN')
              : new Date().toLocaleString('zh-CN')
            : null,
        }),

      setRecordSavedAt: ts => set({ recordSavedAt: ts }),

      markSaved: (content, ts) => set({ lastSavedContent: content, recordSavedAt: ts }),

      setPatientSnapshot: snap => set({ patientSnapshot: snap }),

      appendToRecord: text =>
        set(state => ({
          recordContent: state.recordContent ? state.recordContent + '\n\n' + text : text,
        })),

      bindOwner: encounterId => set({ ownerEncounterId: encounterId }),

      assertOwner: encounterId => {
        const owner = get().ownerEncounterId
        // 归属为空 = 本次改动之前留下的旧数据，无从判断归谁，一律丢弃更安全
        if (!encounterId || owner !== encounterId) {
          if (get().recordContent) {
            set({
              recordContent: '',
              lastSavedContent: '',
              isFinal: false,
              finalizedAt: null,
              recordSavedAt: 0,
            })
          }
          set({ ownerEncounterId: encounterId })
          return false
        }
        return true
      },

      reset: () =>
        set({
          recordContent: '',
          recordType: 'outpatient',
          ownerEncounterId: null,
          lastSavedContent: '',
          isGenerating: false,
          isPolishing: false,
          pendingGenerate: false,
          isFinal: false,
          finalizedAt: null,
          recordSavedAt: 0,
        }),
    }),
    {
      name: 'medassist-record',
      // 瞬态字段（isGenerating/isPolishing/pendingGenerate）不持久化
      partialize: state => ({
        recordContent: state.recordContent,
        recordType: state.recordType,
        ownerEncounterId: state.ownerEncounterId,
        lastSavedContent: state.lastSavedContent,
        patientSnapshot: state.patientSnapshot,
        isFinal: state.isFinal,
        finalizedAt: state.finalizedAt,
        recordSavedAt: state.recordSavedAt,
      }),
    }
  )
)
