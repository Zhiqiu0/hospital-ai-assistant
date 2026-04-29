/**
 * 门诊/急诊工作台顶栏（components/workbench/WorkbenchHeader.tsx）
 *
 * 内容：
 *   - 左：MediScribe Logo + 部门 Tag（门诊蓝/急诊红）
 *   - 中：当前患者徽章（绿色，含姓名/性别/年龄/接诊号后6位）+ 初诊/复诊按钮
 *   - 右：历史病历 / 影像分析 / 切换急诊/门诊 / 用户头像 / 登出
 */
import { Button, Typography, Space, Tag, Avatar, Divider } from 'antd'
import {
  LogoutOutlined,
  PlusOutlined,
  MedicineBoxOutlined,
  CameraOutlined,
  UserOutlined,
} from '@ant-design/icons'

const { Text } = Typography

interface WorkbenchHeaderProps {
  isEmergency: boolean
  accentColor: string
  accentLight: string
  accentLighter: string
  user: any
  currentPatient: any
  currentEncounterId: string | null
  setModalOpen: (mode: 'new' | 'returning' | null) => void
  openHistory: () => void
  setImagingOpen: (open: boolean) => void
  onSwitchMode: () => void
  handleLogout: () => void
}

export default function WorkbenchHeader({
  isEmergency,
  accentColor,
  accentLight,
  accentLighter,
  user,
  currentPatient,
  currentEncounterId,
  setModalOpen,
  openHistory,
  setImagingOpen,
  onSwitchMode,
  handleLogout,
}: WorkbenchHeaderProps) {
  return (
    <>
      {/* 顶部强调条（门诊蓝→青/急诊红→粉渐变） */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `linear-gradient(90deg, ${accentColor}, ${accentLight}, ${accentLighter})`,
          borderRadius: '0 0 2px 2px',
        }}
      />

      {/* Logo */}
      <Space size={10}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 9,
            background: `linear-gradient(135deg, ${accentColor}, ${accentLight})`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: `0 2px 8px ${isEmergency ? 'rgba(220,38,38,0.35)' : 'rgba(37,99,235,0.35)'}`,
          }}
        >
          <MedicineBoxOutlined style={{ color: 'var(--surface)', fontSize: 16 }} />
        </div>
        <Text strong style={{ fontSize: 16, color: 'var(--text-1)', letterSpacing: '-0.4px' }}>
          MediScribe
        </Text>
        <Tag color={isEmergency ? 'red' : 'blue'} style={{ margin: 0, borderRadius: 20 }}>
          {isEmergency ? '急诊部' : '门诊部'}
        </Tag>
      </Space>

      {/* 患者信息（居中绝对定位） */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        {currentPatient ? (
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
              border: '1px solid #bbf7d0',
              borderRadius: 8,
              padding: '4px 12px',
              boxShadow: '0 1px 4px rgba(5,150,105,0.1)',
              lineHeight: 1,
            }}
          >
            <div
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: '#22c55e',
                boxShadow: '0 0 0 2px rgba(34,197,94,0.25)',
                flexShrink: 0,
              }}
            />
            <Text style={{ fontSize: 13, fontWeight: 700, color: '#065f46' }}>
              {currentPatient.name}
            </Text>
            {currentPatient.gender && currentPatient.gender !== 'unknown' && (
              <Text style={{ fontSize: 12, color: '#059669' }}>
                {currentPatient.gender === 'male' ? '男' : '女'}
              </Text>
            )}
            {currentPatient.age != null && currentPatient.age > 0 && (
              <Text style={{ fontSize: 12, color: '#059669' }}>{currentPatient.age}岁</Text>
            )}
            <Text
              style={{
                fontSize: 11,
                color: 'var(--text-4)',
                fontFamily: 'monospace',
                marginLeft: 4,
              }}
            >
              #{currentEncounterId?.slice(-6).toUpperCase()}
            </Text>
          </div>
        ) : (
          <Text style={{ fontSize: 13, color: 'var(--text-4)' }}>未选择患者</Text>
        )}
        <Button
          icon={<PlusOutlined />}
          size="small"
          type="primary"
          onClick={() => setModalOpen('new')}
          style={{ borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14 }}
        >
          初诊
        </Button>
        <Button
          size="small"
          onClick={() => setModalOpen('returning')}
          style={{ borderRadius: 20, fontSize: 12, height: 30, paddingInline: 14 }}
        >
          复诊
        </Button>
      </div>

      {/* 右侧用户操作区 */}
      <Space size={4} style={{ flexShrink: 0 }}>
        {/* 历史病历：门诊端一个入口看全部签发病历，与住院端命名一致。
             抽屉默认显示患者列表（按最近就诊倒序）+ 搜索过滤 + 点患者看其全部病历。
             替代了原来的「我的病历」+「患者档案」两个按钮，避免功能重叠。 */}
        <Button
          icon={<UserOutlined />}
          size="small"
          type="text"
          onClick={openHistory}
          style={{ color: '#059669', fontSize: 12, borderRadius: 8 }}
        >
          历史病历
        </Button>
        <Button
          icon={<CameraOutlined />}
          size="small"
          type="text"
          onClick={() => setImagingOpen(true)}
          style={{ color: '#7c3aed', fontSize: 12, borderRadius: 8 }}
        >
          影像分析
        </Button>
        <Button
          size="small"
          type="text"
          onClick={onSwitchMode}
          style={{
            color: isEmergency ? '#2563eb' : '#dc2626',
            fontSize: 12,
            borderRadius: 8,
            fontWeight: 500,
          }}
        >
          切换至{isEmergency ? '门诊' : '急诊'}
        </Button>
        <Divider type="vertical" style={{ margin: '0 4px', borderColor: 'var(--border)' }} />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '4px 10px',
            borderRadius: 8,
            background: 'var(--surface-2)',
          }}
        >
          <Avatar
            size={26}
            style={{
              background: `linear-gradient(135deg, ${accentColor}, ${accentLighter})`,
              fontSize: 11,
              flexShrink: 0,
            }}
          >
            {user?.real_name?.[0]}
          </Avatar>
          <div style={{ lineHeight: 1.3 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>
              {user?.real_name}
            </div>
            {user?.department_name && (
              <div style={{ fontSize: 11, color: 'var(--text-4)' }}>{user.department_name}</div>
            )}
          </div>
        </div>
        <Button
          icon={<LogoutOutlined />}
          size="small"
          type="text"
          onClick={handleLogout}
          style={{ color: 'var(--text-3)', borderRadius: 8 }}
        />
      </Space>
    </>
  )
}
