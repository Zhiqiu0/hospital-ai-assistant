/**
 * 问诊保存逻辑（hooks/inquiryPanel/useInquirySave.ts）
 *
 * 从 useInquiryPanel.ts 拆出（2026-06-11 Round 5.5 拆分），逻辑一字未改：
 *   - onSave：表单提交回调（AI 规范化 + 病历章节同步 + 急诊去向记录）
 *   - saveAll：统一保存入口（必填校验守卫 + profile/inquiry 并发保存）
 *   - saving / savedDisposition 两个本地状态随逻辑一起搬入
 */
import { useState } from 'react'
import type { FormInstance } from 'antd'
import { message } from '@/services/messageBridge'
import type { Patient } from '@/domain/medical'
import { usePatientProfileEditStore } from '@/store/patientProfileEditStore'
import api from '@/services/api'
import { INQUIRY_FORM_FIELDS, buildInquiryData, syncInquiryToRecord } from '@/utils/inquirySync'
import type { InquiryData } from '@/store/types'
import { useDiagnosisEntriesStore, selectWestern } from '@/store/diagnosisEntriesStore'
import {
  composeDiagnosisItems,
  renderDiagnosisProjection,
} from '@/domain/medical/diagnosisProjection'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'

interface InquirySaveParams {
  form: FormInstance
  inquiry: InquiryData
  setInquiry: (data: InquiryData) => void
  currentEncounterId: string | null
  recordContent: string
  setRecordContent: (content: string) => void
  setPendingGenerate: (v: boolean) => void
  isEmergency: boolean
  isDirty: boolean
  setIsDirty: (v: boolean) => void
  /** 患者档案是否有未保存改动（来自 patientProfileEditStore） */
  profileDirty: boolean
  currentPatient: Patient | null
}

