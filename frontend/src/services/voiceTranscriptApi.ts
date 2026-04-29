/**
 * 语音转写 API 调用集合（services/voiceTranscriptApi.ts）
 *
 * 把 useVoiceInputCard 里散落的 4 个后端调用抽出来集中管理，让 hook 主体只剩 React 状态/编排：
 *   - fetchAudioToken    : 拿一次性鉴权 token，给前端 <audio> 标签播放原始录音
 *   - uploadVoiceAudio   : 上传录音 Blob（实时 ASR 完成时附 transcript / 失败时空串走兜底转写）
 *   - structureVoice     : 调 /ai/voice-structure 把口语转写整理成结构化问诊字段
 *   - deleteVoiceRecord  : 清空当前接诊的语音记录
 *
 * 所有函数返回原始后端响应，调用方按需取字段；不抛业务异常（统一在 hook 里 try/catch + message）。
 *
 * Audit Round 4 M6 拆分。
 */
import api from '@/services/api'
import type { InquiryData } from '@/store/types'
import type { DialogueItem } from '@/store/voiceTranscriptStore'

export interface VoiceUploadResult {
  voice_record_id?: string
  transcript?: string
}

export interface VoiceStructureResult {
  inquiry?: Partial<InquiryData>
  transcript_summary?: string
  speaker_dialogue?: DialogueItem[]
  transcript_id?: string
}

/** 拉一次性 audio token（给 <audio> 标签鉴权播放原始录音）。 */
export async function fetchAudioToken(transcriptId: string): Promise<string | null> {
  try {
    const res: any = await api.get(`/ai/voice-records/${transcriptId}/audio-token`)
    return res?.audio_token || null
  } catch {
    return null
  }
}

/**
 * 上传录音文件到后端归档 + 必要时整段转写。
 *
 * @param blob 录音 Blob（mediaRecorder onstop 出来的）
 * @param transcriptText 实时 ASR 已识别文本；为空表示走 Qwen-Audio 兜底转写
 * @param meta 当前接诊上下文（encounter_id / visit_type）
 */
export async function uploadVoiceAudio(
  blob: Blob,
  transcriptText: string,
  meta: { encounterId: string | null; visitType: 'outpatient' | 'inpatient' }
): Promise<VoiceUploadResult> {
  const formData = new FormData()
  formData.append('file', blob, `voice-record-${Date.now()}.webm`)
  if (meta.encounterId) formData.append('encounter_id', meta.encounterId)
  formData.append('visit_type', meta.visitType)
  formData.append('transcript', transcriptText)
  return (await api.post('/ai/voice-records/upload', formData)) as VoiceUploadResult
}

/**
 * 调 /ai/voice-structure 把口语转写整理成结构化问诊字段。
 *
 * 增量分析基线（让 LLM 只输出新增/修正字段，不要整段覆盖）：
 *   - existingRecord：右侧病历草稿全文（最权威，含医生手改痕迹）
 *   - existingInquiry：左侧问诊字段（次选，病历草稿未生成时使用）
 *   后端路由优先取 existingRecord；都为空时基线规则不触发，按原行为整段输出。
 */
export async function structureVoice(payload: {
  fullTranscript: string
  transcriptId: string | null
  visitType: 'outpatient' | 'inpatient'
  patient: { name?: string; gender?: string; age?: number | null } | null | undefined
  existingInquiry: Record<string, any>
  existingRecord?: string
}): Promise<VoiceStructureResult> {
  const { fullTranscript, transcriptId, visitType, patient, existingInquiry, existingRecord } =
    payload
  return (await api.post('/ai/voice-structure', {
    transcript: fullTranscript,
    transcript_id: transcriptId,
    visit_type: visitType,
    patient_name: patient?.name || '',
    patient_gender: patient?.gender || '',
    patient_age: patient?.age != null ? String(patient.age) : '',
    existing_inquiry: existingInquiry,
    existing_record: existingRecord || '',
  })) as VoiceStructureResult
}

/** 删除某条语音记录（清空重录场景使用）。失败静默吞掉，调用方不依赖结果。 */
export async function deleteVoiceRecord(transcriptId: string): Promise<void> {
  try {
    await api.delete(`/ai/voice-records/${transcriptId}`)
  } catch {
    // 静默：本地清空 UI 仍然继续，不阻塞用户操作
  }
}

/** 过滤 patch 里的空值字段（'' / null / undefined），避免覆盖已有内容。 */
export function filterPatch(patch: Partial<InquiryData>): Partial<InquiryData> {
  return Object.fromEntries(
    Object.entries(patch).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  ) as Partial<InquiryData>
}
