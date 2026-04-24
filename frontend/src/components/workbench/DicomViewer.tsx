/**
 * DICOM 影像查看器（DicomViewer.tsx）
 * 基于 Canvas 渲染缩略图，支持窗位（WC）/窗宽（WW）拖动调节。
 *
 * 鉴权说明：
 *   后端 thumbnail 端点要求 Authorization 头（修复 PHI 泄露漏洞），
 *   原生 <img>/Image() 不会自动带 token，所以走 fetchAuthedBlobUrl
 *   先拿到 blob URL，再喂给 Image+canvas。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Spin, Typography } from 'antd'
import { fetchAuthedBlobUrl } from '@/services/authedImage'

const { Text } = Typography

interface Props {
  studyId: string
  filename: string
}

export default function DicomViewer({ studyId, filename }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [wc, setWc] = useState(50)
  const [ww, setWw] = useState(350)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadImage = useCallback(
    (wcVal: number, wwVal: number, customWin: boolean) => {
      if (!filename) return
      setLoading(true)
      setError('')
      const url = customWin
        ? `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(filename)}?wc=${wcVal}&ww=${wwVal}`
        : `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(filename)}`

      // 走鉴权 fetch + blob URL，避免 <img>/Image() 不带 token 导致 401
      let objectUrl: string | null = null
      fetchAuthedBlobUrl(url)
        .then(u => {
          objectUrl = u
          const img = new Image()
          img.onload = () => {
            if (canvasRef.current) {
              const canvas = canvasRef.current
              canvas.width = img.width
              canvas.height = img.height
              canvas.getContext('2d')?.drawImage(img, 0, 0)
            }
            setLoading(false)
            // canvas 已经持有像素数据，blob URL 可立即释放
            if (objectUrl) URL.revokeObjectURL(objectUrl)
          }
          img.onerror = () => {
            setError('影像加载失败')
            setLoading(false)
            if (objectUrl) URL.revokeObjectURL(objectUrl)
          }
          img.src = u
        })
        .catch(() => {
          setError('影像加载失败')
          setLoading(false)
        })
    },
    [studyId, filename]
  )

  useEffect(() => {
    setWc(50)
    setWw(350)
    loadImage(50, 350, false)
  }, [studyId, filename])

  const handleWcChange = (val: number) => {
    setWc(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadImage(val, ww, true), 400)
  }

  const handleWwChange = (val: number) => {
    setWw(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadImage(wc, val, true), 400)
  }

  return (
    <div
      style={{
        background: '#000',
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative',
        minHeight: 400,
      }}
    >
      {loading && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Spin tip="加载影像..." />
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
          }}
        >
          <Text style={{ color: 'var(--surface)' }}>{error}</Text>
        </div>
      )}
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block', maxHeight: 480 }}
      />
      <div
        style={{
          padding: '8px 12px',
          background: '#111',
          display: 'flex',
          gap: 16,
          alignItems: 'center',
        }}
      >
        <Text style={{ color: '#999', fontSize: 12 }}>窗位(WC)</Text>
        <input
          type="range"
          min={-200}
          max={400}
          value={wc}
          onChange={e => handleWcChange(Number(e.target.value))}
          style={{ flex: 1 }}
        />
        <Text style={{ color: 'var(--surface)', fontSize: 12, minWidth: 30 }}>{wc}</Text>
        <Text style={{ color: '#999', fontSize: 12 }}>窗宽(WW)</Text>
        <input
          type="range"
          min={1}
          max={2000}
          value={ww}
          onChange={e => handleWwChange(Number(e.target.value))}
          style={{ flex: 1 }}
        />
        <Text style={{ color: 'var(--surface)', fontSize: 12, minWidth: 40 }}>{ww}</Text>
      </div>
    </div>
  )
}
