/** 用户应看到真实依赖状态，而不是任意非空健康响应对应绿色横幅。 */
import { describe, expect, it } from 'vitest'
import { describeHealth } from './healthStatus'

describe('深度健康结果展示', () => {
  it.each(['missing', 'invalid', 'unavailable', 'error'])('AI状态%s不能显示正常', state => {
    expect(describeHealth({ status: 'degraded', deps: { db: 'ok', ai_credential: state } }, false).type).toBe('error')
  })
  it('其他供应商未验证时明确提示', () => {
    const result = describeHealth({ status: 'degraded', deps: { db: 'ok', ai_credential: 'unverified' } }, false)
    expect(result.type).toBe('warning')
    expect(result.text).toContain('未验证')
  })
  it('服务端降级但未识别具体依赖也不能报正常', () => {
    expect(describeHealth({ status: 'degraded', deps: { db: 'ok', ai_credential: 'ok' } }, false).type).toBe('error')
  })
  it('PACS故障明确显示', () => {
    const result = describeHealth({ status: 'degraded', deps: { db: 'ok', ai_credential: 'ok', orthanc: 'error' } }, false)
    expect(result.text).toContain('影像')
  })
  it('验证成功仅表示鉴权与余额通过，不宣称生成质量通过', () => {
    expect(describeHealth({ status: 'ok', deps: { db: 'ok', ai_credential: 'ok' } }, false).type).toBe('success')
  })
})
