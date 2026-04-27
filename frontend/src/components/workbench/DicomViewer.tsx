/**
 * DICOM 影像查看器（DicomViewer.tsx）
 *
 * 优化 3：完全砍掉 cornerstone3D，改用 backend 渲染好的高清 JPEG +
 * 浏览器原生 <img> 显示。市面医院 PACS Web 端的标配做法。
 *
 * 数据流：
 *   <img src="/api/v1/pacs/{study_id}/preview/{instance_uid}?...">
 *      ↓
 *   后端 Redis 命中 → 直接返 JPEG（~30KB, 5ms）
 *   后端 Redis 未命中 → 拉 Orthanc raw DCM + pydicom 渲染 + 写 Redis
 *      ↓
 *   浏览器原生 JPEG 解码 + 渲染（瞬时）
 *
 * 工具栏：
 *   - 窗位窗宽：拖拽鼠标 → debounce 触发后端重渲染（带 wc/ww 参数）
 *   - 缩放/平移：CSS transform，瞬时响应（不发请求）
 *   - 重置：清状态回到初始
 *   - 滚轮翻片：切换 instanceUid，多帧 stack 场景用
 *
 * 失去的能力（vs cornerstone3D）：3D / MPR / DICOM SR 标注 / 像素精确测距。
 * 这些都是重型阅片站才用的，临床医生 99% 工作不需要——未来真要做 3D 重建
 * 时再装回 cornerstone3D 不晚。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Spin, Typography, Space, Button, Tooltip } from 'antd'
import {
  DragOutlined,
  ZoomInOutlined,
  BulbOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { fetchAuthedBlobUrl } from '@/services/authedImage'

const { Text } = Typography

interface Props {
  studyId: string
  /** 单帧场景：传一个 SOPInstanceUID */
  instanceUid?: string
  /** 单帧场景对应的 series UID（可选，传上来后端免一次反查） */
  seriesUid?: string
  /** 多帧场景：传整个 stack 的 SOPInstanceUID 数组（按显示顺序） */
  instanceUids?: string[]
  /** 多帧场景对应的 series UID 数组（按 index 与 instanceUids 对齐） */
  seriesUids?: string[]
  /** 多帧场景下默认显示第几帧（默认 0） */
  initialIndex?: number
  /** 预加载提示：传上来后 DicomViewer mount 时后台拉这些帧的 preview 到内存
   *  缓存，用户切换帧时瞬时显示（不再等 200ms 网络往返）。
   *  典型用法：把当前 study 选中的所有帧 UID 传过来 */
  preloadInstanceUids?: string[]
  /** 预加载帧对应的 series UID 数组（按 index 对齐） */
  preloadSeriesUids?: string[]
}

type ToolMode = 'window' | 'zoom' | 'pan'

