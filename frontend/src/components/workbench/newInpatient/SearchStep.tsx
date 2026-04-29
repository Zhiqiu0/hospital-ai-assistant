/**
 * 住院新建接诊：搜索步骤（newInpatient/SearchStep.tsx）
 *
 * 输入姓名/患者编号，模糊匹配后展示已有患者卡片列表。
 * 命中点击 → 复用；未命中或主动新建 → 切换到表单步骤。
 *
 * 三态住院 Tag（与门诊端复诊搜索、历史病历抽屉保持一致）：
 *   在院中 → 不该再开新住院接诊（已经在住），应去病区找
 *   已出院 → 旧患者再次入院，正常新建
 *   无 Tag → 纯门诊或新患者
 */
import { Input, Spin, Avatar, Space, Tag, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { ACCENT } from './constants'

interface SearchStepProps {
  keyword: string
  onSearch: (kw: string) => void
  searching: boolean
  results: any[]
  onSelect: (p: any) => void
  onCreateNew: () => void
}

export default function SearchStep({
  keyword,
  onSearch,
  searching,
  results,
  onSelect,
  onCreateNew,
}: SearchStepProps) {
  return (
    <div style={{ paddingTop: 16 }}>
      <Input.Search
        placeholder="输入姓名或患者编号搜索已有患者..."
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
              <Avatar size={32} style={{ background: ACCENT, flexShrink: 0 }}>
                {p.name?.[0]}
              </Avatar>
              <div style={{ flex: 1 }}>
                <Space size={6} align="center">
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</span>
                  {p.has_active_inpatient ? (
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
                  ) : p.has_any_inpatient_history ? (
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
              <Tag color="green" style={{ flexShrink: 0 }}>
                住院复用
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
