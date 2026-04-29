/**
 * 受鉴权 PACS 缩略图组件（pages/pacs/AuthedThumbnail.tsx）
 *
 * R1 后路径参数为 SOPInstanceUID（DICOM 标准），不是文件名。
 * 后端已要求 Authorization 头（修复 PHI 泄露漏洞），
 * 这里用 useAuthedImage 把响应转成 blob URL 喂给原生 <img>。
 *
 * IntersectionObserver lazy-fetch：未进入视口的缩略图不发请求。
 * rootMargin=50px 视口边缘提前加载（滚动时不至于太突兀）。
 * 滚动时图按需补，比预加载远端图更重要——后端单帧 0.6s + 6 路并发，
 * 一屏 16 张图 ~2s 出齐，预加载只会把后面的请求排队压死前面的。
 */
import { useEffect, useRef, useState } from 'react'
import { useAuthedImage } from '@/services/authedImage'

interface AuthedThumbnailProps {
  studyId: string
  instanceUid: string
  /** 可选：传上来后端免一次反查（537 帧 study 加载从分钟级降到秒级） */
  seriesUid?: string
  style?: React.CSSProperties
}

export default function AuthedThumbnail({
  studyId,
  instanceUid,
  seriesUid,
  style,
}: AuthedThumbnailProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = containerRef.current
    if (!el || inView) return
    const io = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setInView(true)
          io.disconnect()
        }
      },
      { rootMargin: '50px' }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [inView])

  const url =
    inView &&
    (seriesUid
      ? `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(instanceUid)}?series_uid=${encodeURIComponent(seriesUid)}`
      : `/api/v1/pacs/${studyId}/thumbnail/${encodeURIComponent(instanceUid)}`)

  const { src, error } = useAuthedImage(url || null)
  return (
    <div ref={containerRef} style={style}>
      {error ? (
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#888',
            fontSize: 11,
            background: '#222',
          }}
        >
          加载失败
        </div>
      ) : src ? (
        <img
          src={src}
          alt={instanceUid.slice(-12)}
          style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
        />
      ) : null}
    </div>
  )
}
