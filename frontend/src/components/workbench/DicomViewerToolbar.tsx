/**
 * DICOM 查看器工具栏（components/workbench/DicomViewerToolbar.tsx）
 *
 * 三种交互模式（互斥）：窗位窗宽 / 缩放 / 平移；右侧重置按钮。
 * 多帧场景显示当前帧序号 "x / N"。
 */
import { Button, Space, Tooltip, Typography } from 'antd'
import { DragOutlined, ZoomInOutlined, BulbOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ToolMode } from '@/hooks/useDicomViewer'

const { Text } = Typography

interface DicomViewerToolbarProps {
  activeTool: ToolMode
  setActiveTool: (m: ToolMode) => void
  totalFrames: number
  currentFrame: number
  resetView: () => void
}

export default function DicomViewerToolbar({
  activeTool,
  setActiveTool,
  totalFrames,
  currentFrame,
  resetView,
}: DicomViewerToolbarProps) {
  return (
    <div
      style={{
        padding: '6px 10px',
        background: '#181818',
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        borderBottom: '1px solid #222',
      }}
    >
      <Space size={4}>
        <Tooltip title="窗位窗宽（左键上下/左右拖）">
          <Button
            size="small"
            type={activeTool === 'window' ? 'primary' : 'default'}
            icon={<BulbOutlined />}
            onClick={() => setActiveTool('window')}
          />
        </Tooltip>
        <Tooltip title="缩放（左键上下拖）">
          <Button
            size="small"
            type={activeTool === 'zoom' ? 'primary' : 'default'}
            icon={<ZoomInOutlined />}
            onClick={() => setActiveTool('zoom')}
          />
        </Tooltip>
        <Tooltip title="平移（左键拖拽）">
          <Button
            size="small"
            type={activeTool === 'pan' ? 'primary' : 'default'}
            icon={<DragOutlined />}
            onClick={() => setActiveTool('pan')}
          />
        </Tooltip>
      </Space>
      <div style={{ flex: 1 }} />
      {totalFrames > 1 && (
        <Text style={{ color: '#999', fontSize: 12 }}>
          {currentFrame + 1} / {totalFrames}
        </Text>
      )}
      <Tooltip title="重置（窗位/缩放/平移）">
        <Button size="small" icon={<ReloadOutlined />} onClick={resetView} />
      </Tooltip>
    </div>
  )
}