export default function DicomViewer({
  studyId,
  instanceUid,
  seriesUid,
  instanceUids,
  seriesUids,
  initialIndex = 0,
  preloadInstanceUids,
  preloadSeriesUids,
}: Props) {
  // 把单帧/多帧 props 统一成 (instance, series) 对的数组
  const pairs: Array<{ instance: string; series?: string }> =
    instanceUids && instanceUids.length > 0
      ? instanceUids.map((u, i) => ({ instance: u, series: seriesUids?.[i] }))
      : instanceUid
        ? [{ instance: instanceUid, series: seriesUid }]
        : []

  const [currentFrame, setCurrentFrame] = useState(
    Math.min(initialIndex, Math.max(pairs.length - 1, 0)),
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
  const containerRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ startX: number; startY: number; baseWc: number; baseWw: number; basePanX: number; basePanY: number } | null>(null)
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
    [studyId, cur],
  )

  // 加载图片（先查内存 cache，未命中走 fetch + 鉴权 → blob URL → 写 cache）
  // cache 命中时切换帧 < 10ms，无 loading 闪烁
  const loadImage = useCallback(
    (url: string) => {
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
    },
    [],
  )

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 预加载：mount 时后台拉所有 preloadInstanceUids 对应的 preview 到 cache
  // 用户切换帧时直接命中 cache，瞬时显示
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
    // 鼠标事件没有 pointerId，setPointerCapture 不需要在这里调用
    // （拖出元素后 onMouseLeave 会清掉 dragRef，体验已足够好）
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

  return (
    <div
      style={{
        background: '#000',
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative',
        // 撑满父容器（PacsWorkbenchPage 的 Card body）让图能尽量大
        height: '100%',
        minHeight: 480,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 工具栏 */}
      <div
        style={{
          padding: '6px 10px',
          background: '#181818',
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          borderBottom: '1px solid #222',
        }}
      >
        <Space size={4}>
          <Tooltip title="窗位窗宽（左键上下/左右拖）">
            <Button
              size="small"
              type={activeTool === 'window' ? 'primary' : 'default'}
              icon={<BulbOutlined />}
              onClick={() => setActiveTool('window')}
            />
          </Tooltip>
          <Tooltip title="缩放（左键上下拖）">
            <Button
              size="small"
              type={activeTool === 'zoom' ? 'primary' : 'default'}
              icon={<ZoomInOutlined />}
              onClick={() => setActiveTool('zoom')}
            />
          </Tooltip>
          <Tooltip title="平移（左键拖拽）">
            <Button
              size="small"
              type={activeTool === 'pan' ? 'primary' : 'default'}
              icon={<DragOutlined />}
              onClick={() => setActiveTool('pan')}
            />
          </Tooltip>
        </Space>
        <div style={{ flex: 1 }} />
        {pairs.length > 1 && (
          <Text style={{ color: '#999', fontSize: 12 }}>
            {currentFrame + 1} / {pairs.length}
          </Text>
        )}
        <Tooltip title="重置（窗位/缩放/平移）">
          <Button size="small" icon={<ReloadOutlined />} onClick={resetView} />
        </Tooltip>
      </div>

      {/* 渲染区 */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          position: 'relative',
          minHeight: 360,
          overflow: 'hidden',
          // 光标语义化：窗位窗宽是上下/左右拖动（ns-resize），缩放是放大镜，平移是移动手
          cursor:
            activeTool === 'pan'
              ? 'move'
              : activeTool === 'zoom'
                ? 'zoom-in'
                : 'ns-resize',
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onWheel={onWheel}
        onContextMenu={e => e.preventDefault()}
      >
        {imageSrc && (
          <img
            src={imageSrc}
            alt={cur?.instance.slice(-12) || 'preview'}
            draggable={false}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'contain',
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: 'center center',
              userSelect: 'none',
              pointerEvents: 'none',
            }}
          />
        )}
        {loading && (
          <div
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              display: 'flex',
              alignItems: 'center',
              zIndex: 5,
              pointerEvents: 'none',
              background: 'rgba(0,0,0,0.5)',
              padding: '4px 10px',
              borderRadius: 12,
            }}
          >
            <Spin size="small" />
            <Text style={{ color: '#fff', fontSize: 11, marginLeft: 6 }}>
              加载中...
            </Text>
          </div>
        )}
        {error && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 6,
            }}
          >
            <Text style={{ color: '#fff' }}>{error}</Text>
          </div>
        )}
        {/* 调试浮层：拖拽时显示当前 wc/ww 数值 */}
        {(wc !== null || ww !== null) && (
          <div
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              color: '#fff',
              background: 'rgba(0,0,0,0.5)',
              padding: '2px 8px',
              borderRadius: 4,
              fontSize: 11,
              fontFamily: 'monospace',
              pointerEvents: 'none',
            }}
          >
            WC: {Math.round(wc ?? 50)} / WW: {Math.round(ww ?? 350)}
          </div>
        )}
      </div>
    </div>
  )
}
