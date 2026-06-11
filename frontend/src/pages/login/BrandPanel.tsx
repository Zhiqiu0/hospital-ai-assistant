/**
 * 登录页左侧品牌宣传面板（pages/login/BrandPanel.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 LoginPage.tsx 抽出的纯展示子组件。
 * 渐变背景 + 装饰圆 + Logo + 系统名 + 三条特性卡片；
 * 按 selectedSystem 切换门诊青 / 住院深青主题与特性文案。
 * 视觉：全部颜色从 theme/tokens.ts 读取；图标用 antd SVG 图标（无障碍 + 专业度）。
 */
import {
  MedicineBoxOutlined,
  ThunderboltOutlined,
  MessageOutlined,
  SafetyOutlined,
  FileTextOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import { scenes, radius, typography } from '@/theme/tokens'
import type { SystemType } from './SystemSelector'

/** 门诊 / 住院两套特性宣传文案（图标 + 标题 + 描述） */
const FEATURES: Record<SystemType, { icon: React.ReactNode; title: string; desc: string }[]> = {
  outpatient: [
    { icon: <ThunderboltOutlined />, title: 'AI 病历生成', desc: '一键生成标准化病历草稿' },
    { icon: <MessageOutlined />, title: '智能追问建议', desc: '自动提示关键问诊问题' },
    { icon: <SafetyOutlined />, title: 'AI 质控检查', desc: '实时检测病历规范问题' },
  ],
  inpatient: [
    { icon: <FileTextOutlined />, title: '住院病历生成', desc: '符合浙江省2021版质控标准' },
    { icon: <ExperimentOutlined />, title: '专项评估辅助', desc: 'VTE风险、营养、心理一键评估' },
    { icon: <SafetyOutlined />, title: 'AI 质控检查', desc: '按百分制评分标准实时检测' },
  ],
}

interface BrandPanelProps {
  /** 当前选中的系统（决定主题色与特性文案） */
  selectedSystem: SystemType
}

export default function BrandPanel({ selectedSystem }: BrandPanelProps) {
  const isInpatient = selectedSystem === 'inpatient'
  const theme = isInpatient ? scenes.inpatient : scenes.outpatient

  return (
    <div
      style={{
        flex: 1,
        background: `linear-gradient(145deg, ${theme.primaryDark} 0%, ${theme.primary} 50%, ${theme.accentLight} 100%)`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: '60px 48px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'background 0.4s ease',
      }}
    >
      {/* 装饰圆 */}
      <div
        style={{
          position: 'absolute',
          top: -80,
          right: -80,
          width: 320,
          height: 320,
          borderRadius: '50%',
          background: 'rgba(255,255,255,0.06)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: -60,
          left: -60,
          width: 240,
          height: 240,
          borderRadius: '50%',
          background: 'rgba(255,255,255,0.05)',
        }}
      />

      <div style={{ position: 'relative', textAlign: 'center', color: 'var(--surface)' }}>
        <div
          style={{
            width: 72,
            height: 72,
            borderRadius: 20,
            background: 'rgba(255,255,255,0.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 24px',
            backdropFilter: 'blur(10px)',
            border: '1px solid rgba(255,255,255,0.25)',
          }}
        >
          <MedicineBoxOutlined style={{ fontSize: 34, color: 'var(--surface)' }} />
        </div>
        <h1
          style={{
            fontSize: 32,
            fontWeight: 800,
            letterSpacing: '-0.5px',
            marginBottom: 8,
            fontFamily: typography.fontHeading,
          }}
        >
          MediScribe
        </h1>
        <p style={{ fontSize: 16, opacity: 0.85, marginBottom: 48 }}>
          {isInpatient ? '住院部临床智能助手系统' : '门诊临床接诊智能助手系统'}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, textAlign: 'left' }}>
          {FEATURES[selectedSystem].map(f => (
            <div
              key={f.title}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                background: 'rgba(255,255,255,0.1)',
                borderRadius: radius.lg,
                padding: '14px 16px',
                border: '1px solid rgba(255,255,255,0.15)',
                backdropFilter: 'blur(4px)',
              }}
            >
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: radius.md,
                  background: 'rgba(255,255,255,0.18)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 18,
                  color: 'var(--surface)',
                  flexShrink: 0,
                }}
              >
                {f.icon}
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{f.title}</div>
                <div style={{ fontSize: 12, opacity: 0.75, marginTop: 2 }}>{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
