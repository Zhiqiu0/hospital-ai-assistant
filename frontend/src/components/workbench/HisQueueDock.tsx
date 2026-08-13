/**
 * HIS 叫号队列停靠组件（components/workbench/HisQueueDock.tsx）
 *
 * 叫号式工作台（2026-08-11 业务联动）：
 *   - 左下角悬浮按钮常驻，角标显示今日待接诊数，点开抽屉看完整队列
 *   - 新患者推送到达：提示音 + 右上角横幅通知（带"开始接诊"按钮）
 *   - 空闲（工作台无进行中接诊）→ 自动打开新患者；忙时只提醒不抢屏
 *   - 病历回写结果：成功绿 toast / 未回写黄条 / 失败红色通知（医生需手工兜底）
 *
 * 保险丝关闭（后端 503）时整个组件不渲染，纯 SaaS 部署零感知。
 */
import { useCallback, useState } from 'react'
import { App, Badge, Drawer, FloatButton, List, Tag } from 'antd'
import { BellOutlined, CheckCircleOutlined, SoundOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useHisQueue, type HisQueueEvent, type HisQueueItem } from '@/hooks/useHisQueue'

interface HisQueueDockProps {
  /** 打开某条接诊（接 useWorkbenchBase.handleResume） */
  onOpen: (item: { encounter_id: string; patient_name?: string }) => void
}

/** 叫号提示音：WebAudio 双音"叮咚"，免音频资源文件（浏览器未授权自动播放时静默失败） */
function playChime(): void {
  try {
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new AudioCtx()
    const play = (freq: number, start: number, dur: number) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = freq
      // 短促起音 + 指数衰减，听感像门铃不像警报
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + start)
      gain.gain.exponentialRampToValueAtTime(0.35, ctx.currentTime + start + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur)
      osc.connect(gain).connect(ctx.destination)
      osc.start(ctx.currentTime + start)
      osc.stop(ctx.currentTime + start + dur)
    }
    play(988, 0, 0.45) // 叮（B5）
    play(784, 0.18, 0.6) // 咚（G5）
    window.setTimeout(() => void ctx.close(), 1200)
  } catch {
    // 无声也不影响横幅提醒
  }
}

/** 出生日期 → 年龄文本（队列展示用，算不出返回空串） */
function ageText(birthDate?: string | null): string {
  if (!birthDate) return ''
  const birth = new Date(birthDate)
  if (Number.isNaN(birth.getTime())) return ''
  const age = Math.floor((Date.now() - birth.getTime()) / (365.25 * 24 * 3600 * 1000))
  return age >= 0 && age < 150 ? `${age}岁` : ''
}

