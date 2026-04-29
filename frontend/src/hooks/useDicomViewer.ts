/**
 * DICOM 影像查看器业务逻辑 hook（hooks/useDicomViewer.ts）
 *
 * 抽出来供 DicomViewer 组件使用。封装了：
 *   - state：currentFrame / activeTool / wc / ww / zoom / pan / imageSrc / loading
 *   - 内存缓存：preview URL → blob URL（unmount 时统一释放）
 *   - URL 构造 + 鉴权图片加载
 *   - 鼠标拖拽（窗位窗宽 / 缩放 / 平移）
 *   - 滚轮翻片
 *   - 预加载（4 路并发后台拉所有帧）
 *   - 重置视图
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAuthedBlobUrl } from '@/services/authedImage'

export type ToolMode = 'window' | 'zoom' | 'pan'

interface UseDicomViewerOptions {
  studyId: string
  pairs: Array<{ instance: string; series?: string }>
  initialIndex: number
  preloadInstanceUids?: string[]
  preloadSeriesUids?: string[]
}

export function useDicomViewer({
  studyId,
  pairs,
  initialIndex,
  preloadInstanceUids,
  preloadSeriesUids,
}: UseDicomViewerOptions) {
  const [currentFrame, setCurrentFrame] = useState(
    Math.min(initialIndex, Math.max(pairs.length - 1, 0))
  )
  const [activeTool, setActiveTool] = useState<ToolMode>('window')
  // 窗位窗宽（拖拽实时改，debounce 后调后端重渲染）
  const [wc, setWc] = useState<number | null>(null)
  const [ww, setWw] = useState<number | null>(null)
  // 缩放/平移（CSS transform，瞬时响应）
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [imageSrc, setImageSrc] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const cur = pairs[currentFrame]
  const dragRef = useRef<{
    startX: number
    startY: number
    baseWc: number
    baseWw: number
    basePanX: number
    basePanY: number
  } | null>(null)
  const pendingUrlRef = useRef<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // 内存缓存：preview URL → blob URL。命中时切换帧瞬时（< 10ms）不发请求
  // unmount 时统一释放所有 blob URL，避免内存泄漏
  const imageCacheRef = useRef<Map<string, string>>(new Map())

  // 构造 preview URL
  const buildUrl = useCallback(
    (wcVal: number | null, wwVal: number | null) => {
      if (!cur) return null
      const params = new URLSearchParams()
      if (cur.series) params.set('series_uid', cur.series)
      if (wcVal !== null && wwVal !== null) {
        params.set('wc', String(wcVal))
        params.set('ww', String(wwVal))
      }
      const qs = params.toString()
      return `/api/v1/pacs/${studyId}/preview/${encodeURIComponent(cur.instance)}${qs ? '?' + qs : ''}`
    },
    [studyId, cur]
  )

  // 加载图片（先查内存 cache，未命中走 fetch + 鉴权 → blob URL → 写 cache）
  const loadImage = useCallback((url: string) => {
    pendingUrlRef.current = url
    const cached = imageCacheRef.current.get(url)
    if (cached) {
      setImageSrc(cached)
      setLoading(false)
      setError('')
      return
    }
    setLoading(true)
    setError('')
    fetchAuthedBlobUrl(url)
      .then(u => {
        // 加载期间帧切换 / 组件卸载 → 立即释放新 URL，避免泄漏
        if (pendingUrlRef.current !== url) {
          URL.revokeObjectURL(u)
          return
        }
        // 写缓存（unmount 时统一 revoke），同 URL 二次进入直接命中
        imageCacheRef.current.set(url, u)
        setImageSrc(u)
        setLoading(false)
      })
      .catch(() => {
        if (pendingUrlRef.current === url) {
          setError('影像加载失败')
          setLoading(false)
        }
      })
  }, [])

  // 帧切换 / studyId 变化 → 重新加载
  useEffect(() => {
    if (!cur) return
    setWc(null)
    setWw(null)
    const url = buildUrl(null, null)
    if (url) loadImage(url)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId, cur?.instance])

  // 组件卸载：释放所有 blob URL（cache + 当前显示的）
  useEffect(() => {
    const cache = imageCacheRef.current
    return () => {
      cache.forEach(blobUrl => URL.revokeObjectURL(blobUrl))
      cache.clear()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  // 预加载：mount 时后台拉所有 preloadInstanceUids 对应的 preview 到 cache
  useEffect(() => {
    if (!preloadInstanceUids || preloadInstanceUids.length === 0) return
    const ids = preloadInstanceUids
    const seriesArr = preloadSeriesUids || []
    let cancelled = false

    // 限制并发 4 路（不抢主帧请求资源）
    const concurrency = 4
    let idx = 0
    const cache = imageCacheRef.current

    async function worker() {
      while (!cancelled && idx < ids.length) {
        const i = idx++
        const iuid = ids[i]
        const suid = seriesArr[i]
        const params = new URLSearchParams()
        if (suid) params.set('series_uid', suid)
        const qs = params.toString()
        const url = `/api/v1/pacs/${studyId}/preview/${encodeURIComponent(iuid)}${qs ? '?' + qs : ''}`
        if (cache.has(url)) continue
        try {
          const blobUrl = await fetchAuthedBlobUrl(url)
          if (cancelled) {
            URL.revokeObjectURL(blobUrl)
            return
          }
          cache.set(url, blobUrl)
        } catch {
          // 单帧预加载失败不阻断后续
        }
      }
    }
    const workers = Array.from({ length: concurrency }, () => worker())
    Promise.all(workers).catch(() => {})

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId, preloadInstanceUids?.join('|')])

  // 鼠标事件：根据 activeTool 调窗位窗宽 / 缩放 / 平移
  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      baseWc: wc ?? 50,
      baseWw: ww ?? 350,
      basePanX: pan.x,
      basePanY: pan.y,
    }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    if (activeTool === 'window') {
      // 上下拖：调窗位（亮度）；左右拖：调窗宽（对比度）
      const newWc = dragRef.current.baseWc + dy
      const newWw = Math.max(1, dragRef.current.baseWw + dx)
      setWc(newWc)
      setWw(newWw)
      // debounce 触发后端重渲染（避免每像素都打请求）
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        const url = buildUrl(newWc, newWw)
        if (url) loadImage(url)
      }, 300)
    } else if (activeTool === 'pan') {
      setPan({
        x: dragRef.current.basePanX + dx,
        y: dragRef.current.basePanY + dy,
      })
    } else if (activeTool === 'zoom') {
      const factor = 1 + dy * -0.003
      setZoom(z => Math.max(0.1, Math.min(8, z * factor)))
      // 重置 dragRef 让缩放是相对的
      dragRef.current.startY = e.clientY
    }
  }
  const onMouseUp = () => {
    dragRef.current = null
  }

  // 滚轮：多帧切换上一帧/下一帧
  const onWheel = (e: React.WheelEvent) => {
    if (pairs.length <= 1) return
    e.preventDefault()
    setCurrentFrame(idx => {
      const next = e.deltaY > 0 ? idx + 1 : idx - 1
      return Math.max(0, Math.min(pairs.length - 1, next))
    })
  }

  // 重置：窗位窗宽 + 缩放 + 平移
  const resetView = () => {
    setWc(null)
    setWw(null)
    setZoom(1)
    setPan({ x: 0, y: 0 })
    const url = buildUrl(null, null)
    if (url) loadImage(url)
  }

  return {
    cur,
    currentFrame,
    activeTool,
    setActiveTool,
    wc,
    ww,
    zoom,
    pan,
    imageSrc,
    loading,
    error,
    onMouseDown,
    onMouseMove,
    onMouseUp,
    onWheel,
    resetView,
  }
}
