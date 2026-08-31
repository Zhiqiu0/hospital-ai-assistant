/**
 * 重复患者档案合并面板（数据更正页 · 下半部分）
 *
 * 为什么需要它：老人无身份证、儿童留家长手机、代挂号——查重强键全 miss 时系统
 * 会新建档案。这是刻意取舍，但「可事后人工合并」这句话此前只写在代码注释里，
 * 功能并不存在。后果是既往史/过敏史分散在两份档案下，医生查复诊史只看得到
 * 一半——过敏史正是开药前工作台飘红警示的那个字段。
 *
 * 合并**不可逆**，所以这里强制两步：先预览人眼核对，再逐字输入姓名确认。
 */
import { useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, Space, Tag, message } from 'antd'
import api from '@/services/api'

interface Brief {
  id: string
  name: string
  gender: string | null
  birth_date: string | null
  id_card: string | null
  phone: string | null
  patient_no: string | null
  allergy_history: string | null
}

interface Preview {
  target: Brief
  source: Brief
  will_move: { encounters: number; imaging_studies: number }
  warnings: string[]
  confirm_hint: string
}

const briefItems = (b: Brief) => [
  { key: 'name', label: '姓名', children: b.name },
  { key: 'gender', label: '性别', children: b.gender || '—' },
  { key: 'birth', label: '出生日期', children: b.birth_date || '—' },
  { key: 'idc', label: '身份证', children: b.id_card || '—' },
  { key: 'phone', label: '手机号', children: b.phone || '—' },
  { key: 'no', label: '院内编号', children: b.patient_no || '—' },
  { key: 'allergy', label: '过敏史', children: b.allergy_history || '—' },
]

export default function PatientMergePanel() {
  const [targetId, setTargetId] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const doPreview = async () => {
    if (!targetId.trim() || !sourceId.trim()) {
      message.warning('两份档案的 ID 都要填')
      return
    }
    setBusy(true)
    try {
      const res = (await api.get(
        `/admin/patient-merge/preview?target_id=${encodeURIComponent(targetId.trim())}` +
          `&source_id=${encodeURIComponent(sourceId.trim())}`
      )) as Preview
      setPreview(res)
      setConfirmName('')
    } catch (e) {
      message.error('预览失败：' + ((e as { detail?: string })?.detail || '请重试'))
    } finally {
      setBusy(false)
    }
  }

  const doMerge = async () => {
    if (!preview) return
    if (!reason.trim()) {
      message.warning('请填写合并理由（进审计）')
      return
    }
    setBusy(true)
    try {
      const res = (await api.post('/admin/patient-merge', {
        target_id: preview.target.id,
        source_id: preview.source.id,
        confirm_name: confirmName.trim(),
        reason: reason.trim(),
      })) as { moved: { encounters: number; imaging_studies: number } }
      message.success(
        `合并完成：搬移接诊 ${res.moved.encounters} 条、影像 ${res.moved.imaging_studies} 项`
      )
      setPreview(null)
      setTargetId('')
      setSourceId('')
      setConfirmName('')
      setReason('')
    } catch (e) {
      message.error('合并失败：' + ((e as { detail?: string })?.detail || '请重试'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="重复档案合并" style={{ marginTop: 16 }}>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message="合并不可逆"
        description="误合并两个真实存在的人无法撤销。执行前请务必在预览里逐项核对身份证、出生日期与手机号。已签发病历上的患者署名不会被改动——那是签发瞬间冻结的法定内容。"
      />
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          addonBefore="保留档案 ID"
          style={{ width: 420 }}
          value={targetId}
          onChange={e => setTargetId(e.target.value)}
        />
        <Input
          addonBefore="被合并档案 ID"
          style={{ width: 420 }}
          value={sourceId}
          onChange={e => setSourceId(e.target.value)}
        />
        <Button onClick={doPreview} loading={busy}>
          预览
        </Button>
      </Space>

      {preview && (
        <div>
          {preview.warnings.length > 0 && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="这两份档案可能不是同一个人"
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {preview.warnings.map(w => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              }
            />
          )}
          <Space align="start" wrap size={16}>
            <Descriptions
              title={<Tag color="green">保留（数据并到这份）</Tag>}
              size="small"
              column={1}
              bordered
              items={briefItems(preview.target)}
              style={{ width: 380 }}
            />
            <Descriptions
              title={<Tag color="red">被合并（合并后隐藏）</Tag>}
              size="small"
              column={1}
              bordered
              items={briefItems(preview.source)}
              style={{ width: 380 }}
            />
          </Space>
          <p style={{ marginTop: 12 }}>
            将搬移：接诊 <strong>{preview.will_move.encounters}</strong> 条、影像{' '}
            <strong>{preview.will_move.imaging_studies}</strong> 项。
            档案字段只补空、不覆盖保留档案里已有的内容。
          </p>
          <Space wrap>
            <Input
              placeholder={`逐字输入「${preview.source.name}」以确认`}
              style={{ width: 260 }}
              value={confirmName}
              onChange={e => setConfirmName(e.target.value)}
            />
            <Input
              placeholder="合并理由（必填，进审计）"
              style={{ width: 320 }}
              value={reason}
              onChange={e => setReason(e.target.value)}
            />
            <Button
              type="primary"
              danger
              loading={busy}
              disabled={confirmName.trim() !== preview.source.name}
              onClick={doMerge}
            >
              执行合并
            </Button>
          </Space>
        </div>
      )}
    </Card>
  )
}
