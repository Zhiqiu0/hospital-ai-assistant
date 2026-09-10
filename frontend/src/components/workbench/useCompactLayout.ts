/**
 * 窄屏判定 hook（components/workbench/useCompactLayout.ts）
 *
 * 从 CollapsibleSide 拆出：项目约定组件文件只导出组件（react-refresh/
 * only-export-components），常量与 hook 放独立文件共享——与
 * recordView/viewableRecord.ts 的拆法同一口径。断点取值的理由见
 * CollapsibleSide 头注。
 */
import { useEffect, useState } from 'react'

export const COMPACT_BREAKPOINT = 1180

/** 当前视口是否属于"窄屏"（平板/分屏）。SSR 兜底为 false（本项目纯 CSR）。 */
export function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia(`(max-width: ${COMPACT_BREAKPOINT}px)`).matches
  )
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${COMPACT_BREAKPOINT}px)`)
    const onChange = (e: MediaQueryListEvent) => setCompact(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return compact
}