export default function HisQueueDock({ onOpen }: HisQueueDockProps) {
  const { notification } = App.useApp()
  const [drawerOpen, setDrawerOpen] = useState(false)

  /** 新患者到达：空闲自动接诊，忙时提示音+横幅（不抢屏） */
  const handleAdmit = useCallback(
    (item: HisQueueItem) => {
      playChime()
      const busy = !!useActiveEncounterStore.getState().encounterId
      if (!busy) {
        // 空闲：直接打开工作台开始接诊
        onOpen({ encounter_id: item.encounter_id, patient_name: item.patient_name })
        message.info(`HIS 新患者「${item.patient_name}」已自动进入工作台`)
        return
      }
      const key = `his-admit-${item.encounter_id}`
      notification.open({
        key,
        message: `新患者：${item.patient_name}`,
        description: `${item.dept_name || ''} ${ageText(item.birth_date)} HIS 已推送接诊，当前患者处理完后可一键切换`,
        icon: <SoundOutlined style={{ color: '#0891B2' }} />,
        duration: 12,
        placement: 'topRight',
        btn: (
          <a
            onClick={() => {
              notification.destroy(key)
              onOpen({ encounter_id: item.encounter_id, patient_name: item.patient_name })
            }}
          >
            开始接诊
          </a>
        ),
      })
    },
    [notification, onOpen]
  )

  /** 回写结果：成功轻提示，失败重提示（医生需在 HIS 里人工兜底） */
  const handleWritebackResult = useCallback(
    (ev: HisQueueEvent) => {
      if (ev.ok) {
        message.success('病历已自动回写 HIS')
        return
      }
      if (ev.status === 'skipped') {
        message.warning('病历已签发，但 HIS 连接不在线，未能回写')
        return
      }
      notification.error({
        message: '病历回写 HIS 失败',
        description: `${ev.message || ev.status}。请在 HIS 中人工核对/补录本次病历。`,
        duration: 0, // 不自动消失，医生必须看到
        placement: 'topRight',
      })
    },
    [notification]
  )

  const { enabled, connected, items, refresh } = useHisQueue({
    onAdmit: handleAdmit,
    onWritebackResult: handleWritebackResult,
  })

  /** 失败重试：走既有手动回写端点，结果即时刷新队列（信封 code=0 才算成功） */
  const retryWriteback = async (item: HisQueueItem) => {
    try {
      const res = (await api.post(`/his/encounter/${item.encounter_id}/writeback`)) as {
        code: number
        message?: string
        data?: { status?: string; message?: string }
      }
      const st = res.data?.status
      if (res.code === 0 && st === 'dispatched') {
        // 2026-08-13：手动回写改走派发链路（多 worker 下由持有 WS 连接的进程
        // 执行），真实结果经 SSE writeback_result 推回，这里只确认已发起
        message.info(`已发起「${item.patient_name}」回写，结果稍后自动更新`)
      } else if (res.code === 0 && st === 'success') {
        message.success(`「${item.patient_name}」病历已回写 HIS`)
      } else if (res.code === 0 && st === 'skipped') {
        // skipped：HIS 连接不在线，属"未回写"而非"失败"——信封 message 恒为
        // "success"，不能拿它当失败原因展示（2026-08-11 审计修复）
        message.warning('HIS 连接不在线，暂未能回写，请稍后重试')
      } else {
        message.error(`回写仍失败：${res.data?.message || res.message || st || '未知原因'}`)
      }
    } catch {
      message.error('回写请求失败，请稍后重试')
    }
    void refresh()
  }

  if (!enabled) return null // 保险丝关闭：纯 SaaS 模式不渲染任何入口

  const waiting = items.filter(x => x.status === 'in_progress')

  return (
    <>
      <FloatButton
        type={waiting.length > 0 ? 'primary' : 'default'}
        badge={{ count: waiting.length, overflowCount: 99 }}
        icon={<BellOutlined />}
        tooltip="HIS 今日接诊队列"
        style={{ insetInlineStart: 24, insetBlockEnd: 48 }}
        onClick={() => {
          setDrawerOpen(true)
          // 开抽屉时重拉队列：接诊在本页被取消/签发后，SSE 不推该类变更，
          // 以 DB 为准修正角标与列表（如取消后角标残留）
          void refresh()
        }}
      />
      <Drawer
        title={
          <span>
            今日接诊队列
            <Badge
              status={connected ? 'success' : 'error'}
              text={connected ? '实时连接' : '连接中断（自动重连中）'}
              style={{ marginLeft: 12, fontSize: 12, fontWeight: 'normal' }}
            />
          </span>
        }
        placement="left"
        width={360}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      >
        <List
          dataSource={items}
          locale={{ emptyText: '今日暂无 HIS 推送的接诊' }}
          renderItem={item => (
            <List.Item
              style={{ cursor: 'pointer', padding: '10px 4px' }}
              onClick={() => {
                setDrawerOpen(false)
                onOpen({ encounter_id: item.encounter_id, patient_name: item.patient_name })
              }}
            >
              <List.Item.Meta
                avatar={
                  item.status === 'completed' ? (
                    <CheckCircleOutlined style={{ fontSize: 20, color: '#52c41a' }} />
                  ) : (
                    <Badge status="processing" />
                  )
                }
                title={
                  <span>
                    {item.patient_name}
                    <span style={{ marginLeft: 8, color: 'var(--text-3)', fontSize: 12 }}>
                      {item.gender || ''} {ageText(item.birth_date)}
                    </span>
                    {item.is_first_visit === false && (
                      <Tag style={{ marginLeft: 6 }} color="blue">
                        复诊
                      </Tag>
                    )}
                  </span>
                }
                description={
                  <span style={{ fontSize: 12 }}>
                    {item.dept_name || ''}
                    {item.visited_at
                      ? ` · ${new Date(item.visited_at).toLocaleTimeString('zh-CN', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}`
                      : ''}
                    {item.status === 'completed' ? ' · 已签发' : ' · 待接诊'}
                    {item.writeback_status === 'success' && (
                      <Tag color="green" style={{ marginLeft: 6 }}>
                        已回写HIS
                      </Tag>
                    )}
                    {item.writeback_status && item.writeback_status !== 'success' && (
                      <>
                        <Tag color="red" style={{ marginLeft: 6 }}>
                          {item.writeback_status === 'skipped' ? '未回写' : '回写失败'}
                        </Tag>
                        <a
                          onClick={e => {
                            e.stopPropagation() // 别触发整行的"打开接诊"
                            void retryWriteback(item)
                          }}
                        >
                          重试
                        </a>
                      </>
                    )}
                  </span>
                }
              />
            </List.Item>
          )}
        />
      </Drawer>
    </>
  )
}
