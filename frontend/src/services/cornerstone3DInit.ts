/**
 * Cornerstone3D 一次性全局初始化（services/cornerstone3DInit.ts）
 *
 * R1 sprint E：把 PACS 的 DICOM viewer 从 canvas 升级到 cornerstone3D，
 * 支持原生 DICOM 解析、窗位窗宽、缩放、平移、滚动切片，且为后续 F-2 复诊
 * 比较 + F-3 标注预留生态接入点。
 *
 * 走 wadouri 协议 → 后端 `/api/v1/pacs/{study_id}/dicom/{instance_uid}` 拿
 * 原始 DCM 字节（应用层鉴权由 FastAPI 代理负责，前端只在 XHR 头里塞 Bearer
 * token）。
 */
import { init as csInit } from '@cornerstonejs/core'
import {
  init as csToolsInit,
  addTool,
  PanTool,
  ZoomTool,
  WindowLevelTool,
  StackScrollTool,
  LengthTool,
} from '@cornerstonejs/tools'
// 注意：default export 是个 namespace 对象（含 init/wadouri/wadors 等），
// 真正要调用的 init 在它下面，这里走命名导入更直观
import { init as dicomImageLoaderInit } from '@cornerstonejs/dicom-image-loader'

import { useAuthStore } from '@/store/authStore'

/** 全局只跑一次 */
let initialized = false
let initPromise: Promise<void> | null = null

export async function ensureCornerstone3D(): Promise<void> {
  if (initialized) return
  if (initPromise) return initPromise

  initPromise = (async () => {
    // 1) cornerstone core（WebGL renderer + viewport / cache 体系）
    await csInit()
    // 2) cornerstone tools（鼠标交互：缩放/平移/窗位窗宽 等）
    await csToolsInit()
    // 3) dicom-image-loader（wadouri / wadors 协议 + DICOM 解码 worker pool）
    dicomImageLoaderInit({
      // 解码并发数：CT/MR 切片多时能显著加速；不超过 CPU 核数避免反向劣化
      maxWebWorkers: Math.min(navigator.hardwareConcurrency || 2, 4),
      // 给每个 XHR 注入 Authorization 头；后端 FastAPI 代理需要 Bearer token
      // 注意：返回的 headers 会与 defaultHeaders 合并并实际写入 xhr
      beforeSend: () => {
        const token = useAuthStore.getState().token
        const headers: Record<string, string> = {
          // 后端 dicom 端点返回 application/dicom，明确声明避免某些 CDN 改 MIME
          Accept: 'application/dicom',
        }
        if (token) {
          headers.Authorization = `Bearer ${token}`
        }
        return headers
      },
    })

    // 4) 注册全局可用 tools；具体 viewport 通过 ToolGroup 选择性激活
    addTool(WindowLevelTool)
    addTool(PanTool)
    addTool(ZoomTool)
    addTool(StackScrollTool)
    addTool(LengthTool)

    initialized = true
  })()

  return initPromise
}

/** Tool 名称统一出口（避免组件层硬编码字符串） */
export const TOOL_NAMES = {
  windowLevel: WindowLevelTool.toolName,
  pan: PanTool.toolName,
  zoom: ZoomTool.toolName,
  stackScroll: StackScrollTool.toolName,
  length: LengthTool.toolName,
} as const

export type ToolName = (typeof TOOL_NAMES)[keyof typeof TOOL_NAMES]
