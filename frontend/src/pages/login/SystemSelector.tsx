/**
 * 登录页系统选择卡（pages/login/SystemSelector.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 LoginPage.tsx 抽出的纯展示子组件。
 * 门诊 / 住院两张选择卡片，按选中态切换对应场景主题色（门诊青 / 住院深青）。
 * 无内部状态：受控组件，由父组件持有 selectedSystem。
 */
import { AppstoreOutlined, HomeOutlined } from '@ant-design/icons'
import { scenes, neutral, radius } from '@/theme/tokens'

/** 登录目标系统类型（门诊 / 住院），登录后写入 authStore.systemType */
export type SystemType = 'outpatient' | 'inpatient'

interface SystemSelectorProps {
  /** 当前选中的系统 */
  value: SystemType
  /** 切换系统回调 */
  onChange: (system: SystemType) => void
}

export default function SystemSelector({ value, onChange }: SystemSelectorProps) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: neutral.text2, marginBottom: 10 }}>
        选择登录系统
      </div>
      <div style={{ display: 'flex', gap: 10 }}>
        {(
          [
            {
              key: 'outpatient',
              label: '门诊系统',
              icon: <AppstoreOutlined />,
              desc: '门诊接诊 · 病历书写',
            },
            {
              key: 'inpatient',
              label: '住院系统',
              icon: <HomeOutlined />,
              desc: '住院管理 · 入院记录',
            },
          ] as const
        ).map(s => {
          const active = value === s.key
          const sceneTheme = s.key === 'inpatient' ? scenes.inpatient : scenes.outpatient
          return (
            <button
              type="button"
              key={s.key}
              onClick={() => onChange(s.key)}
              aria-pressed={active}
              style={{
                flex: 1,
                padding: '14px 12px',
                borderRadius: radius.lg,
                cursor: 'pointer',
                border: `2px solid ${active ? sceneTheme.primary : neutral.border}`,
                background: active ? sceneTheme.primaryLight : neutral.surface2,
                transition: 'all 0.2s',
                textAlign: 'center',
              }}
            >
              <div
                style={{
                  fontSize: 22,
                  marginBottom: 4,
                  color: active ? sceneTheme.primary : neutral.text3,
                }}
              >
                {s.icon}
              </div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: active ? sceneTheme.primary : neutral.text2,
                }}
              >
                {s.label}
              </div>
              <div style={{ fontSize: 11, color: neutral.text4, marginTop: 2 }}>{s.desc}</div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
