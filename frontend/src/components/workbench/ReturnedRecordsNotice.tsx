/**
 * 质控退回提醒（components/workbench/ReturnedRecordsNotice.tsx，2026-08-22 退回闭环）
 *
 * 三级质控的最后一段：质控员"退回整改"后医生此前毫无感知。本组件在
 * 医生工作台（门诊/住院共用）顶部显示橙色横幅，点开抽屉看逐条整改意见。
 * 出清单条件与后端口径互为镜像：医生修订重签后该条自动消失
 * （重签同时会重新进入质控员的复核队列）。
 */
import { useCallback, useEffect, useState } from 'react'
import { Button, Drawer, Tag } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import api from '@/services/api'

interface ReturnedItem {
  record_id: string
  encounter_id: string
  record_type: string
  visit_type: string
  returned_at: string
  reviewer_name: string | null
  comment: string | null
}

const TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  emergency: '急诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程',
  course_record: '日常病程',
  senior_round: '上级查房',
  pre_op_summary: '术前小结',
  op_record: '手术记录',
  post_op_record: '术后病程',
  discharge_record: '出院记录',
}

/** 轮询间隔：5 分钟（退回不是分钟级急事，别给后端加压） */
const POLL_MS = 5 * 60 * 1000

export default function ReturnedRecordsNotice() {
  const [items, setItems] = useState<ReturnedItem[]>([])
  const [open, setOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = (await api.get('/medical-records/my-returned')) as unknown as ReturnedItem[]
      setItems(Array.isArray(res) ? res : [])
    } catch {
      /* 拉取失败静默——提醒是增强功能，不打扰主流程 */
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [load])

  if (items.length === 0) return null

  return (
    <>
      <div
        onClick={() => setOpen(true)}
        style={{
          background: '#fff7e6',
          borderBottom: '1px solid #ffd591',
          padding: '6px 16px',
          fontSize: 13,
          color: '#ad4e00',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <ExclamationCircleOutlined />
        <span>
          有 <b>{items.length}</b> 份病历被质控退回，请查看整改意见
        </span>
        <Button size="small" type="link" style={{ marginLeft: 'auto', padding: 0 }}>
          查看详情
        </Button>
      </div>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        width={520}
        title={`质控退回整改（${items.length} 份）`}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {items.map(it => (
            <div
              key={it.record_id}
              style={{
                border: '1px solid var(--border-subtle)',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 13,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <Tag color="orange">{TYPE_LABEL[it.record_type] || it.record_type}</Tag>
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>
                  {it.returned_at.replace('T', ' ').slice(0, 16)} · 复核人：
                  {it.reviewer_name || '—'}
                </span>
              </div>
              <div style={{ marginBottom: 8 }}>整改意见：{it.comment || '（未填写）'}</div>
              <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
                {it.visit_type === 'inpatient'
                  ? '整改方式：在住院工作台修订该文书并重新签发，重签后自动重新进入复核。'
                  : '整改方式：门急诊病历签发后不可直接修改，请联系管理员走病历修订通道。'}
              </div>
            </div>
          ))}
        </div>
      </Drawer>
    </>
  )
}
