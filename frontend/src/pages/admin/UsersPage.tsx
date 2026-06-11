/**
 * 用户管理页（pages/admin/UsersPage.tsx）
 *
 * 管理系统用户账号，调用 GET/POST/PUT/DELETE /admin/users：
 *   - 列：用户名、姓名、角色、所属科室、状态（激活/禁用）、注册时间
 *   - 角色：doctor / admin / radiologist
 *   - 新建用户：含初始密码（后端 bcrypt hash 存储）
 *   - 编辑：修改姓名、科室、角色；重置密码
 *   - 软删除：is_active=False（不物理删除，保留历史病历关联）
 *
 * 密码策略：
 *   创建时要求 ≥8 位；管理员可强制重置密码但不能查看原密码。
 *
 * 2026-06-11 Round 5.5 拆分：表单弹窗 / 重置密码弹窗 / 表格列定义 / 共享类型
 * 移至 ./users/ 子目录，本文件只保留数据加载与页面编排。
 */
import { useEffect, useState } from 'react'
import { Table, Button, Typography } from 'antd'
import { message } from '@/services/messageBridge'
import { useAuthStore } from '@/store/authStore'
import { PlusOutlined } from '@ant-design/icons'
import api from '@/services/api'
import type { UserRow, DeptOption, UserFormValues } from './users/types'
import { buildUserColumns } from './users/userColumns'
import UserFormModal from './users/UserFormModal'
import ResetPasswordModal from './users/ResetPasswordModal'

const { Title } = Typography

export default function UsersPage() {
  // 当前登录管理员 ID——用于禁用"自己停用自己"按钮（防误操作把自己锁出系统）
  const myId = useAuthStore(s => s.user?.id)
  const [users, setUsers] = useState<UserRow[]>([])
  const [departments, setDepartments] = useState<DeptOption[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editUser, setEditUser] = useState<UserRow | null>(null)
  // 重置密码弹窗的目标用户（null = 关闭）；密码状态/API 调用在 ResetPasswordModal 内部
  const [resetUser, setResetUser] = useState<{ id: string; username: string } | null>(null)

  const loadUsers = async (p = page) => {
    setLoading(true)
    try {
      const data = (await api.get(`/admin/users?page=${p}&page_size=10`)) as {
        items: UserRow[]
        total: number
      }
      setUsers(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  const loadDepts = async () => {
    const data = (await api.get('/admin/departments')) as { items?: DeptOption[] }
    setDepartments(data.items || [])
  }

  useEffect(() => {
    loadUsers()
    loadDepts()
    // 只挂载时加载一次；setState 在 effect 里是预期路径
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openCreate = () => {
    setEditUser(null)
    setModalOpen(true)
  }

  const openEdit = (user: UserRow) => {
    setEditUser(user)
    setModalOpen(true)
  }

  const handleSubmit = async (values: UserFormValues) => {
    try {
      if (editUser) {
        await api.put(`/admin/users/${editUser.id}`, values)
        message.success('更新成功')
      } else {
        await api.post('/admin/users', values)
        message.success('创建成功')
      }
      setModalOpen(false)
      loadUsers()
    } catch (e) {
      // axios 响应拦截把后端 { detail: string } 当作 reject 值传出，这里 inline cast 取 detail
      const detail = (e as { detail?: string })?.detail
      message.error(detail || '操作失败')
    }
  }

  const handleDeactivate = async (id: string) => {
    try {
      await api.delete(`/admin/users/${id}`)
      message.success('已停用')
      loadUsers()
    } catch {
      message.error('操作失败')
    }
  }

  // 启用已停用账号（2026-05-03 加）—— 跟科室管理对齐，让停用动作可逆
  const handleActivate = async (id: string) => {
    try {
      await api.post(`/admin/users/${id}/activate`)
      message.success('已启用')
      loadUsers()
    } catch {
      message.error('操作失败')
    }
  }

  // 表格列定义在 ./users/userColumns.tsx，这里注入页面侧回调
  const columns = buildUserColumns({
    myId,
    onEdit: openEdit,
    onReset: setResetUser,
    onDeactivate: handleDeactivate,
    onActivate: handleActivate,
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          用户管理
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建用户
        </Button>
      </div>
      <Table
        columns={columns}
        dataSource={users}
        rowKey="id"
        loading={loading}
        pagination={{
          total,
          pageSize: 10,
          current: page,
          onChange: p => {
            setPage(p)
            loadUsers(p)
          },
        }}
      />

      {/* 新建/编辑用户弹窗（表单 UI 在子组件，提交 API 在本页 handleSubmit） */}
      <UserFormModal
        open={modalOpen}
        editUser={editUser}
        departments={departments}
        onCancel={() => setModalOpen(false)}
        onSubmit={handleSubmit}
      />

      {/* 重置密码弹窗：密码原文不可"看"，只能"重置"——展示一次后由用户登录改回 */}
      <ResetPasswordModal user={resetUser} onClose={() => setResetUser(null)} />
    </div>
  )
}
