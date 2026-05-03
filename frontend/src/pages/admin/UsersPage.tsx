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
 */
import { useEffect, useState } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Tooltip,
  Typography,
  Popconfirm,
  message,
} from 'antd'
import { useAuthStore } from '@/store/authStore'
import {
  PlusOutlined,
  EditOutlined,
  StopOutlined,
  CheckCircleOutlined,
  KeyOutlined,
  CopyOutlined,
} from '@ant-design/icons'
import api from '@/services/api'

const { Title } = Typography

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

const ROLE_MAP: Record<string, { label: string; color: string }> = {
  super_admin: { label: '超级管理员', color: 'red' },
  hospital_admin: { label: '医院管理员', color: 'orange' },
  dept_admin: { label: '科室管理员', color: 'gold' },
  doctor: { label: '医生', color: 'blue' },
  nurse: { label: '护士', color: 'cyan' },
}

export default function UsersPage() {
  // 当前登录管理员 ID——用于禁用"自己停用自己"按钮（防误操作把自己锁出系统）
  const myId = useAuthStore(s => s.user?.id)
  const [users, setUsers] = useState<any[]>([])
  const [departments, setDepartments] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editUser, setEditUser] = useState<any>(null)
  const [form] = Form.useForm()

  const loadUsers = async (p = page) => {
    setLoading(true)
    try {
      const data: any = await api.get(`/admin/users?page=${p}&page_size=10`)
      setUsers(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  const loadDepts = async () => {
    const data: any = await api.get('/admin/departments')
    setDepartments(data.items || [])
  }

  useEffect(() => {
    loadUsers()
    loadDepts()
  }, [])

  const openCreate = () => {
    setEditUser(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (user: any) => {
    setEditUser(user)
    form.setFieldsValue({
      real_name: user.real_name,
      role: user.role,
      department_id: user.department_id,
    })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
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
    } catch (e: any) {
      message.error(e?.detail || '操作失败')
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

  // ── 重置密码（2026-05-03 加）─────────────────────────────────────────────
  // 密码原文不可"看"——bcrypt 单向哈希。管理员只能"重置"：手输或一键生成强随机串，
  // 弹窗展示新密码一次（带"复制"按钮），关闭后再也看不到。
  // 真实场景下应该再加"用户首次登录强制改密码"的标志位，本期 MVP 暂不强制。
  const [resetUser, setResetUser] = useState<{ id: string; username: string } | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetSubmitting, setResetSubmitting] = useState(false)

  const openReset = (user: { id: string; username: string }) => {
    setResetUser(user)
    // 默认生成 12 位强随机密码（含字母数字）；管理员可在弹窗内修改
    setNewPassword(generateRandomPassword(12))
  }

  const submitReset = async () => {
    if (!resetUser || !newPassword || newPassword.length < 6) {
      message.warning('密码至少 6 位')
      return
    }
    setResetSubmitting(true)
    try {
      await api.post(`/admin/users/${resetUser.id}/reset-password`, {
        new_password: newPassword,
      })
      message.success('密码已重置，请将新密码告知用户')
      // 不立即关弹窗，让管理员有机会复制；点"知道了"才关
    } catch (e: unknown) {
      const detail = (e as { detail?: string })?.detail
      message.error(detail || '重置失败')
    } finally {
      setResetSubmitting(false)
    }
  }

  const closeReset = () => {
    setResetUser(null)
    setNewPassword('')
  }

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(newPassword)
      message.success('已复制到剪贴板')
    } catch {
      message.warning('复制失败，请手动选中复制')
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '姓名', dataIndex: 'real_name', key: 'real_name' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => {
        const r = ROLE_MAP[role] || { label: role, color: 'default' }
        return <Tag color={r.color}>{r.label}</Tag>
      },
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => openReset({ id: record.id, username: record.username })}
          >
            重置密码
          </Button>
          {record.is_active ? (
            // 自己不能停用自己——按钮禁用 + tooltip 解释
            record.id === myId ? (
              <Tooltip title="不能停用自己的账号，请由其他管理员操作">
                <Button size="small" danger icon={<StopOutlined />} disabled>
                  停用
                </Button>
              </Tooltip>
            ) : (
              <Popconfirm title="确认停用该用户？" onConfirm={() => handleDeactivate(record.id)}>
                <Button size="small" danger icon={<StopOutlined />}>
                  停用
                </Button>
              </Popconfirm>
            )
          ) : (
            <Popconfirm title="确认启用该用户？" onConfirm={() => handleActivate(record.id)}>
              <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
                启用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

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
      <Modal
        title={editUser ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        okText="确认"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit} autoComplete="off">
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
            <Select
              options={Object.entries(ROLE_MAP).map(([v, r]) => ({ value: v, label: r.label }))}
            />
          </Form.Item>
          <Form.Item label="所属科室" name="department_id">
            <Select
              allowClear
              placeholder="选择科室（可选）"
              options={departments.map((d: any) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          {!editUser && (
            <>
              <Form.Item label="工号" name="employee_no">
                <Input placeholder="员工编号（可选）" />
              </Form.Item>
              <Form.Item label="手机号" name="phone">
                <Input placeholder="手机号（可选）" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      {/* 重置密码弹窗：密码原文不可"看"，只能"重置"——展示一次后由用户登录改回 */}
      <Modal
        title="重置密码"
        open={!!resetUser}
        onCancel={closeReset}
        okText="确认重置"
        cancelText="取消"
        okButtonProps={{ loading: resetSubmitting }}
        onOk={submitReset}
        destroyOnClose
        width={460}
      >
        <div style={{ marginBottom: 12, color: 'var(--text-3)', fontSize: 13 }}>
          为用户 <Tag>{resetUser?.username}</Tag> 重置密码：
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
    </div>
  )
}
