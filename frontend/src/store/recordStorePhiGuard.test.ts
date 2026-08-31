/**
 * 病案首页快照的跨患者隔离回归锁（store/recordStorePhiGuard.test.ts）
 *
 * 2026-08-31 导出产物审计抓到的**严重**问题：recordStore.reset() 清了正文
 * 与 draftsByType（注释还特意写了"不清会跨患者残留（PHI）"），唯独漏了
 * patientSnapshot——而它是打印件/Word 病案首页的**优先**取值源
 * （recordExport 的 pick(snapshot, patient) 顺序），还进了 partialize
 * 跨刷新存活。
 *
 * 触发的是门诊叫号主流程，不是边角场景：
 *   切接诊 → reset() 把 recordType 置回 'outpatient' → 随后
 *   setRecordType('outpatient') 因"类型没变"提前返回 → 清不到快照 →
 *   新患者的打印件首页印着上一位患者的姓名/身份证/住址/电话。
 * 既是废纸（正文与首页不是同一个人），也是把甲的身份信息交到乙手上的
 * PHI 泄漏。
 *
 * 这三条断言钉住三个清理点，防止将来重构时又漏掉其中之一。
 */
import { describe, it, expect, beforeEach } from 'vitest'

import { useRecordStore } from './recordStore'

const SNAP = { name: '甲患者', id_card: '330100199001011234', phone: '13800000000' }

describe('recordStore 病案首页快照隔离', () => {
  beforeEach(() => {
    useRecordStore.setState({
      patientSnapshot: SNAP,
      recordContent: '甲患者的病历正文',
      recordType: 'outpatient',
      ownerEncounterId: 'enc-A',
    })
  })

  it('reset() 必须清掉 patientSnapshot（切接诊走这条路）', () => {
    useRecordStore.getState().reset()
    expect(useRecordStore.getState().patientSnapshot).toBeNull()
  })

  it('assertOwner 归属不符时必须清掉 patientSnapshot', () => {
    // 归属指向 enc-A，断言成 enc-B → 走丢弃分支
    const passed = useRecordStore.getState().assertOwner('enc-B')
    expect(passed).toBe(false)
    expect(useRecordStore.getState().patientSnapshot).toBeNull()
  })

  it('切换文书类型时清掉 patientSnapshot（住院多文书路径）', () => {
    useRecordStore.getState().setRecordType('admission_note')
    expect(useRecordStore.getState().patientSnapshot).toBeNull()
  })
})
