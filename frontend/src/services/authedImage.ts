/**
 * 带鉴权的图片资源加载（services/authedImage.ts）
 *
 * 浏览器原生 <img src="..."> 不会自动带 Authorization 头，所以含 PHI 的
 * 图片接口（如 PACS 缩略图）必须走 fetch + blob URL 的方式才能补上鉴权。
 *
 * 提供两个对外能力：
 *   - fetchAuthedBlobUrl(url): 通用底层函数，返回临时 object URL；调用方必须在
 *                              用完后调用 URL.revokeObjectURL 释放，否则内存泄漏。
 *   - useAuthedImage(url):     React hook 语法糖，自动管理生命周期 + 取消逻辑，
 *                              组件卸载或 url 变化时自动 revoke 旧 objectURL。
 *
 * 历史背景：
 *   PACS thumbnail/dicom 端点曾经无鉴权（任何人凭 study_id 即可拖走 DICOM
 *   原始文件，含完整患者 PII）。补完后端鉴权后，前端 <img> 必须改用本工具
 *   才能正常加载——否则 401。
 */
import { useEffect, useState } from 'react'
import { useAuthStore } from '@/store/authStore'

/**
 * 用当前登录 token 拉取受保护图片，返回临时 object URL。
 * 调用方负责 URL.revokeObjectURL 释放，否则内存泄漏。
 */
export async function fetchAuthedBlobUrl(url: string): Promise<string> {
  const token = useAuthStore.getState().token
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/**
 * React hook：把受保护的图片 URL 转成可直接给 <img src> 用的 object URL。
 * url 为 null 时返回 src=null，便于 IMG 在 url 还没准备好时不报错。
 *
 * @returns { src, loading, error }
 *   src     : 可以直接赋给 <img src=...>，加载中/出错时为 null
 *   loading : true 表示正在 fetch
 *   error   : 加载失败（401/403/404/网络）时为 true
 */
export function useAuthedImage(url: string | null): {
  src: string | null
  loading: boolean
  error: boolean
} {
  const [src, setSrc] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    // url 为空：清空状态，不发请求
    if (!url) {
      setSrc(null)
      setLoading(false)
      setError(false)
      return
    }
    let cancelled = false
    let objectUrl: string | null = null
    setLoading(true)
    setError(false)

    fetchAuthedBlobUrl(url)
      .then(u => {
        if (cancelled) {
          // 组件已卸载/url 已变 → 释放新拿到的 URL，避免泄漏
          URL.revokeObjectURL(u)
          return
        }
        objectUrl = u
        setSrc(u)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError(true)
        setLoading(false)
      })

    // cleanup：组件卸载或 url 变化时执行
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [url])

  return { src, loading, error }
}
