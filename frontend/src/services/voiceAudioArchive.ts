/**
 * 录音归档 / 兜底转写结果处理（services/voiceAudioArchive.ts）
 *
 * 2026-08-14 第七轮审计从 useVoiceDialogueSession 抽出：那个 hook 负责的是
 * 「一次录音的生命周期编排」，而"音频传上去之后怎么处理返回结果"是另一件事，
 * 且第七轮在这里改了两处语义（#23 追加而非替换、#27 兜底无结果要告警），
 * 留在原文件会让 hook 超出本项目「组件 ≤300 行」的硬约束。
 */
import { message } from '@/services/messageBridge'
import { saveVoiceTranscript, uploadVoiceAudio } from '@/services/voiceTranscriptApi'

// ── 录音文件归档开关 ────────────────────────────────────────────────────────
// 关闭时不把录音归档到后端（省测试服务器磁盘，损失"播放原始录音"功能）。
// 注意（2026-08-11 审计修复）：即便关闭归档，当实时 ASR 失败（transcriptText 为空）
// 时仍必须上传音频走 Qwen-Audio 云端兜底转写——否则医生口述内容会静默全丢，而 UI
// 明确承诺"停止后自动云端转写"。故真正的跳过条件见下：关归档 且 已有转写文字
// 才跳过；无转写文字（兜底场景，低频）无视本开关必须上传。
const ENABLE_AUDIO_UPLOAD = false

export interface ArchiveAudioParams {
  blob: Blob
  /** 实时 ASR 已识别的文本；空串表示实时 ASR 失败，需要云端兜底整段转写 */
  transcriptText: string
  /**
   * 归档到**开始录音时**的那个接诊（审计 #28）。
   * 录音期间医生可能已经切走，用调用处闭包里的"当前接诊"会把音频挂到
   * 另一位患者身上，所以由调用方显式钉死归属。
   */
  ownerEncounterId: string | null
  visitType: 'outpatient' | 'inpatient'
  /** 取当前完整转写（用于兜底结果追加，而非整段替换） */
  getExistingTranscript: () => string
  setTranscript: React.Dispatch<React.SetStateAction<string>>
  setTranscriptId: (value: string | null) => void
  /** 已有的 voice_record id（纯文本落库时走更新而非每次新建） */
  getExistingTranscriptId?: () => string | null
}

/**
 * 上传录音音频文件并处理返回结果。
 * - transcriptText 非空：仅归档（后端跳过整段转写）
 * - transcriptText 为空：后端 Qwen-Audio 兜底转写
 */
export async function archiveAudioBlob(params: ArchiveAudioParams): Promise<void> {
  const {
    blob,
    transcriptText,
    ownerEncounterId,
    visitType,
    getExistingTranscript,
    setTranscript,
    setTranscriptId,
    getExistingTranscriptId,
  } = params

  if (!blob.size) return
  if (!ENABLE_AUDIO_UPLOAD && transcriptText.trim()) {
    // 不传音频，但**必须把文字落库**（2026-08-14 第七轮审计 #26）：
    // 原先这里直接 return，实时 ASR 这条主路径下 voice_records 表一行都不写，
    // 转写只活在浏览器 localStorage 里——换台电脑或清了数据就没了，
    // 工作台快照的 latest_voice_record 也恒为空。
    try {
      const saved = await saveVoiceTranscript({
        encounterId: ownerEncounterId,
        visitType,
        transcript: transcriptText,
        voiceRecordId: getExistingTranscriptId?.() ?? null,
      })
      if (saved?.voice_record_id) setTranscriptId(saved.voice_record_id)
    } catch {
      // 落库失败不打扰医生：本地 localStorage 里仍有完整转写，
      // 下次进入该接诊会重新尝试；这里弹错反而干扰问诊。
    }
    return
  }

  const data = await uploadVoiceAudio(blob, transcriptText, {
    encounterId: ownerEncounterId,
    visitType,
  })
  if (data?.voice_record_id) setTranscriptId(data.voice_record_id)

  const isFallback = !transcriptText.trim()
  if (data?.transcript && isFallback) {
    // ── 追加而不是整段替换（2026-08-14 第七轮审计 #23）─────────────────────
    //
    // 原先是 setTranscript(data.transcript)，把已有正文整个换掉。
    // 触发场景很常见：医生录第一段时实时 ASR 正常（转写已在框里），录第二段
    // 时 WebSocket 挂了走兜底——此时上传的 transcriptText 被有意置空以触发
    // 云端转写，而云端只转了第二段音频，回来一替换，**第一段的转写连同医生
    // 的手工修改一起消失**。兜底转写只认识自己这一段音频，结果只能是增量。
    const existing = getExistingTranscript()
    setTranscript(existing ? `${existing}\n${data.transcript}` : data.transcript)
    message.success('语音已保存，云端转写完成')
  } else if (isFallback) {
    // 走了兜底但云端没给出任何文字（2026-08-14 第七轮审计 #27）：
    // 原先这里落到 else 弹「原始语音已保存」——医生刚说完的一段话一个字都没
    // 转出来，界面却告诉他成功了，他就直接去写下一位患者了。
    // 实时 ASR 已经失败、云端兜底又没结果，必须明确告知。
    message.warning('云端转写未能识别出内容，录音已保存，请手工补录或重说一遍')
  } else {
    message.success('原始语音已保存')
  }
}
