/**
 * 录音归档 / 兜底转写结果处理回归测试（2026-08-14 第七轮审计 #23 #27）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/voiceTranscriptApi', () => ({
  uploadVoiceAudio: vi.fn(),
}))
vi.mock('@/services/messageBridge', () => ({
  message: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import { uploadVoiceAudio } from '@/services/voiceTranscriptApi'
import { message } from '@/services/messageBridge'
import { archiveAudioBlob } from './voiceAudioArchive'

const uploadMock = uploadVoiceAudio as unknown as ReturnType<typeof vi.fn>
const warnMock = message.warning as unknown as ReturnType<typeof vi.fn>
const successMock = message.success as unknown as ReturnType<typeof vi.fn>

function makeParams(over: Partial<Parameters<typeof archiveAudioBlob>[0]> = {}) {
  return {
    blob: new Blob(['x']),
    transcriptText: '', // 空 = 实时 ASR 失败，走云端兜底
    ownerEncounterId: 'enc-1',
    visitType: 'outpatient' as const,
    getExistingTranscript: () => '',
    setTranscript: vi.fn(),
    setTranscriptId: vi.fn(),
    ...over,
  }
}

beforeEach(() => {
  uploadMock.mockReset()
  warnMock.mockClear()
  successMock.mockClear()
})

describe('archiveAudioBlob', () => {
  it('兜底转写结果追加到已有正文，不整段替换', async () => {
    uploadMock.mockResolvedValue({ voice_record_id: 'v1', transcript: '第二段的转写' })
    const setTranscript = vi.fn()
    // 医生第一段实时 ASR 成功，框里已经有内容
    await archiveAudioBlob(
      makeParams({ getExistingTranscript: () => '第一段的转写', setTranscript })
    )

    expect(setTranscript).toHaveBeenCalledWith('第一段的转写\n第二段的转写')
  })

  it('本来没有正文时兜底结果直接落入', async () => {
    uploadMock.mockResolvedValue({ voice_record_id: 'v1', transcript: '云端转写内容' })
    const setTranscript = vi.fn()
    await archiveAudioBlob(makeParams({ setTranscript }))

    expect(setTranscript).toHaveBeenCalledWith('云端转写内容')
  })

  it('兜底转写没识别出内容时告警，不弹成功', async () => {
    uploadMock.mockResolvedValue({ voice_record_id: 'v1', transcript: '' })
    await archiveAudioBlob(makeParams())

    expect(warnMock).toHaveBeenCalledTimes(1)
    expect(String(warnMock.mock.calls[0][0])).toContain('未能识别')
    expect(successMock).not.toHaveBeenCalled()
  })

  it('音频归档到调用方指定的接诊，而不是别的', async () => {
    uploadMock.mockResolvedValue({ voice_record_id: 'v1', transcript: 'x' })
    await archiveAudioBlob(makeParams({ ownerEncounterId: 'enc-原患者' }))

    expect(uploadMock.mock.calls[0][2]).toMatchObject({ encounterId: 'enc-原患者' })
  })

  it('空音频直接跳过，不发请求', async () => {
    await archiveAudioBlob(makeParams({ blob: new Blob([]) }))
    expect(uploadMock).not.toHaveBeenCalled()
  })

  it('实时 ASR 已有文本且归档关闭时跳过上传', async () => {
    await archiveAudioBlob(makeParams({ transcriptText: '实时转写好的内容' }))
    expect(uploadMock).not.toHaveBeenCalled()
  })
})
