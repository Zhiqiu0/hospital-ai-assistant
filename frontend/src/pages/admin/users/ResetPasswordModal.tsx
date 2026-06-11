/**
 * 重置密码弹窗（pages/admin/users/ResetPasswordModal.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 UsersPage.tsx 抽出（2026-05-03 原始功能）。
 * 密码原文不可"看"——bcrypt 单向哈希。管理员只能"重置"：手输或一键生成强随机串，
 * 弹窗展示新密码一次（带"复制"按钮），关闭后再也看不到。
 * 真实场景下应该再加"用户首次登录强制改密码"的标志位，本期 MVP 暂不强制。
 *
 * 自包含组件：新密码状态、随机生成、复制、调 reset-password API 全在本组件内，
 * 父组件只传 user（打开目标，null=关闭）和 onClose。
 */
import { useEffect, useState } from 'react'
import { Modal, Input, Button, Tag } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { message } from '@/services/messageBridge'
import api from '@/services/api'

/**
 * 生成强随机密码（默认 12 位，含字母数字大小写）。
 * 仅在重置密码弹窗里给管理员一个起点，管理员可手动修改。
 * 不引入 third-party 依赖，使用 crypto.getRandomValues 保证随机性。
 */
function generateRandomPassword(length = 12): string {
  const charset = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789' // 去除易混淆的 I,L,O,1,0
  const arr = new Uint32Array(length)
  crypto.getRandomValues(arr)
  return Array.from(arr, n => charset[n % charset.length]).join('')
}

interface ResetPasswordModalProps {
  /** 重置目标用户；null = 关闭弹窗 */
  user: { id: string; username: string } | null
  /** 关闭回调（父组件负责清空 user） */
  onClose: () => void
}

export default function ResetPasswordModal({ user, onClose }: ResetPasswordModalProps) {
  const [newPassword, setNewPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // 每次打开（user 变化且非空）时默认生成 12 位强随机密码；管理员可在弹窗内修改
  useEffect(() => {
    if (user) setNewPassword(generateRandomPassword(12))
    else setNewPassword('')
  }, [user])

  const submitReset = async () => {
    if (!user || !newPassword || newPassword.length < 6) {
      message.warning('密码至少 6 位')
      return
    }
    setSubmitting(true)
    try {
      await api.post(`/admin/users/${user.id}/reset-password`, {
        new_password: newPassword,
      })
      message.success('密码已重置，请将新密码告知用户')
      // 不立即关弹窗，让管理员有机会复制；点"知道了"才关
    } catch (e: unknown) {
      const detail = (e as { detail?: string })?.detail
      message.error(detail || '重置失败')
    } finally {
      setSubmitting(false)
    }
  }

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(newPassword)
      message.success('已复制到剪贴板')
    } catch {
      message.warning('复制失败，请手动选中复制')
    }
  }

  return (
    <Modal
      title="重置密码"
      open={!!user}
      onCancel={onClose}
      okText="确认重置"
      cancelText="取消"
      okButtonProps={{ loading: submitting }}
      onOk={submitReset}
      destroyOnHidden
      width={460}
    >
      <div style={{ marginBottom: 12, color: 'var(--text-3)', fontSize: 13 }}>
        为用户 <Tag>{user?.username}</Tag> 重置密码：
      </div>
      <Input.Password
        value={newPassword}
        onChange={e => setNewPassword(e.target.value)}
        placeholder="新密码（至少 6 位）"
        addonAfter={
          <Button
            type="text"
            size="small"
            icon={<CopyOutlined />}
            onClick={copyPassword}
            title="复制密码到剪贴板"
          />
        }
      />
      <div style={{ marginTop: 8, fontSize: 12 }}>
        <Button
          type="link"
          size="small"
          style={{ padding: 0 }}
          onClick={() => setNewPassword(generateRandomPassword(12))}
        >
          重新生成随机密码
        </Button>
      </div>
      <div
        style={{
          marginTop: 12,
          padding: '8px 10px',
          background: '#fef9c3',
          border: '1px solid #fde047',
          borderRadius: 6,
          fontSize: 12,
          color: '#854d0e',
        }}
      >
        ⚠️ 提交后请<b>立即复制</b>新密码并告知用户。关闭弹窗后系统不再保留原文，只存哈希值。
      </div>
    </Modal>
  )
}
