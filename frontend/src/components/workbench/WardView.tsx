/**
 * 病区视图组件（components/workbench/WardView.tsx）
 *
 * 以卡片列表形式展示当前医生负责的全部活跃住院接诊，
 * 点击患者卡片即可切换到该接诊的工作台。
 */
import { useEffect, useState, useCallback } from 'react'
import { Button, Empty, Spin, Tag, Typography } from 'antd'
import { PlusOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import api from '@/services/api'
import { useWorkbenchStore } from '@/store/workbenchStore'

const { Text } = Typography

interface WardPatient {
  encounter_id: string
  patient_id: string
  patient_name: string
  gender: string
  age: number | null
  bed_no: string | null
  admission_route: string | null
  admission_condition: string | null
  visited_at: string | null
  chief_complaint: string | null
  /** 入院天数：在 fetchWard 时一次性计算好，避免 render 内调 Date.now()
      触发 react-hooks/purity 规则 */
  admit_days?: number | null
}

interface Props {
  onNewEncounter: () => void
  onSelectPatient: (p: WardPatient) => void
  selectedEncounterId?: string | null
}

const CONDITION_COLOR: Record<string, string> = {
  危: '#dc2626',
  急: '#f97316',
  一般: '#16a34a',
}

export default function WardView({ onNewEncounter, onSelectPatient, selectedEncounterId }: Props) {
  const { currentEncounterId } = useWorkbenchStore()
  const [patients, setPatients] = useState<WardPatient[]>([])
  const [loading, setLoading] = useState(false)

  const fetchWard = useCallback(async () => {
    setLoading(true)
    try {
      const res = (await api.get('/inpatient/ward')) as any
      // 在拉取后立即计算 admit_days（async 函数内调 Date.now() 不在 render path）
      const now = Date.now()
      const items: WardPatient[] = (res.items || []).map((p: WardPatient) => ({
        ...p,
        admit_days: p.visited_at
          ? Math.floor((now - new Date(p.visited_at).getTime()) / 86400000)
          : null,
      }))
      setPatients(items)
    } catch {
      setPatients([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchWard()
  }, [fetchWard])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 病区标题栏 */}
      <div
        style={{
          padding: '10px 12px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <Text style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
          病区 · {patients.length} 位患者
        </Text>
        <Button
          icon={<ReloadOutlined />}
          size="small"
          type="text"
          onClick={fetchWard}
          loading={loading}
          style={{ color: 'var(--text-4)' }}
        />
      </div>

      {/* 患者列表 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '8px 8px' }}>
        {loading && patients.length === 0 ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
            <Spin size="small" />
          </div>
        ) : patients.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span style={{ fontSize: 12, color: 'var(--text-4)' }}>暂无住院患者</span>}
            style={{ marginTop: 32 }}
          />
        ) : (
          patients.map(p => {
            const isSelected =
              p.encounter_id === selectedEncounterId || p.encounter_id === currentEncounterId
            const admitDays = p.admit_days ?? null

            return (
              <div
                key={p.encounter_id}
                onClick={() => onSelectPatient(p)}
                style={{
                  background: isSelected
                    ? 'linear-gradient(135deg, #f0fdf4, #dcfce7)'
                    : 'var(--surface-2)',
                  border: `1.5px solid ${isSelected ? '#86efac' : 'var(--border)'}`,
                  borderRadius: 10,
                  padding: '9px 11px',
                  marginBottom: 6,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  boxShadow: isSelected ? '0 1px 6px rgba(5,150,105,0.12)' : 'none',
                }}
              >
                {/* 姓名 + 床号 */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: 4,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div
                      style={{
                        width: 24,
                        height: 24,
                        borderRadius: '50%',
                        background: isSelected
                          ? 'linear-gradient(135deg, #065f46, #059669)'
                          : '#e2e8f0',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}
                    >
                      <UserOutlined
                        style={{ fontSize: 11, color: isSelected ? '#fff' : '#94a3b8' }}
                      />
                    </div>
                    <Text
                      style={{
                        fontSize: 13,
                        fontWeight: 700,
                        color: isSelected ? '#065f46' : 'var(--text-1)',
                      }}
                    >
                      {p.patient_name}
                    </Text>
                  </div>
                  {p.bed_no && (
                    <Tag
                      color={isSelected ? 'green' : 'default'}
                      style={{ margin: 0, fontSize: 11, borderRadius: 6 }}
                    >
                      {p.bed_no}
                    </Tag>
                  )}
                </div>

                {/* 性别/年龄/病情 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Text style={{ fontSize: 11, color: 'var(--text-4)' }}>
                    {p.gender === 'male' ? '男' : p.gender === 'female' ? '女' : '未知'}
                    {p.age != null ? ` · ${p.age}岁` : ''}
                  </Text>
                  {p.admission_condition && (
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        color: CONDITION_COLOR[p.admission_condition] || '#64748b',
                        background: `${CONDITION_COLOR[p.admission_condition] || '#64748b'}18`,
                        padding: '1px 5px',
                        borderRadius: 4,
                      }}
                    >
                      {p.admission_condition}
                    </span>
                  )}
                  {admitDays != null && (
                    <Text style={{ fontSize: 10, color: 'var(--text-4)' }}>
                      住院第 {admitDays + 1} 天
                    </Text>
                  )}
                </div>

                {/* 主诉摘要 */}
                {p.chief_complaint && (
                  <Text
                    ellipsis
                    style={{ fontSize: 11, color: 'var(--text-3)', display: 'block', marginTop: 2 }}
                  >
                    {p.chief_complaint}
                  </Text>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* 新建住院接诊按钮 */}
      <div style={{ padding: '8px 8px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
        <Button
          icon={<PlusOutlined />}
          block
          size="small"
          onClick={onNewEncounter}
          style={{
            borderRadius: 8,
            background: '#059669',
            borderColor: '#059669',
            color: '#fff',
            fontWeight: 600,
          }}
        >
          新建住院接诊
        </Button>
      </div>
    </div>
  )
}
