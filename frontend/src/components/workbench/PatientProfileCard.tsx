/**
 * 患者档案卡片（components/workbench/PatientProfileCard.tsx）
 *
 * 摆放在 InquiryPanel 顶部，集中编辑患者纵向档案：
 *   既往史 / 过敏史 / 个人史 / 家族史 / 长期用药 / 婚育史 / 宗教信仰 (共 7 个)
 *
 * 月经史已移除：是时变信息（每月都变），跟主诉/生命体征一类，每次接诊重填，
 * 已挪到 InpatientInquiryPanel 的「专项评估」段以 inquiry 字段呈现。
 *
 * 与本次接诊解耦：
 *   保存调 PUT /patients/:id/profile（不是 /encounters/:id/inquiry），
 *   档案数据跟随患者，下次复诊自动带入，不需要医生重新填写。
 *
 * 字段级时间戳（FHIR verificationStatus 思路）：
 *   每个字段独立显示「X 天前由某医生确认」，按距今天数染色提醒：
 *     7 天内      → 灰色（新鲜）
 *     7-180 天    → 浅黄（建议确认）
 *     180 天以上  → 橙色（请重新核对）
 *   长期用药字段阈值更短（30 天就开始黄）—— 用药变化快。
 *   字段下提供「✓ 仍准确」按钮，点击调 POST /profile/confirm 仅刷新 updated_at。
 *
 * 折叠默认行为：
 *   - 复诊（已有档案）默认折叠，点击展开查看/修改
 *   - 初诊（无档案）默认展开，引导医生录入
 */

import { useState, useEffect, useRef } from 'react'
import { Input, Space, Tag, Button, message } from 'antd'
import { UserOutlined, DownOutlined, RightOutlined, CheckOutlined } from '@ant-design/icons'
import { usePatientProfileCard } from '@/hooks/usePatientProfileCard'
import api from '@/services/api'
import { usePatientCacheStore } from '@/store/patientCacheStore'

const { TextArea } = Input

const labelStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--text-2)',
  marginBottom: 4,
  display: 'block',
}

interface FieldConfig {
  key: keyof ReturnType<typeof usePatientProfileCard>['form']
  label: string
  rows: number
  placeholder: string
  /** 单行 Input 而非 TextArea */
  singleLine?: boolean
  /** 该字段 N 天后开始黄色提醒（不传走默认 180 天） */
  staleAfterDays?: number
}

/**
 * 7 个档案字段（不含月经史）。
 * staleAfterDays：长期用药 30 天，其他用默认 180 天。
 */
const FIELDS: FieldConfig[] = [
  {
    key: 'past_history',
    label: '既往史',
    rows: 2,
    placeholder: '既往病史、手术史、传染病史；无特殊可填「既往体质可」',
  },
  {
    key: 'allergy_history',
    label: '过敏史',
    rows: 1,
    placeholder: '如：青霉素过敏 / 否认药物及食物过敏史',
    singleLine: true,
  },
  {
    key: 'personal_history',
    label: '个人史',
    rows: 2,
    placeholder: '吸烟、饮酒、职业、生活习惯；无特殊可填「无特殊」',
  },
  {
    key: 'family_history',
    label: '家族史',
    rows: 2,
    placeholder: '直系亲属重要疾病史；无特殊可填「无特殊」',
  },
  {
    key: 'current_medications',
    label: '长期用药',
    rows: 2,
    placeholder: '正在服用的药物名称、剂量、用法；无可填「无」',
    staleAfterDays: 30,  // 用药变化快，30 天就提醒确认
  },
  {
    key: 'marital_history',
    label: '婚育史',
    rows: 2,
    placeholder: '婚姻、生育情况；无特殊可填「适龄结婚，配偶子女体健」',
  },
  {
    key: 'religion_belief',
    label: '宗教信仰',
    rows: 1,
    placeholder: '如：无 / 佛教 / 基督教（涉及禁忌时填写）',
    singleLine: true,
  },
]

/**
 * 计算字段元数据距今的"天数 + 颜色"，未录入返回 null。
 * staleAfterDays：超过此天数显示为黄色；3×staleAfterDays 显示为橙色。
 */
