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
 * 业务逻辑（state / 缓存 / 鼠标事件 / 预加载）抽到 useDicomViewer。
 * 工具栏 UI 抽到 DicomViewerToolbar。本文件只剩容器 + 渲染区。
 *
 * 失去的能力（vs cornerstone3D）：3D / MPR / DICOM SR 标注 / 像素精确测距。
 * 这些都是重型阅片站才用的，临床医生 99% 工作不需要。
 */
import { useRef } from 'react'
import { Spin, Typography } from 'antd'
import { useDicomViewer } from '@/hooks/useDicomViewer'
import DicomViewerToolbar from './DicomViewerToolbar'

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

  const {
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
  } = useDicomViewer({
    studyId,
    pairs,
    initialIndex,
    preloadInstanceUids,
    preloadSeriesUids,
  })

  const containerRef = useRef<HTMLDivElement>(null)

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
      <DicomViewerToolbar
        activeTool={activeTool}
        setActiveTool={setActiveTool}
        totalFrames={pairs.length}
        currentFrame={currentFrame}
        resetView={resetView}
      />

      {/* 渲染区 */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          position: 'relative',
          minHeight: 360,
          overflow: 'hidden',
          // 光标语义化
          cursor: activeTool === 'pan' ? 'move' : activeTool === 'zoom' ? 'zoom-in' : 'ns-resize',
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
            <Text style={{ color: '#fff', fontSize: 11, marginLeft: 6 }}>加载中...</Text>
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
