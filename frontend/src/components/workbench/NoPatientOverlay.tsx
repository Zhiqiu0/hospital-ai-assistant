/**
 * 无接诊时的工作台遮罩（components/workbench/NoPatientOverlay.tsx）
 *
 * 半透明 + 模糊背景，居中显示 Empty + 初诊/复诊按钮。
 * 由父组件根据 currentPatient 是否存在控制显示。
 */
import { Button, Empty, Space } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

interface NoPatientOverlayProps {
  setModalOpen: (mode: 'new' | 'returning') => void
}

export default function NoPatientOverlay({ setModalOpen }: NoPatientOverlayProps) {
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(248,250,252,0.90)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        zIndex: 50,
        borderRadius: 8,
      }}
    >
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <span style={{ fontSize: 14, color: 'var(--text-3)' }}>
            暂无接诊，请选择「初诊」或「复诊」开始
          </span>
        }
      />
      <Space>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setModalOpen('new')}
          size="large"
          style={{ borderRadius: 20 }}
        >
          初诊
        </Button>
        <Button onClick={() => setModalOpen('returning')} size="large" style={{ borderRadius: 20 }}>
          复诊
        </Button>
      </Space>
    </div>
  )
}
