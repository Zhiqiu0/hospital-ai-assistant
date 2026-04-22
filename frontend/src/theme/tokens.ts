/**
 * 设计 Tokens 单一来源（theme/tokens.ts）
 *
 * 全站所有页面的颜色 / 间距 / 字体 / 阴影 / 圆角 / 动效时长统一从此文件导出。
 * 禁止在组件内硬编码这些值。
 *
 * 三个场景主题：
 *   outpatient  门诊（默认）    医疗青  #0891B2
 *   emergency   急诊            救急红  #DC2626
 *   inpatient   住院            深医青  #0E7490
 */

// ── 场景主题 ──────────────────────────────────────────────────────────────────
export const scenes = {
  outpatient: {
    name: '门诊',
    primary: '#0891B2',
    primaryDark: '#0E7490',
    primaryLight: '#ECFEFF',
    primaryBorder: '#A5F3FC',
    accentLight: '#06B6D4',
    accentLighter: '#67E8F9',
    shadowRgba: '8, 145, 178',
  },
  emergency: {
    name: '急诊',
    primary: '#DC2626',
    primaryDark: '#B91C1C',
    primaryLight: '#FEF2F2',
    primaryBorder: '#FECACA',
    accentLight: '#EF4444',
    accentLighter: '#FCA5A5',
    shadowRgba: '220, 38, 38',
  },
  inpatient: {
    name: '住院',
    primary: '#0E7490',
    primaryDark: '#155E75',
    primaryLight: '#ECFEFF',
    primaryBorder: '#A5F3FC',
    accentLight: '#0891B2',
    accentLighter: '#22D3EE',
    shadowRgba: '14, 116, 144',
  },
} as const

export type SceneKey = keyof typeof scenes

// ── 语义色 ────────────────────────────────────────────────────────────────────
export const semantic = {
  success: '#22C55E',
  successLight: '#F0FDF4',
  successBorder: '#BBF7D0',
  warning: '#F59E0B',
  warningLight: '#FFFBEB',
  error: '#EF4444',
  errorLight: '#FEF2F2',
  info: '#0891B2',
  infoLight: '#ECFEFF',
} as const

// ── 中性色 ────────────────────────────────────────────────────────────────────
export const neutral = {
  // 背景层级
  bg: '#F0FDFA',
  surface: '#FFFFFF',
  surface2: '#F8FAFC',
  surface3: '#F1F5F9',
  // 边框
  border: '#E2E8F0',
  borderSubtle: '#F1F5F9',
  // 文字层级
  text1: '#0F172A', // 主要
  text2: '#334155', // 次要
  text3: '#64748B', // 辅助
  text4: '#94A3B8', // 占位
} as const

// ── 间距 ──────────────────────────────────────────────────────────────────────
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  '2xl': 24,
  '3xl': 32,
} as const

// ── 圆角 ──────────────────────────────────────────────────────────────────────
export const radius = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  pill: 20,
  full: 9999,
} as const

// ── 阴影 ──────────────────────────────────────────────────────────────────────
export const shadow = {
  xs: '0 1px 2px rgba(0,0,0,0.05)',
  sm: '0 1px 4px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
  md: '0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04)',
  lg: '0 8px 24px rgba(0,0,0,0.10), 0 4px 8px rgba(0,0,0,0.05)',
} as const

// ── 字体 ──────────────────────────────────────────────────────────────────────
export const typography = {
  fontBody: "'Noto Sans SC', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  fontHeading: "'Figtree', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  fontMono: "'JetBrains Mono', 'Courier New', monospace",
  fontSize: {
    xs: 11,
    sm: 12,
    base: 14,
    md: 14,
    lg: 16,
    xl: 18,
    '2xl': 20,
    '3xl': 24,
  },
  lineHeight: {
    tight: 1.3,
    normal: 1.5,
    relaxed: 1.6,
    loose: 1.75,
  },
} as const

// ── 动效 ──────────────────────────────────────────────────────────────────────
export const motion = {
  fast: '120ms',
  base: '180ms',
  slow: '280ms',
  ease: 'cubic-bezier(0.4, 0, 0.2, 1)',
} as const

// ── 层级 ──────────────────────────────────────────────────────────────────────
export const zIndex = {
  base: 1,
  dropdown: 10,
  sticky: 20,
  fixed: 30,
  modal: 50,
  popover: 60,
  toast: 70,
} as const

// ── 组件尺寸 ──────────────────────────────────────────────────────────────────
export const sizing = {
  headerHeight: 58,
  statusBarHeight: 28,
  sidebarWidth: 64,
  sidebarExpandedWidth: 200,
  panelWidth: 320,
  touchTarget: 44, // 无障碍最小触控区域
} as const

// ── 便捷帮助函数 ──────────────────────────────────────────────────────────────
/** 根据场景获取完整主题色集 */
export const getScene = (key: SceneKey) => scenes[key]

/** 生成 rgba 阴影，用于按钮 hover */
export const sceneShadow = (key: SceneKey, opacity = 0.35) =>
  `0 4px 12px rgba(${scenes[key].shadowRgba}, ${opacity})`
