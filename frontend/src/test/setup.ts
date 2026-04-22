/**
 * Vitest 全局测试环境配置
 * - 扩展 jest-dom 断言（toBeInTheDocument 等）
 * - 每个测试后自动清理渲染的 DOM，避免状态泄漏
 * - mock 浏览器 API：matchMedia（AntD 响应式需要）/ ResizeObserver
 */
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})

// AntD 某些组件在 jsdom 里会查 window.matchMedia
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

// jsdom 不实现 ResizeObserver，AntD Table 等组件会用到
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as typeof ResizeObserver
}
