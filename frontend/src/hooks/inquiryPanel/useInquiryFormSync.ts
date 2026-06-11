/**
 * 问诊表单同步副作用（hooks/inquiryPanel/useInquiryFormSync.ts）
 *
 * 从 useInquiryPanel.ts 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - 切换接诊 / inquirySavedAt 更新时全量同步表单
 *   - 辅助检查 / 就诊时间 / 现病史 / 初步诊断被外部写入 store 时单字段同步
 *
 * 注意：各 useEffect 的依赖数组刻意不完整（form 引用稳定 / inquiry 整体加入
 * 会导致每次输入重置），eslint-disable 注释为原设计，原样保留。
 */
import { useEffect } from 'react'
import type { FormInstance } from 'antd'
import dayjs from 'dayjs'
import type { InquiryData } from '@/store/types'

interface InquiryFormSyncParams {
  form: FormInstance
  inquiry: InquiryData
  /** 当前接诊 id，切换时触发全量同步 */
  currentEncounterId: string | null
  /** 最后一次主动保存时间戳，0=从未保存 */
  inquirySavedAt: number
  setIsDirty: (v: boolean) => void
}

export function useInquiryFormSync({
  form,
  inquiry,
  currentEncounterId,
  inquirySavedAt,
  setIsDirty,
}: InquiryFormSyncParams) {
  // 切换接诊或 inquirySavedAt 更新时全量同步表单
  useEffect(() => {
    form.setFieldsValue({
      ...inquiry,
      visit_time: inquiry.visit_time ? dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm') : dayjs(),
      onset_time: inquiry.onset_time ? dayjs(inquiry.onset_time, 'YYYY-MM-DD HH:mm') : null,
    })
    // inquirySavedAt=0 且有数据说明是刷新前填了但未保存，保持 dirty 提示用户保存
    if (inquirySavedAt === 0 && inquiry.chief_complaint) {
      setIsDirty(true)
    } else {
      setIsDirty(false)
    }
    // inquiry 是整个表单状态，加进 deps 会让每次输入都重置——只在接诊切换时重置
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, currentEncounterId, inquirySavedAt])

  // 辅助检查由外部（如追问建议）写入时同步表单
  useEffect(() => {
    const current = form.getFieldValue('auxiliary_exam') || ''
    if (inquiry.auxiliary_exam !== current) {
      form.setFieldValue('auxiliary_exam', inquiry.auxiliary_exam || '')
    }
    // form 引用稳定，加进 deps 会让效果过度触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inquiry.auxiliary_exam])

  // 就诊时间从 store 初始化（workspace snapshot 的 visited_at）
  useEffect(() => {
    if (inquiry.visit_time && !form.getFieldValue('visit_time')) {
      form.setFieldValue('visit_time', dayjs(inquiry.visit_time, 'YYYY-MM-DD HH:mm'))
    }
    // form 引用稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inquiry.visit_time])

  // 现病史被追问建议修改时同步表单并激活保存按钮
  useEffect(() => {
    const current = form.getFieldValue('history_present_illness') || ''
    if (inquiry.history_present_illness !== current) {
      form.setFieldValue('history_present_illness', inquiry.history_present_illness || '')
      setIsDirty(true)
    }
    // form 引用稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inquiry.history_present_illness])

  // AI 诊断建议写入 initial_impression 时同步表单
  useEffect(() => {
    const current = form.getFieldValue('initial_impression') || ''
    if (inquiry.initial_impression !== current) {
      form.setFieldValue('initial_impression', inquiry.initial_impression || '')
      setIsDirty(true)
    }
    // form 引用稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inquiry.initial_impression])
}