function getStaleness(updatedAt: string | null | undefined, staleAfterDays: number) {
  if (!updatedAt) return null
  const updated = new Date(updatedAt).getTime()
  if (Number.isNaN(updated)) return null
  const days = Math.floor((Date.now() - updated) / (1000 * 60 * 60 * 24))
  let color: string
  let bgColor: string | undefined
  if (days <= 7) {
    color = '#9ca3af' // 灰：新鲜
  } else if (days <= staleAfterDays) {
    color = '#a16207' // 浅褐：默认范围内
  } else if (days <= staleAfterDays * 3) {
    color = '#b45309' // 橙黄：建议确认
    bgColor = '#fef3c7'
  } else {
    color = '#ea580c' // 深橙：请重新核对
    bgColor = '#ffedd5'
  }
  let label: string
  if (days === 0) label = '今天确认'
  else if (days < 30) label = `${days} 天前确认`
  else if (days < 365) label = `${Math.floor(days / 30)} 个月前确认`
  else label = `${Math.floor(days / 365)} 年前确认`
  return { days, label, color, bgColor }
}

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
  const filledLabels = FIELDS.filter(f => form[f.key] && form[f.key].trim()).map(f => f.label)

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
      {/* 卡片标题栏：点击切换折叠 */}
      <div
        onClick={() => setCollapsed(v => !v)}
        style={{
          padding: '8px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <Space size={6}>
          {collapsed ? (
            <RightOutlined style={{ fontSize: 11, color: '#854d0e' }} />
          ) : (
            <DownOutlined style={{ fontSize: 11, color: '#854d0e' }} />
          )}
          <UserOutlined style={{ color: '#854d0e' }} />
          <span style={{ fontSize: 13, fontWeight: 700, color: '#713f12' }}>患者档案</span>
          <Tag
            color="orange"
            style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px' }}
          >
            跟随患者
          </Tag>
          {isDirty && (
            <Tag
              color="red"
              style={{ margin: 0, fontSize: 10, padding: '0 6px', height: 18, lineHeight: '16px' }}
            >
              未保存
            </Tag>
          )}
        </Space>
        <Space size={6}>
          {collapsed && filledLabels.length > 0 && (
            <span style={{ fontSize: 11, color: '#854d0e' }}>已填：{filledLabels.join('、')}</span>
          )}
          {collapsed && filledLabels.length === 0 && (
            <span style={{ fontSize: 11, color: '#a16207' }}>未录入档案</span>
          )}
          {updatedAt && !collapsed && (
            <span style={{ fontSize: 11, color: '#a16207' }}>
              最近更新于 {new Date(updatedAt).toLocaleDateString('zh-CN')}
            </span>
          )}
        </Space>
      </div>

      {/* 展开后的字段表单 */}
      {!collapsed && (
        <div className="profile-card-body" style={{ padding: '0 12px 10px', background: '#fffef7' }}>
          {FIELDS.map(f => {
            const meta = fieldsMeta?.[f.key]
            const stale = getStaleness(meta?.updated_at, f.staleAfterDays ?? 180)
            const hasValue = !!form[f.key]?.trim()
            return (
              <div key={f.key} style={{ marginBottom: 10 }}>
                {/* label 行：标签 + 时间戳/确认按钮（右对齐） */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: 4,
                  }}
                >
                  <span style={labelStyle}>{f.label}</span>
                  {stale && hasValue && (
                    <Space size={4}>
                      <span
                        style={{
                          fontSize: 10,
                          color: stale.color,
                          background: stale.bgColor,
                          padding: stale.bgColor ? '1px 6px' : 0,
                          borderRadius: 4,
                        }}
                      >
                        {stale.label}
                      </span>
                      {/* 仅在"开始变黄"以后显示确认按钮，避免新数据也来打扰 */}
                      {stale.days > 7 && (
                        <Button
                          size="small"
                          type="link"
                          icon={<CheckOutlined />}
                          loading={confirmingField === f.key}
                          onClick={e => {
                            e.stopPropagation()
                            handleConfirmField(f.key)
                          }}
                          style={{ fontSize: 10, height: 18, padding: '0 4px', color: '#059669' }}
                        >
                          仍准确
                        </Button>
                      )}
                    </Space>
                  )}
                </div>
                {f.singleLine ? (
                  <Input
                    size="small"
                    value={form[f.key]}
                    onChange={e => setField(f.key, e.target.value)}
                    placeholder={f.placeholder}
                    style={{ borderRadius: 6, fontSize: 13 }}
                  />
                ) : (
                  <TextArea
                    rows={f.rows}
                    value={form[f.key]}
                    onChange={e => setField(f.key, e.target.value)}
                    placeholder={f.placeholder}
                    style={{ borderRadius: 6, fontSize: 13, resize: 'none' }}
                  />
                )}
              </div>
            )
          })}
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
