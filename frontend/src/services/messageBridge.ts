/**
 * 消息桥（services/messageBridge.ts）
 *
 * 为什么需要：
 *   antd v5 静态 `import { message } from 'antd'` 不消费 React 上下文，即使
 *   外层套了 `<App>`，静态 message 仍走"独立 holder"路径——v5.4 之后该路径
 *   被官方判定为"无 ConfigProvider 时不渲染"，导致生产构建里所有 toast 静默
 *   失败（dev 控制台 warn："Static function can not consume context...
 *   Please use 'App' component instead."）。
 *
 * 工程目标：
 *   - 保留 29 个调用方现有 `import { message } from '...'` 的写法，单点替换
 *     import 源；不强制所有 hook / store 都改成 `App.useApp()`（非组件无法用 hook）
 *   - 真实 message API 由 <AntApp> 内的 MessageBinder 组件在挂载时注入
 *
 * 调用约定：
 *   消费方：`import { message } from '@/services/messageBridge'`
 *   注入方：main.tsx 的 MessageBinder 在 mount 时调 bindMessageApi
 *
 * 注入前的 fallback：
 *   绑定前的调用（理论上不会发生——AntApp 同步挂载，业务调用都晚于挂载）
 *   走 console.warn 兜底，dev 环境立刻被看见，prod 不挂掉主流程。
 */

import type { MessageInstance } from 'antd/es/message/interface'

let _api: MessageInstance | null = null

/** 由 main.tsx 的 MessageBinder 注入真实 message api */
export function bindMessageApi(api: MessageInstance): void {
  _api = api
}

type MessageMethod = (...args: unknown[]) => unknown

function proxy(method: keyof MessageInstance): MessageMethod {
  return (...args: unknown[]) => {
    if (_api) {
      // antd v5 message 实例的方法签名形式不一，统一 any-cast 转发
      return (_api[method] as unknown as MessageMethod)(...args)
    }
    if (import.meta.env.DEV) {
      console.warn(
        `[messageBridge] message.${String(method)}() 在 AntApp 挂载前被调用，已跳过`,
        ...args
      )
    }
    return undefined
  }
}

/** 全站统一使用的 message 对象，签名跟 antd 的 message 一致 */
export const message = {
  success: proxy('success'),
  error: proxy('error'),
  warning: proxy('warning'),
  info: proxy('info'),
  loading: proxy('loading'),
  open: proxy('open'),
  destroy: proxy('destroy'),
}
