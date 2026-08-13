/**
 * 强制首次改密弹窗（components/ForcePasswordChangeModal.tsx，2026-08-13）
 *
 * 背景：批量开户给全院医生建号时用统一初始密码（上百人逐个分发不同密码不现实），
 * 但工号在院内是公开信息，不改密就等于「知道工号即可冒用他人身份签发病历」。
 * 后端在 get_current_user 处硬拦——未改密账号除改密/登出外一律 403；本弹窗是
 * 对应的前端表现：登录后立刻挡在最上层，不可关闭、不可跳过，改完才放行。
 *
 * 触发来源两条（互为兜底）：
 *   1. 登录响应里的 user.must_change_password
 *   2. 任意接口返回 403 且带 X-Must-Change-Password 头（api.ts 拦截器置位），
 *      覆盖「localStorage 里是旧登录态、字段还没有」的老会话
 */

import { useState } from 'react'
import { Modal, Form, Input, Alert } from 'antd'
// antd v5 静态 message 不消费 React 上下文、提示不显示，全项目统一走消息桥
import { message } from '@/services/messageBridge'
import api from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function ForcePasswordChangeModal() {
  const { user, setMustChangePassword, clearAuth } = useAuthStore()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)

  const open = !!user?.must_change_password
  if (!open) return null

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSubmitting(true)
    try {
      await api.post('/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      setMustChangePassword(false)
      message.success('密码已修改，可以开始使用了')
    } catch (err) {
      // 后端把「原密码错 / 新密码太短 / 与原密码相同」都用 400 + detail 返回
      const detail = (err as { detail?: string })?.detail || '修改失败，请重试'
      message.error(detail)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      title="请先修改初始密码"
      okText="确认修改"
      confirmLoading={submitting}
      onOk={handleSubmit}
      // 不给关闭途径：这是安全强制项，关掉也只会撞后端 403
      closable={false}
      maskClosable={false}
      keyboard={false}
      cancelText="退出登录"
      onCancel={clearAuth}
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="您的账号还在使用统一初始密码"
        description="改密之前无法查看患者与病历。请设置一个只有您本人知道的密码——病历上的署名是您本人，密码泄露等同于他人能以您的名义签发病历。"
      />
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item
          label="初始密码"
          name="old_password"
          rules={[{ required: true, message: '请输入管理员发给您的初始密码' }]}
        >
          <Input.Password autoFocus placeholder="管理员发给您的初始密码" />
        </Form.Item>
        <Form.Item
          label="新密码"
          name="new_password"
          rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, message: '新密码至少 6 位' },
          ]}
        >
          <Input.Password placeholder="至少 6 位，请勿使用工号或生日" />
        </Form.Item>
        <Form.Item
          label="确认新密码"
          name="confirm_password"
          dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator: (_, value) =>
                !value || getFieldValue('new_password') === value
                  ? Promise.resolve()
                  : Promise.reject(new Error('两次输入的新密码不一致')),
            }),
          ]}
        >
          <Input.Password placeholder="再输入一次" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
