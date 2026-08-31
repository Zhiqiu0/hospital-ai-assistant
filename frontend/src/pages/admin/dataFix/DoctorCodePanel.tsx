/**
 * HIS 工号绑定管理面板（数据更正页 · 上半部分）
 *
 * 为什么需要它：医院给的是全院名单，混着自助机、护工、财务，批量开户把护工的
 * 工号挂到临床医生名下是会发生的。而 HIS 派单按工号定位归属且归属先于状态——
 * 不改绑就继续署错人名，停用错账号则该工号的推送一律被拒、那位医生的病人再也
 * 进不了系统。系统此前给出的提示是「请联系管理员改派」，而改派功能并不存在。
 */
import { useState } from 'react'
import { Button, Card, Input, Modal, Space, Table, Tag, message } from 'antd'
import api from '@/services/api'

interface CodeRow {
  id: string
  code: string
  note: string | null
  user_id: string
  username: string
  real_name: string
  role: string
  is_active: boolean
}

export default function DoctorCodePanel() {
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState<CodeRow[]>([])
  const [loading, setLoading] = useState(false)
  // 改绑弹窗：目标账号 ID + 理由（理由进审计，事后要能说清为什么改）
  const [reassign, setReassign] = useState<CodeRow | null>(null)
  const [targetUserId, setTargetUserId] = useState('')
  const [reason, setReason] = useState('')

  const load = async (code?: string) => {
    setLoading(true)
    try {
      const q = (code ?? keyword).trim()
      const res = (await api.get(
        `/admin/doctor-codes${q ? `?code=${encodeURIComponent(q)}` : ''}`
      )) as CodeRow[]
      setRows(res || [])
      if (q && (!res || res.length === 0)) {
        message.info(`工号 ${q} 未绑定任何账号（HIS 推它会被拒收）`)
      }
    } catch (e) {
      message.error('查询失败：' + ((e as { detail?: string })?.detail || '请重试'))
    } finally {
      setLoading(false)
    }
  }

  const doReassign = async () => {
    if (!reassign) return
    if (!targetUserId.trim() || !reason.trim()) {
      message.warning('目标账号 ID 与改绑理由都必须填写')
      return
    }
    try {
      await api.put(`/admin/doctor-codes/${encodeURIComponent(reassign.code)}/reassign`, {
        target_user_id: targetUserId.trim(),
        reason: reason.trim(),
      })
      message.success(`工号 ${reassign.code} 已改绑`)
      setReassign(null)
      setTargetUserId('')
      setReason('')
      void load(reassign.code)
    } catch (e) {
      // 后端会明确说明为什么拒绝（账号停用/非临床角色/已绑在该账号下），如实透传
      message.error('改绑失败：' + ((e as { detail?: string })?.detail || '请重试'))
    }
  }

  const doUnbind = (row: CodeRow) => {
    let why = ''
    Modal.confirm({
      title: `解绑工号 ${row.code}？`,
      content: (
        <div>
          <p style={{ marginBottom: 8 }}>
            当前绑定：{row.real_name}（{row.username}）。解绑后 HIS 再推这个工号会被
            拒收并带上工号——用于误导入的护工/自助机/财务工号。
          </p>
          <Input placeholder="解绑理由（必填，进审计）" onChange={e => (why = e.target.value)} />
        </div>
      ),
      okText: '确认解绑',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        if (!why.trim()) {
          message.warning('请填写解绑理由')
          return Promise.reject(new Error('no reason'))
        }
        try {
          await api.delete(
            `/admin/doctor-codes/${encodeURIComponent(row.code)}?reason=${encodeURIComponent(why.trim())}`
          )
          message.success('已解绑')
          void load()
        } catch (e) {
          message.error('解绑失败：' + ((e as { detail?: string })?.detail || '请重试'))
          return Promise.reject(e)
        }
      },
    })
  }

  return (
    <Card
      title="HIS 工号绑定"
      extra={
        <Space>
          <Input.Search
            placeholder="按工号精确查，留空查全部"
            allowClear
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            onSearch={() => void load()}
            style={{ width: 260 }}
          />
        </Space>
      }
    >
      <p style={{ color: '#888', marginTop: 0 }}>
        HIS 报「工号未注册 / 账号已停用」时先来这里查这个工号挂在谁名下。 改绑
        <strong>不影响历史病历署名</strong>——已签发的文书签发时是谁就永远是谁， 改绑只决定此后 HIS
        推送归哪位医生。
      </p>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '工号', dataIndex: 'code', width: 120 },
          { title: '备注', dataIndex: 'note', width: 130 },
          {
            title: '绑定账号',
            render: (_, r: CodeRow) => (
              <span>
                {r.real_name}（{r.username}） {!r.is_active && <Tag color="red">已停用</Tag>}
                {r.role !== 'doctor' && <Tag color="orange">{r.role}</Tag>}
              </span>
            ),
          },
          { title: '账号 ID', dataIndex: 'user_id', width: 300, ellipsis: true },
          {
            title: '操作',
            width: 150,
            render: (_, r: CodeRow) => (
              <Space>
                <Button size="small" onClick={() => setReassign(r)}>
                  改绑
                </Button>
                <Button size="small" danger onClick={() => doUnbind(r)}>
                  解绑
                </Button>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title={`改绑工号 ${reassign?.code ?? ''}`}
        open={!!reassign}
        onCancel={() => setReassign(null)}
        onOk={doReassign}
        okText="确认改绑"
      >
        <p>
          当前绑定：{reassign?.real_name}（{reassign?.username}）
        </p>
        <p style={{ color: '#888' }}>
          目标账号必须是<strong>在职的临床医生</strong>——推到停用账号或非医生角色， HIS
          照样会拒收接诊。账号 ID 可在「用户管理」里复制。
        </p>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="目标账号 ID（UUID）"
            value={targetUserId}
            onChange={e => setTargetUserId(e.target.value)}
          />
          <Input
            placeholder="改绑理由（必填，进审计）"
            value={reason}
            onChange={e => setReason(e.target.value)}
          />
        </Space>
      </Modal>
    </Card>
  )
}
