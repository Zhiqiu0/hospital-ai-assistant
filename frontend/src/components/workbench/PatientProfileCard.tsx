/**
 * 患者档案卡片（components/workbench/PatientProfileCard.tsx）
 *
 * 摆放在 InquiryPanel 顶部，集中编辑患者纵向档案：
 *   既往史 / 过敏史 / 个人史 / 家族史 / 长期用药 / 婚育史 / 月经史(女) / 宗教信仰
 *
 * 与本次接诊解耦：
 *   保存调 PUT /patients/:id/profile（不是 /encounters/:id/inquiry），
 *   档案数据跟随患者，下次复诊自动带入，不需要医生重新填写。
 *
 * 折叠默认行为：
 *   - 复诊（已有档案）默认折叠，点击展开查看/修改
 *   - 初诊（无档案）默认展开，引导医生录入
 *
 * 业务逻辑全部在 hooks/usePatientProfileCard.ts，本文件只渲染 JSX。
 */

import { useState, useEffect, useRef } from 'react'
import { Input, Space, Tag } from 'antd'
import { UserOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
import { usePatientProfileCard } from '@/hooks/usePatientProfileCard'

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
  /** 仅女性显示 */
  femaleOnly?: boolean
  /** 单行 Input 而非 TextArea */
  singleLine?: boolean
}

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
  },
  {
    key: 'marital_history',
    label: '婚育史',
    rows: 2,
    placeholder: '婚姻、生育情况；无特殊可填「适龄结婚，配偶子女体健」',
  },
  {
    key: 'menstrual_history',
    label: '月经史',
    rows: 2,
    placeholder: '初潮年龄、行经天数/间隔天数、末次月经、经量、痛经、生育情况',
    femaleOnly: true,
  },
  {
    key: 'religion_belief',
    label: '宗教信仰',
    rows: 1,
    placeholder: '如：无 / 佛教 / 基督教（涉及禁忌时填写）',
    singleLine: true,
  },
]

export default function PatientProfileCard() {
  // 1.6.3：保存动作迁到 InquiryPanel/InpatientInquiryPanel 底部统一按钮，
  // 卡片本身只负责字段编辑与折叠态展示
  const { patientId, isFemale, form, setField, isDirty, updatedAt, hasAnyProfileContent } =
    usePatientProfileCard()

  const [collapsed, setCollapsed] = useState(true)
  // 切换患者时按"后端 profile 是否已有内容"决定初始折叠态：
  //   有档案 → 折叠（避免占空间）
  //   无档案 → 展开（引导初诊医生录入）
  // 用 hasAnyProfileContent（来自 hook 的 profile 直读，非 form 本地态）避免时序问题
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
  const filledLabels = FIELDS.filter(f => {
    if (f.femaleOnly && !isFemale) return false
    return form[f.key] && form[f.key].trim()
  }).map(f => f.label)

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
              更新于 {new Date(updatedAt).toLocaleDateString('zh-CN')}
            </span>
          )}
        </Space>
      </div>

      {/* 展开后的字段表单 */}
      {!collapsed && (
        <div className="profile-card-body" style={{ padding: '0 12px 10px', background: '#fffef7' }}>
          {FIELDS.map(f => {
            if (f.femaleOnly && !isFemale) return null
            return (
              <div key={f.key} style={{ marginBottom: 8 }}>
                <span style={labelStyle}>{f.label}</span>
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
