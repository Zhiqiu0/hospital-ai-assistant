/**
 * 病历查看弹窗（components/workbench/RecordViewModal.tsx）
 *
 * 只读模式展示一份完整病历内容，被 HistoryDrawer 和管理页调用：
 *   - 顶部"病案首页"：患者+就诊+医生+科室；优先用 patient_snapshot（签发那一刻
 *     冻结的快照，合规要求），缺失才回落到当前 patient 字段
 *   - 病历正文（pre 标签保留格式）
 *   - "打印"按钮调用 utils/recordExport.printRecord，复用同一段首页+样式，
 *     保证查看/打印/导出三处首页布局完全一致
 *
 * Props:
 *   record: 完整病历对象（含 content 字段与可选 patient_snapshot）
 *   open: 是否显示
 *   onClose: 关闭回调
 *
 * 不提供编辑功能：已签发病历不可修改，
 * 草稿病历应通过续接诊恢复工作台进行编辑。
 *
 * 2026-05-16 加：病案首页（合规级"签发时冻结身份信息"）。原来弹窗只显示
 * 姓名/性别/年龄+正文，医生导出/打印都丢身份信息；现在三个入口共用 buildPatientHeaderHtml
 * 以及 inline 卡片，统一展示完整首页。
 *
 * 2026-06-11 Round 5.5 拆分：病案首页卡片移至 ./recordView/PatientHeaderCard.tsx，
 * ViewableRecord 类型与打印/格式化辅助函数移至 ./recordView/viewableRecord.ts，
 * 本文件只保留弹窗骨架。
 */
import { Modal, Space, Tag, Button, Typography } from 'antd'
import { FileTextOutlined, CheckOutlined, PrinterOutlined } from '@ant-design/icons'
import PatientHeaderCard from './recordView/PatientHeaderCard'
import { handlePrint, type ViewableRecord } from './recordView/viewableRecord'

const { Text } = Typography

interface RecordViewModalProps {
  record: ViewableRecord | null
  onClose: () => void
  accentColor: string
  tagColor: string
  recordTypeLabel: (type: string) => string
  showPrint?: boolean
}

export default function RecordViewModal({
  record,
  onClose,
  accentColor,
  tagColor,
  recordTypeLabel,
  showPrint = false,
}: RecordViewModalProps) {
  return (
    <Modal
      title={
        record && (
          <Space wrap>
            <FileTextOutlined style={{ color: accentColor }} />
            <span style={{ fontWeight: 600 }}>{record.patient_name}</span>
            {record.patient_gender && record.patient_gender !== 'unknown' && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_gender === 'male' ? '男' : '女'}
              </Text>
            )}
            {record.patient_age != null && (
              <Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>
                {record.patient_age}岁
              </Text>
            )}
            <Tag color={tagColor} style={{ margin: 0 }}>
              {recordTypeLabel(record.record_type)}
            </Tag>
            <Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
              {record.submitted_at ? new Date(record.submitted_at).toLocaleString('zh-CN') : ''}
            </Text>
          </Space>
        )
      }
      open={!!record}
      onCancel={onClose}
      footer={
        <Space>
          {showPrint && record && (
            <Button icon={<PrinterOutlined />} onClick={() => handlePrint(record, recordTypeLabel)}>
              打印 / 导出PDF
            </Button>
          )}
          <Button type={showPrint ? 'primary' : 'default'} onClick={onClose}>
            关闭
          </Button>
        </Space>
      }
      width={720}
    >
      {record && <PatientHeaderCard record={record} />}
      <div
        style={{
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '20px 24px',
          maxHeight: 460,
          overflowY: 'auto',
          fontSize: 14,
          lineHeight: 1.9,
          whiteSpace: 'pre-wrap',
          fontFamily: "'PingFang SC', 'Microsoft YaHei', sans-serif",
          color: 'var(--text-1)',
        }}
      >
        {record?.content || '（病历内容为空）'}
      </div>
      {/* 已签发标识 + 责任医生 + 签发时间。
          按《病历书写规范》要求展示责任医生姓名；后端从 list_by_patient 返回。
          submitted_by_name = 实际触发签发的医生（可能与接诊医生不同：管床代签等）；
          doctor_name = 接诊医生（接诊创建者，主要责任人）。一般情况下两者相同。 */}
      <div
        style={{
          marginTop: 12,
          padding: '10px 14px',
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          fontSize: 12,
          color: '#166534',
        }}
      >
        <Space size={6}>
          <CheckOutlined style={{ color: '#22c55e' }} />
          <span>已签发病历 · 不可修改</span>
        </Space>
        {record?.doctor_name && (
          <span style={{ color: '#065f46' }}>
            接诊医生：<b>{record.doctor_name}</b>
            {/* 2026-05-03 改：医生侧不再展示 submitted_by_name 差异——
                管理员后台修订病历会让 submitted_by_name 变成 admin，原逻辑会显示
                "（签发：系统管理员）"误导医生认为责任主体不是自己。合规要求的修订
                留痕走 audit_logs 表（管理员后台 + 审计员可查），医生侧只看接诊医生
                即可。如未来真有"管床代签"需求需另起字段（如 first_signed_by）单独
                展示，不复用 submitted_by_name（语义已被修订人占用）。 */}
          </span>
        )}
        {record?.submitted_at && (
          <span style={{ color: '#065f46' }}>
            签发于：{new Date(record.submitted_at).toLocaleString('zh-CN')}
          </span>
        )}
      </div>
    </Modal>
  )
}
