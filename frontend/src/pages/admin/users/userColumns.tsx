/**
 * 用户管理表格列定义（pages/admin/users/userColumns.tsx）
 *
 * 2026-06-11 Round 5.5 拆分：从 UsersPage.tsx 抽出。
 * 工厂函数形式：操作列需要页面侧的回调（编辑/重置密码/停用/启用）和
 * 当前管理员 ID（用于禁用"自己停用自己"按钮，防误操作把自己锁出系统）。
 */
import { Button, Space, Tag, Tooltip, Popconfirm, type TableProps } from 'antd'
import { EditOutlined, StopOutlined, CheckCircleOutlined, KeyOutlined } from '@ant-design/icons'
import { ROLE_MAP, type UserRow } from './types'

interface UserColumnsDeps {
  /** 当前登录管理员 ID（自己不能停用自己） */
  myId?: string
  /** 打开编辑弹窗 */
  onEdit: (user: UserRow) => void
  /** 打开重置密码弹窗 */
  onReset: (user: { id: string; username: string }) => void
  /** 停用用户（软删除 is_active=False） */
  onDeactivate: (id: string) => void
  /** 启用已停用账号（2026-05-03 加，让停用动作可逆） */
  onActivate: (id: string) => void
}

/** 构建用户表格列：基础信息列 + 角色/状态 Tag 列 + 操作列 */
export function buildUserColumns({
  myId,
  onEdit,
  onReset,
  onDeactivate,
  onActivate,
}: UserColumnsDeps): NonNullable<TableProps<UserRow>['columns']> {
  return [
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
      render: (_: unknown, record: UserRow) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(record)}>
            编辑
          </Button>
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => onReset({ id: record.id, username: record.username })}
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
              <Popconfirm title="确认停用该用户？" onConfirm={() => onDeactivate(record.id)}>
                <Button size="small" danger icon={<StopOutlined />}>
                  停用
                </Button>
              </Popconfirm>
            )
          ) : (
            <Popconfirm title="确认启用该用户？" onConfirm={() => onActivate(record.id)}>
              <Button size="small" type="primary" icon={<CheckCircleOutlined />}>
                启用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]
}