export function useInquirySave({
  form,
  inquiry,
  setInquiry,
  currentEncounterId,
  recordContent,
  setRecordContent,
  setPendingGenerate,
  isEmergency,
  isDirty,
  setIsDirty,
  profileDirty,
  currentPatient,
}: InquirySaveParams) {
  const [saving, setSaving] = useState(false)
  // 保存后的患者去向，用于驱动急诊流转提示
  const [savedDisposition, setSavedDisposition] = useState<string>('')

  const onSave = async (values: Record<string, unknown>) => {
    setSaving(true)
    // 跨患者写回守卫（2026-08-28 弱网审计）：normalize-fields 最长可等 300s，
    // 期间医生可能已切到下一位患者（叫号场景高频）。慢响应回来后如果无条件
    // setInquiry/setEntries/setRecordContent，就把 A 的内容写进 B 的工作台并被
    // auto-save 固化——生成/润色链路早有同款指针守卫，保存链路此前漏装。
    const startEncounterId = useActiveEncounterStore.getState().encounterId
    const stillSameEncounter = () =>
      useActiveEncounterStore.getState().encounterId === startEncounterId
    const data = buildInquiryData(values)

    // 找出本次新增或修改的字段，用于 AI 规范化和病历章节同步
    const changedFields: Record<string, string> = {}
    // inquiry 是 InquiryData，但下标访问要走 string 键——用 Record 视图绕开
    const inquiryAsRecord = inquiry as unknown as Record<string, string | undefined>
    for (const key of INQUIRY_FORM_FIELDS) {
      const val = data[key] ?? ''
      if (val && val !== (inquiryAsRecord[key] ?? '')) changedFields[key] = val
    }

    const isFirstGeneration = !recordContent.trim()

    let normalizedData = { ...data }
    if (!isFirstGeneration && Object.keys(changedFields).length > 0) {
      try {
        // 后端规范化接口仅返回被修改字段，形状不固定，故用 Record<string, string>
        const res = (await api.post('/ai/normalize-fields', { fields: changedFields })) as {
          fields?: Record<string, string>
        } | null
        if (res?.fields) {
          normalizedData = { ...data, ...res.fields }
          form.setFieldsValue(res.fields)
        }
      } catch {
        /* 规范化失败时继续用原值 */
      }
      // 慢响应期间已切患者：后续所有本地写回都会污染新患者工作台，整体中止
      if (!stillSameEncounter()) {
        setSaving(false)
        return
      }
    }

    // ── 诊断条目合成与投影（2026-08-21 阶段1b 结构化）────────────────────
    // 西医条目（store）+ 中医病/证（表单文本）合成完整列表；条目为空而文本
    // 非空时整段初始化一条（AI 生成/复诊带入桥）。本地投影立即回填三个旧
    // 文本字段（LLM/渲染/QC 链路的输入源），PUT 后端后由权威投影再覆盖一致
    const diagnosisItems = composeDiagnosisItems(
      selectWestern(useDiagnosisEntriesStore.getState().entries),
      {
        western: normalizedData.western_diagnosis,
        tcmDisease: normalizedData.tcm_disease_diagnosis,
        tcmSyndrome: normalizedData.tcm_syndrome_diagnosis,
      }
    )
    useDiagnosisEntriesStore.getState().setEntries(diagnosisItems)
    const projection = renderDiagnosisProjection(diagnosisItems)
    normalizedData = {
      ...normalizedData,
      western_diagnosis: projection.western_diagnosis,
      tcm_disease_diagnosis: projection.tcm_disease_diagnosis,
      tcm_syndrome_diagnosis: projection.tcm_syndrome_diagnosis,
    }
    form.setFieldsValue({
      western_diagnosis: projection.western_diagnosis,
      tcm_disease_diagnosis: projection.tcm_disease_diagnosis,
      tcm_syndrome_diagnosis: projection.tcm_syndrome_diagnosis,
    })

    // buildInquiryData 返回的 Record<string, string> 与 InquiryData 字段并集兼容
    // （都是字符串型字段），借助 unknown 桥接，避免污染 inquirySync 的返回类型
    setInquiry(normalizedData as unknown as InquiryData)
    // 服务端保存问诊必须 await 并按结果给提示——不能 fire-and-forget：
    // PUT 失败却照样弹"已保存"、清 dirty，会让医生以为存上了，实际换设备/重登
    // 走 snapshot 恢复时数据回退到旧版（P1 静默丢数据）。
    let savedOk = true
    if (currentEncounterId) {
      try {
        await api.put(`/encounters/${currentEncounterId}/inquiry`, normalizedData)
        // 诊断条目落库（结构化权威源；后端会做主诊断唯一等校验 + 权威投影双写）
        await api.put(`/encounters/${currentEncounterId}/diagnoses`, {
          items: diagnosisItems.map(i => ({
            category: i.category,
            name: i.name,
            code: i.code || null,
            code_type: i.code_type || null,
            is_primary: i.is_primary,
            admission_condition: i.admission_condition || null,
            sort_order: i.sort_order,
          })),
        })
      } catch (err) {
        savedOk = false
        // 校验类 422 必须把后端 detail 透出（2026-08-29 第八轮回归修复）：
        // 体征生理极限/血压填反等校验错误此前被无差别归因成"网络问题"，
        // 医生反复重试无解。detail 是明确的中文纠错指引（"体温 45 超出…"）。
        const e = err as { status?: number; detail?: unknown; response?: { status?: number } }
        const status = e?.status ?? e?.response?.status
        // pydantic 校验错的 detail 是数组 [{msg: "Value error, 体温 45 …"}]，
        // 业务 HTTPException 的是字符串——两种形态都取出人话部分
        let detail = ''
        if (typeof e?.detail === 'string') {
          detail = e.detail
        } else if (Array.isArray(e?.detail) && e.detail.length) {
          const msg = (e.detail[0] as { msg?: string })?.msg || ''
          detail = msg.replace(/^Value error,\s*/, '')
        }
        if (status === 422 && detail) {
          message.error(detail)
          setSaving(false)
          return
        }
      }
    }

    if (!savedOk) {
      message.error('问诊保存失败，请检查网络后重试')
      setSaving(false)
      // 保留 isDirty：让医生知道还没存上，可再次点击保存
      return
    }
    // PUT 落库归属 startEncounterId 是正确的；但若期间已切患者，
    // 下面的正文章节同步/自动生成/去向提示都不能再碰新患者的工作台
    if (!stillSameEncounter()) {
      setSaving(false)
      return
    }

    // 将已改动的字段同步到右侧病历对应章节
    // 既往/过敏/个人/月经史 已迁到 PatientProfileCard，由其保存时单独同步章节
    if (recordContent) {
      const updated = syncInquiryToRecord(recordContent, normalizedData, changedFields)
      if (updated !== recordContent) setRecordContent(updated)
    }

    // 病历为空且已填主诉时，触发自动生成
    if (!recordContent.trim() && data.chief_complaint) {
      setPendingGenerate(true)
    }

    // 急诊场景：保存后记录患者去向，驱动流转提示
    if (isEmergency) setSavedDisposition((values.patient_disposition as string) || '')
    message.success({ content: '问诊信息已保存', duration: 1.5 })
    setIsDirty(false)
    setSaving(false)
  }

  /**
   * 统一保存：profile dirty 时调 PUT /patients/:id/profile；
   * inquiry dirty 时调 form.submit()（触发 onSave → PUT /encounters/:id/inquiry）。
   * 两个动作并发执行，互不阻塞。
   *
   * ── 2026-05-03 治本：必填校验守卫 ─────────────────────────────────────────
   * 之前直接调 form.submit() 而不 await validateFields：antd 校验失败时只在
   * 字段下方显示红字（如"请选择病发时间"），但 form.submit 不抛 error 给调用
   * 方，saveAll 继续往下走 → profile 仍然保存 → 弹"已保存" toast → 用户感知
   * "保存成功"。再叠加病历自动生成 → recordContent 非空 → isInputLocked=true
   * → 整个表单变灰，必填字段再也填不进去。
   * 修法：inquiry dirty 时先 await form.validateFields()，校验失败立刻 return
   * 并连 profile 一起停（避免"半保存"困惑）。校验过了再走原并发保存路径。
   */
  const saveAll = async () => {
    if (isDirty) {
      try {
        await form.validateFields()
      } catch (errInfo) {
        // form.validateFields() 默认不滚动也不聚焦——只 antd 字段下显示红字。
        // 用户反馈"提示了哪里没填但没跳过去看不见"，所以手动 scroll + focus 第一个错误字段，
        // 让医生填完它再点保存如果还有缺失，下次又会自动跳到下一个字段（errorFields 按
        // 表单声明顺序返回，第一个就是页面最靠上的那个，天然支持"逐个补"流程）。
        // antd validateFields rejection 形状是稳定的 ValidateErrorEntity<unknown>，
        // 这里用 inline type assertion 避免 any 触发 lint 阈值
        const errFields = (errInfo as { errorFields?: Array<{ name: unknown; errors: string[] }> })
          ?.errorFields
        const first = errFields?.[0]
        if (first?.name !== undefined) {
          form.scrollToField(first.name as string | number | (string | number)[], {
            behavior: 'smooth',
            block: 'center',
          })
          // setTimeout 等 scroll 动画大致结束再 focus，避免 focus 把页面位置又拽走
          setTimeout(() => {
            const inst = form.getFieldInstance(
              first.name as string | number | (string | number)[]
            ) as { focus?: () => void } | undefined
            inst?.focus?.()
          }, 300)
        }
        message.error(first?.errors?.[0] || '请补全必填项后再保存')
        return
      }
    }
    const profilePromise = profileDirty
      ? usePatientProfileEditStore.getState().save(currentPatient?.id || '')
      : Promise.resolve('noop' as const)
    if (isDirty) form.submit() // 校验已通过，submit 直接触发 onSave
    const profileResult = await profilePromise
    if (profileResult === true) {
      message.success({ content: '患者档案已保存', duration: 1.5 })
    }
    // inquiry 的 toast 由 onSave 内部弹；profile === 'noop' / false 不再额外弹
  }

  return { saving, savedDisposition, onSave, saveAll }
}
