/**
 * 患者档案卡片（components/workbench/PatientProfileCard.tsx）
 *
 * 摆放在 InquiryPanel 顶部，集中编辑患者纵向档案：
 *   既往史 / 过敏史 / 个人史 / 家族史 / 长期用药 / 婚育史 / 宗教信仰（共 7 个）
 *
 * 月经史已移除：是时变信息（每月都变），跟主诉/生命体征一类，每次接诊重填，
 * 已挪到 InpatientInquiryPanel 的「专项评估」段以 inquiry 字段呈现。
 *
 * 与本次接诊解耦：
 *   保存调 PUT /patients/:id/profile（不是 /encounters/:id/inquiry），
 *   档案数据跟随患者，下次复诊自动带入，不需要医生重新填写。
 *
 * 字段级时间戳（FHIR verificationStatus 思路）：
 *   每个字段独立显示「X 天前由某医生确认」，按距今天数染色提醒——
 *   字段下提供「✓ 仍准确」按钮，点击调 POST /profile/confirm 仅刷新 updated_at。
 *
 * 折叠默认行为：
 *   - 复诊（已有档案）默认折叠，点击展开查看/修改
 *   - 初诊（无档案）默认展开，引导医生录入
 *
 * Audit Round 4 M6 拆分：
 *   - getStaleness + PROFILE_FIELDS → patientProfile/staleness.ts
 *   - 标题栏（折叠态/展开态） → patientProfile/PatientProfileHeader.tsx
 *   - 单字段渲染（label + 时间戳 + 输入） → patientProfile/PatientProfileField.tsx
 *   - 本主文件保留：状态聚合 + 折叠初始化 + 字段表 map + ✓ 仍准确 confirm API
 */
import { useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { usePatientProfileCard } from '@/hooks/usePatientProfileCard'
import api from '@/services/api'
import { usePatientCacheStore } from '@/store/patientCacheStore'
import PatientProfileField from './patientProfile/PatientProfileField'
import PatientProfileHeader from './patientProfile/PatientProfileHeader'
import { PROFILE_FIELDS } from './patientProfile/staleness'

export default function PatientProfileCard() {
  // 1.6.3：保存动作迁到 InquiryPanel/InpatientInquiryPanel 底部统一按钮，
  // 卡片本身只负责字段编辑与折叠态展示
  const { patientId, form, setField, isDirty, updatedAt, hasAnyProfileContent, fieldsMeta } =
    usePatientProfileCard()

  const [collapsed, setCollapsed] = useState(true)
  const [confirmingField, setConfirmingField] = useState<string | null>(null)

  // 切换患者时按"后端 profile 是否已有内容"决定初始折叠态
  const prevPatientIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (prevPatientIdRef.current !== patientId) {
      setCollapsed(hasAnyProfileContent)
      prevPatientIdRef.current = patientId
    }
  }, [patientId, hasAnyProfileContent])

  if (!patientId) {
    // 未选择患者时不渲染卡片，避免空表单干扰
    return null
  }

  // 折叠态显示摘要：哪些字段有内容
  const filledLabels = PROFILE_FIELDS.filter(f => form[f.key] && form[f.key].trim()).map(
    f => f.label
  )

  // ✓ 仍准确按钮：调后端 confirm 端点刷新该字段 updated_at
  const handleConfirmField = async (fieldKey: string) => {
    if (!patientId) return
    setConfirmingField(fieldKey)
    try {
      const updated: any = await api.post(`/patients/${patientId}/profile/confirm`, {
        field: fieldKey,
      })
      // 写回 patientCache 的 fields_meta 部分（值不变，只更新元数据时间）
      usePatientCacheStore.getState().upsertProfile(patientId, {
        past_history: updated.past_history ?? null,
        allergy_history: updated.allergy_history ?? null,
        family_history: updated.family_history ?? null,
        personal_history: updated.personal_history ?? null,
        current_medications: updated.current_medications ?? null,
        marital_history: updated.marital_history ?? null,
        religion_belief: updated.religion_belief ?? null,
        updated_at: updated.updated_at ?? null,
        fields_meta: updated.fields_meta ?? null,
      })
      message.success('已确认')
    } catch {
      message.error('确认失败，请稍后再试')
    } finally {
      setConfirmingField(null)
    }
  }

  return (
    <div
      className="profile-card"
      style={{
        background: '#fefce8',
        border: '1px solid #fde047',
        borderRadius: 8,
        marginBottom: 10,
        overflow: 'hidden',
      }}
    >
      <PatientProfileHeader
        collapsed={collapsed}
        onToggle={() => setCollapsed(v => !v)}
        isDirty={isDirty}
        filledLabels={filledLabels}
        updatedAt={updatedAt}
      />

      {!collapsed && (
        <div
          className="profile-card-body"
          style={{ padding: '0 12px 10px', background: '#fffef7' }}
        >
          {PROFILE_FIELDS.map(f => (
            <PatientProfileField
              key={f.key}
              field={f}
              value={form[f.key]}
              onChange={v => setField(f.key, v)}
              fieldUpdatedAt={fieldsMeta?.[f.key]?.updated_at}
              confirming={confirmingField === f.key}
              onConfirm={handleConfirmField}
            />
          ))}
          {/* 1.6.3：保存按钮已合并到 InquiryPanel 底部"保存"按钮，
              此处只显示当前编辑状态提示，引导医生去底部保存 */}
          {isDirty && (
            <div
              style={{
                fontSize: 11,
                color: '#a16207',
                background: '#fef3c7',
                border: '1px dashed #f59e0b',
                borderRadius: 6,
                padding: '6px 10px',
                marginTop: 4,
                textAlign: 'center',
              }}
            >
              档案有未保存的修改 — 点击下方"保存"按钮一并提交
            </div>
          )}
        </div>
      )}
    </div>
  )
}
