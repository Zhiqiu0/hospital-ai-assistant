/**
 * inquiryStore 持久化回归测试（2026-09-10 持久化审计）
 *
 * 抓的 bug：partialize 持久化了 ownerEncounterId（#211 修复），但自定义
 * merge/migrate 的返回值漏了它——persisted 里存的 owner 永远还原不出来，
 * 每次刷新 owner 恒 null → assertOwner 必失配 reset → "刷新页面医生填到
 * 一半的内容不丢"的承诺整个是死的。
 *
 * 这里直接往 localStorage 塞持久化 payload 再触发 rehydrate，验证
 * merge 链路真的把 owner 与内容一起还原（而不是只测 partialize 写入侧）。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useInquiryStore } from './inquiryStore'
import { defaultInquiry } from './types'

beforeEach(() => {
  localStorage.clear()
  useInquiryStore.getState().reset()
  useInquiryStore.setState({ ownerEncounterId: null })
})

describe('inquiryStore rehydrate 必须完整还原持久化状态', () => {
  it('刷新恢复后 ownerEncounterId 与内容俱在，同接诊 assertOwner 不清数据', async () => {
    // 模拟刷新前 localStorage 里的真实持久化形状（zustand persist 封包格式）
    localStorage.setItem(
      'medassist-inquiry',
      JSON.stringify({
        state: {
          ownerEncounterId: 'enc-刷新前',
          inquiry: { ...defaultInquiry, chief_complaint: '刷新前填的主诉' },
          inquirySavedAt: 0,
          lastSavedInquiryJson: null,
        },
        version: 1,
      })
    )

    await useInquiryStore.persist.rehydrate()

    const s = useInquiryStore.getState()
    // 核心断言：owner 必须被还原（漏 merge 时这里是 null）
    expect(s.ownerEncounterId).toBe('enc-刷新前')
    expect(s.inquiry.chief_complaint).toBe('刷新前填的主诉')

    // 水合守卫对同一接诊放行，内容保住
    expect(s.assertOwner('enc-刷新前')).toBe(true)
    expect(useInquiryStore.getState().inquiry.chief_complaint).toBe('刷新前填的主诉')
  })

  it('换接诊时守卫仍然生效：owner 对不上必须清空（多标签页防串味不回退）', async () => {
    localStorage.setItem(
      'medassist-inquiry',
      JSON.stringify({
        state: {
          ownerEncounterId: 'enc-甲',
          inquiry: { ...defaultInquiry, chief_complaint: '甲患者的主诉' },
          inquirySavedAt: 0,
          lastSavedInquiryJson: null,
        },
        version: 1,
      })
    )
    await useInquiryStore.persist.rehydrate()

    expect(useInquiryStore.getState().assertOwner('enc-乙')).toBe(false)
    expect(useInquiryStore.getState().inquiry.chief_complaint).toBe('')
  })

  it('旧版本 payload（无 owner/基线字段）恢复不抛错且字段形状完整', async () => {
    localStorage.setItem(
      'medassist-inquiry',
      JSON.stringify({
        state: { inquiry: { chief_complaint: '老存档' }, inquirySavedAt: 123 },
        version: 1,
      })
    )
    await useInquiryStore.persist.rehydrate()

    const s = useInquiryStore.getState()
    expect(s.inquiry.chief_complaint).toBe('老存档')
    // defaultInquiry 兜底补齐，不产生 undefined 洞
    expect(s.inquiry.history_present_illness).toBe('')
    expect(s.ownerEncounterId).toBeNull()
    expect(s.lastSavedInquiryJson).toBeNull()
  })
})
