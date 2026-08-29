/**
 * 用户新建/编辑表单弹窗（pages/admin/users/UserFormModal.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 UsersPage.tsx 抽出。
 *   - 新建模式（editUser=null）：用户名 + 初始密码 + 姓名/角色/科室 + 工号/手机号
 *   - 编辑模式（editUser 非空）：仅姓名/角色/科室（用户名不可改，密码走重置弹窗）
 *   - 提交逻辑（API 调用）仍在父组件 UsersPage 的 onSubmit 中，本组件只管表单 UI
 */
import { useEffect } from 'react'
import { Modal, Form, Input, Select } from 'antd'
import { ROLE_MAP, type UserRow, type DeptOption, type UserFormValues } from './types'
import { useAuthStore } from '@/store/authStore'

interface UserFormModalProps {
  /** 弹窗是否可见 */
  open: boolean
  /** 编辑目标用户；null = 新建模式 */
  editUser: UserRow | null
  /** 科室下拉选项 */
  departments: DeptOption[]
  /** 取消/关闭回调 */
  onCancel: () => void
  /** 表单校验通过后的提交回调（由父组件调 API） */
  onSubmit: (values: UserFormValues) => void
}

export default function UserFormModal({
  open,
  editUser,
  departments,
  onCancel,
  onSubmit,
}: UserFormModalProps) {
  const [form] = Form.useForm<UserFormValues>()
  // 科室管理员建号范围适配（2026-08-29 第八轮回归修复）：后端已收紧
  // dept_admin 只能建本科室账号、跨科角色与工号绑定仅院级可为——表单若
  // 保持"科室可选/工号可选"的旧提示，dept_admin 留空或顺手填工号必撞 403。
  // 前端按角色收窄可选项与提示，与后端 assert_creation_scope 口径一致。
  // 只在**新建**模式套建号范围规则（2026-08-29 第九轮修正）：后端只有
  // create/bulk-import 有 assert_creation_scope，update 没有——编辑跨科
  // 老账号时若也过滤科室/强制必填，会把既有 department_id 显示成裸 UUID、
  // 还逼着先把人划进本科室才能改姓名。编辑模式维持原自由表单。
  const me = useAuthStore(s => s.user)
  const isDeptAdmin = me?.role === 'dept_admin' && !editUser
  const roleOptions = Object.entries(ROLE_MAP)
    .filter(([v]) => !(isDeptAdmin && (v === 'qc_officer' || v === 'radiologist')))
    .map(([v, r]) => ({ value: v, label: r.label }))

  // form.resetFields / setFieldsValue 必须等 Modal 内的 Form 挂载之后再调，
  // 否则 useForm 实例没连接到任何 Form 元素，触发
  // "Instance created by useForm is not connected to any Form element" 警告。
  // 监听 open + editUser 变化在 effect 里同步初值。
  useEffect(() => {
    if (!open) return
    if (editUser) {
      form.setFieldsValue({
        real_name: editUser.real_name,
        role: editUser.role,
        department_id: editUser.department_id ?? undefined,
      })
    } else {
      form.resetFields()
    }
  }, [open, editUser, form])

  return (
    <Modal
      title={editUser ? '编辑用户' : '新建用户'}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      okText="确认"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={onSubmit} autoComplete="off">
        {!editUser && (
          <>
            <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
              <Input placeholder="登录用户名" autoComplete="off" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, min: 6 }]}>
              <Input.Password placeholder="至少6位" autoComplete="new-password" />
            </Form.Item>
          </>
        )}
        <Form.Item label="姓名" name="real_name" rules={[{ required: true }]}>
          <Input placeholder="真实姓名" />
        </Form.Item>
        <Form.Item label="角色" name="role" rules={[{ required: true }]}>
          <Select options={roleOptions} />
        </Form.Item>
        <Form.Item
          label="所属科室"
          name="department_id"
          rules={isDeptAdmin ? [{ required: true, message: '科室管理员只能在本科室建号' }] : []}
        >
          <Select
            allowClear={!isDeptAdmin}
            placeholder={isDeptAdmin ? '科室管理员只能选本科室' : '选择科室（可选）'}
            options={departments
              .filter(d => !isDeptAdmin || d.id === me?.department_id)
              .map(d => ({ value: d.id, label: d.name }))}
          />
        </Form.Item>
        {!editUser && (
          <>
            {!isDeptAdmin && (
              <Form.Item label="工号" name="employee_no">
                <Input placeholder="员工编号（可选；HIS 派工映射用）" />
              </Form.Item>
            )}
            <Form.Item label="手机号" name="phone">
              <Input placeholder="手机号（可选）" />
            </Form.Item>
          </>
        )}
      </Form>
    </Modal>
  )
}
