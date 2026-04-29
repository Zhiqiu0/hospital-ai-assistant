/**
 * 门诊新建/复诊弹窗的搜索步骤（newEncounter/SearchStep.tsx）
 *
 * 输入姓名/手机号 → 防抖搜索 → 命中点击 → 复用；未命中点"新患者"切换到表单。
 *
 * 三态住院 Tag（与住院弹窗一致）：
 *   active=true       → 在院中（绿）：还在住院，门诊医生可能要跨科会诊
 *   active=false + history=true → 已出院（灰）：术后复查/慢病随访常见
 *   history=false     → 不打 Tag（纯门诊或新患者）
 */
import { Input, Spin, Avatar, Space, Tag, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

interface SearchStepProps {
  keyword: string
  onSearch: (kw: string) => void
  searching: boolean
  results: any[]
  onSelect: (p: any) => void
  onCreateNew: () => void
  accentColor: string
  isEmergency: boolean
}

export default function SearchStep({
  keyword,
  onSearch,
  searching,
  results,
  onSelect,
  onCreateNew,
  accentColor,
  isEmergency,
}: SearchStepProps) {
  return (
    <div style={{ paddingTop: 16 }}>
      <Input.Search
        placeholder="输入姓名或手机号搜索已有患者..."
        value={keyword}
        onChange={e => onSearch(e.target.value)}
        size="large"
        autoFocus
        allowClear
        onClear={() => onSearch('')}
      />
      {searching && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin size="small" />
        </div>
      )}
      {!searching && results.length > 0 && (
        <div
          style={{
            marginTop: 10,
            border: '1px solid var(--border)',
            borderRadius: 8,
            overflow: 'hidden',
          }}
        >
          {results.map((p, i) => (
            <div
              key={p.id}
              onClick={() => onSelect(p)}
              style={{
                padding: '10px 14px',
                cursor: 'pointer',
                borderTop: i > 0 ? '1px solid var(--border-subtle)' : undefined,
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => {
                ;(e.currentTarget as HTMLDivElement).style.background = 'var(--surface-2)'
              }}
              onMouseLeave={e => {
                ;(e.currentTarget as HTMLDivElement).style.background = ''
              }}
            >
              <Avatar size={32} style={{ background: accentColor, flexShrink: 0 }}>
                {p.name?.[0]}
              </Avatar>
              <div style={{ flex: 1 }}>
                <Space size={6} align="center">
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</span>
                  {p.has_active_inpatient === true ? (
                    <Tag
                      color="green"
                      style={{
                        margin: 0,
                        fontSize: 10,
                        padding: '0 6px',
                        height: 16,
                        lineHeight: '14px',
                      }}
                    >
                      在院中
                    </Tag>
                  ) : p.has_any_inpatient_history === true ? (
                    <Tag
                      style={{
                        margin: 0,
                        fontSize: 10,
                        padding: '0 6px',
                        height: 16,
                        lineHeight: '14px',
                        background: '#f3f4f6',
                        color: '#6b7280',
                        border: '1px solid #e5e7eb',
                      }}
                    >
                      已出院
                    </Tag>
                  ) : null}
                </Space>
                <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : ''}
                  {p.age ? ` · ${p.age}岁` : ''}
                  {p.phone ? ` · ${p.phone}` : ''}
                </div>
              </div>
              <Tag color={isEmergency ? 'red' : 'blue'} style={{ flexShrink: 0 }}>
                复诊
              </Tag>
            </div>
          ))}
        </div>
      )}
      {keyword && !searching && results.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--text-4)', fontSize: 13, marginTop: 16 }}>
          未找到匹配患者
        </div>
      )}
      <div
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: '1px solid var(--border-subtle)',
          textAlign: 'center',
        }}
      >
        <Button type="dashed" icon={<PlusOutlined />} onClick={onCreateNew}>
          新患者，直接填写
        </Button>
      </div>
    </div>
  )
}
