/**
 * 批量开户弹窗（admin/users/BulkImportModal.tsx，2026-08-13）
 *
 * 用途：按医院信息科给的人员名单一次性建全院医生账号。
 *
 * 输入格式（每行一位医生，制表符或逗号分隔）：
 *     姓名, 工号1, 工号2, 工号3
 * 工号可有多个——同一医生的「本人门诊 / 本人住院 / 助理」工号全挂到同一账号，
 * HIS 推任一个都映射到本人，病历署名恒为本人姓名（医院硬要求：病历上不能出现
 * 助理名字）。第一个工号同时作为登录用户名。
 *
 * 流程：先「预检」（dry_run，不落库）看清哪些会建、哪些会跳过，确认无误再「正式导入」。
 */

import { useState } from 'react'
import { Modal, Input, Button, Table, Alert, Typography, Space, message } from 'antd'
import api from '@/services/api'

const { Paragraph, Text } = Typography

/** 单条导入结果（与后端 BulkImportResultItem 对应） */
interface ResultItem {
  real_name: string
  username: string
  codes: string[]
  status: 'created' | 'skipped_exists' | 'code_conflict' | 'error'
  message?: string
}

interface ImportResponse {
  total: number
  created: number
  skipped: number
  failed: number
  initial_password: string
  items: ResultItem[]
}

/** 状态 → 中文说明（管理员看得懂为止，不用暴露英文枚举） */
const STATUS_TEXT: Record<ResultItem['status'], string> = {
  created: '将创建',
  skipped_exists: '已存在，跳过',
  code_conflict: '工号被占用，跳过',
  error: '数据有误',
}

/** 把粘贴的文本解析成后端要的 items，非法行直接忽略（预检结果里会体现数量差） */
function parseRoster(text: string) {
  return text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const parts = line
        .split(/[,，\t]+/)
        .map(p => p.trim())
        .filter(Boolean)
      return { real_name: parts[0] || '', codes: parts.slice(1) }
    })
    .filter(item => item.real_name && item.codes.length > 0)
}

interface Props {
  open: boolean
  onClose: () => void
  onDone: () => void
}

export default function BulkImportModal({ open, onClose, onDone }: Props) {
  const [text, setText] = useState('')
  const [password, setPassword] = useState('MediScribe@2026')
  const [result, setResult] = useState<ImportResponse | null>(null)
  const [preview, setPreview] = useState(false) // 当前结果是不是预检（决定按钮文案）
  const [loading, setLoading] = useState(false)

  const submit = async (dryRun: boolean) => {
    const items = parseRoster(text)
    if (items.length === 0) {
      message.warning('没解析到有效行，每行需要「姓名 + 至少一个工号」')
      return
    }
    setLoading(true)
    try {
      const res = (await api.post('/admin/users/bulk-import', {
        items,
        initial_password: password,
        dry_run: dryRun,
      })) as ImportResponse
      setResult(res)
      setPreview(dryRun)
      if (!dryRun) {
        message.success(`导入完成：新建 ${res.created} 个账号`)
        onDone()
      }
    } finally {
      setLoading(false)
    }
  }

  const close = () => {
    setText('')
    setResult(null)
    setPreview(false)
    onClose()
  }

  return (
    <Modal
      open={open}
      title="批量开户"
      width={760}
      onCancel={close}
      footer={[
        <Button key="close" onClick={close}>
          关闭
        </Button>,
        <Button key="check" loading={loading} onClick={() => submit(true)}>
          预检（不落库）
        </Button>,
        <Button
          key="run"
          type="primary"
          loading={loading}
          // 强制先预检：批量建号是写操作，看过结果再落库，避免一把梭建错一堆账号
          disabled={!preview || !result}
          onClick={() => submit(false)}
        >
          确认导入
        </Button>,
      ]}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="每行一位医生：姓名, 工号1, 工号2, ..."
        description="同一医生的门诊/住院/助理工号请写在同一行——它们会挂到同一个账号，HIS 用任何一个工号推接诊，病历署名都是这位医生本人。第一个工号作为登录用户名。"
      />
      <Input.TextArea
        rows={8}
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={'汪来煜, 6069, 16029, 16039\n张三, 7001\n李四, 7002, 17002'}
        style={{ marginBottom: 12, fontFamily: 'monospace' }}
      />
      <Space style={{ marginBottom: 12 }}>
        <Text>统一初始密码：</Text>
        <Input
          value={password}
          onChange={e => setPassword(e.target.value)}
          style={{ width: 240 }}
        />
      </Space>
      <Paragraph type="secondary" style={{ fontSize: 12 }}>
        医生首次登录会被强制修改密码，改完之前看不到任何患者和病历，因此统一初始密码是安全的。
      </Paragraph>

      {result && (
        <>
          <Alert
            type={result.failed > 0 ? 'warning' : 'success'}
            style={{ margin: '12px 0' }}
            message={`${preview ? '预检' : '导入'}结果：共 ${result.total} 条，${
              preview ? '可建' : '已建'
            } ${result.created}，跳过 ${result.skipped}，有误 ${result.failed}`}
          />
          <Table
            size="small"
            rowKey={r => `${r.username}-${r.codes.join('-')}`}
            dataSource={result.items}
            pagination={{ pageSize: 8 }}
            columns={[
              { title: '姓名', dataIndex: 'real_name', width: 100 },
              { title: '登录用户名', dataIndex: 'username', width: 110 },
              {
                title: '工号',
                dataIndex: 'codes',
                render: (codes: string[]) => codes.join(' / '),
              },
              {
                title: '结果',
                dataIndex: 'status',
                width: 130,
                render: (s: ResultItem['status'], row) => (
                  <Text type={s === 'created' ? 'success' : 'warning'} title={row.message}>
                    {STATUS_TEXT[s]}
                  </Text>
                ),
              },
            ]}
          />
        </>
      )}
    </Modal>
  )
}
