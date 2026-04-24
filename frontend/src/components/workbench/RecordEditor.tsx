/**
 * 病历编辑器组件（components/workbench/RecordEditor.tsx）
 * 业务逻辑已提取至 hooks/useRecordEditor.ts，此文件仅保留 JSX 渲染。
 */
import { Button, Space, Typography, Input, Select, Spin, Tag, Modal } from 'antd'
import {
  ThunderboltOutlined,
  EditOutlined,
  SafetyOutlined,
  FileDoneOutlined,
  CheckOutlined,
  MedicineBoxOutlined,
  PrinterOutlined,
  FileWordOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { printRecord, exportWordDoc } from '@/utils/recordExport'
import FinalRecordModal from './FinalRecordModal'
import PreviousRecordPanel from './PreviousRecordPanel'
import { useRecordEditor } from '@/hooks/useRecordEditor'
import { useWorkbenchStore } from '@/store/workbenchStore'

const { Text } = Typography
const { TextArea } = Input

export default function RecordEditor() {
  const { previousRecordContent } = useWorkbenchStore()
  const {
    recordContent,
    setRecordContent,
    recordType,
    setRecordType,
    isGenerating,
    isPolishing,
    isQCing,
    isQCStale,
    isFinal,
    finalizedAt,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    finalModalOpen,
    setFinalModalOpen,
    isSupplementing,
    isBusy,
    busyText,
    handleGenerate,
    handlePolish,
    handleQC,
    handleSupplement,
  } = useRecordEditor()

  return (
    <div
      style={{
        height: '100%',
        background: 'var(--surface)',
        borderRadius: 12,
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderBottom: '1px solid var(--border-subtle)',
          background: 'var(--surface-2)',
          flexShrink: 0,
          gap: 8,
        }}
      >
        <Space size={8} style={{ flexShrink: 0 }}>
          <Text
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: 'var(--text-1)',
              letterSpacing: '-0.2px',
            }}
          >
            病历草稿
          </Text>
          {isFinal && finalizedAt && (
            <Tag color="success" style={{ margin: 0 }}>
              已签发 · {finalizedAt}
            </Tag>
          )}
          <Select
            value={recordType}
            onChange={setRecordType}
            size="small"
            style={{ width: 120 }}
            options={[
              { value: 'outpatient', label: '门诊病历' },
              {
                label: '─── 住院病历 ───',
                options: [
                  { value: 'admission_note', label: '入院记录' },
                  { value: 'first_course_record', label: '首次病程' },
                  { value: 'course_record', label: '日常病程' },
                  { value: 'senior_round', label: '上级查房' },
                  { value: 'pre_op_summary', label: '术前小结' },
                  { value: 'op_record', label: '手术记录' },
                  { value: 'post_op_record', label: '术后病程' },
                  { value: 'discharge_record', label: '出院记录' },
                ],
              },
            ]}
          />
        </Space>

        <Space size={4}>
          <Button
            icon={<ThunderboltOutlined />}
            type="primary"
            size="small"
            loading={isGenerating}
            onClick={handleGenerate}
            disabled={isFinal || !!recordContent.trim() || isBusy}
            style={{
              borderRadius: 8,
              fontWeight: 600,
              fontSize: 13,
              height: 30,
              paddingInline: 14,
              ...(isFinal || recordContent.trim()
                ? {}
                : {
                    background: 'linear-gradient(135deg, #1d4ed8, #3b82f6)',
                    border: 'none',
                    boxShadow: '0 2px 8px rgba(37,99,235,0.35)',
                  }),
            }}
          >
            一键生成
          </Button>

          <Button
            icon={<EditOutlined />}
            size="small"
            loading={isPolishing}
            onClick={handlePolish}
            disabled={isFinal || !recordContent.trim() || isBusy}
            style={{ borderRadius: 8, fontSize: 12, height: 30 }}
          >
            润色
          </Button>

          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={<SafetyOutlined />}
            size="small"
            loading={isQCing}
            onClick={() => handleQC()}
            disabled={isFinal || isBusy}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              // 病历改动后变为橙色提示重新质控
              ...(isFinal
                ? {}
                : isQCStale
                  ? { color: '#d97706', borderColor: '#fcd34d', background: '#fffbeb' }
                  : { color: '#dc2626', borderColor: '#fca5a5', background: '#fff5f5' }),
            }}
          >
            {isQCStale ? '重新质控' : 'AI质控'}
          </Button>

          {qcIssues.length > 0 && !isFinal && (
            <Button
              icon={<MedicineBoxOutlined />}
              size="small"
              loading={isSupplementing}
              disabled={isBusy}
              onClick={handleSupplement}
              style={{
                borderRadius: 8,
                fontSize: 12,
                height: 30,
                color: '#92400e',
                borderColor: '#fcd34d',
                background: '#fffbeb',
              }}
            >
              补全缺失项
            </Button>
          )}

          <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 2px' }} />

          <Button
            icon={qcPass === false ? <StopOutlined /> : <FileDoneOutlined />}
            size="small"
            disabled={!recordContent.trim() || isBusy}
            onClick={() => {
              if (qcPass === false) {
                Modal.warning({
                  title: `结构检查未通过，无法提交${gradeScore?.grade_score != null ? `（当前 ${gradeScore.grade_score} 分）` : ''}`,
                  content:
                    '请修复右侧质控提示中标注「必须修复」的所有结构性问题后重新质控，通过后方可出具正式病历。',
                  okText: '知道了，去修改',
                  width: 460,
                })
                return
              }
              setFinalModalOpen(true)
            }}
            style={{
              borderRadius: 8,
              fontSize: 12,
              height: 30,
              color: qcPass === false ? '#dc2626' : '#065f46',
              borderColor: qcPass === false ? '#fca5a5' : '#6ee7b7',
              background: qcPass === false ? '#fff5f5' : '#f0fdf4',
            }}
          >
            {qcPass === false
              ? `结构未通过${gradeScore ? `(${gradeScore.grade_score}分)` : ''}`
              : '出具最终病历'}
          </Button>

          <Button
            icon={<FileWordOutlined />}
            size="small"
            disabled={!recordContent.trim() || isBusy}
            onClick={() => exportWordDoc(recordContent, currentPatient, recordType, finalizedAt)}
            style={{ borderRadius: 8, fontSize: 12, height: 30 }}
          >
            导出 Word
          </Button>
        </Space>
      </div>

      {/* Status bar */}
      {isBusy ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 16px',
            flexShrink: 0,
            background: 'linear-gradient(90deg, #eff6ff, #f0f9ff)',
            borderBottom: '1px solid #bfdbfe',
            color: '#1d4ed8',
            fontSize: 12,
            fontWeight: 500,
          }}
        >
          <Spin size="small" />
          <span>{busyText}</span>
        </div>
      ) : isFinal ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '6px 16px',
            flexShrink: 0,
            background: '#f0fdf4',
            borderBottom: '1px solid #bbf7d0',
          }}
        >
          <Space size={6}>
            <CheckOutlined style={{ fontSize: 12, color: '#065f46' }} />
            <span style={{ color: '#065f46', fontSize: 12, fontWeight: 500 }}>
              病历已签发，不可修改
            </span>
          </Space>
          <Button
            size="small"
            icon={<PrinterOutlined />}
            onClick={() => printRecord(recordContent, currentPatient, recordType, finalizedAt)}
            style={{
              borderRadius: 6,
              fontSize: 12,
              height: 26,
              color: '#065f46',
              borderColor: '#86efac',
              background: 'var(--surface)',
            }}
          >
            打印
          </Button>
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 14px',
            flexShrink: 0,
            borderBottom: '1px solid var(--border-subtle)',
            color: '#b0bec5',
            fontSize: 11,
          }}
        >
          <span>AI 生成内容仅供参考，请医生审核后使用</span>
        </div>
      )}

      {/* 复诊时展示上次病历参考卡片 */}
      {previousRecordContent && <PreviousRecordPanel content={previousRecordContent} />}

      {/* Editor */}
      <TextArea
        value={recordContent}
        onChange={e => setRecordContent(e.target.value)}
        readOnly={isFinal}
        placeholder="填写左侧问诊信息后，点击「一键生成」自动生成病历草稿，或直接在此输入..."
        style={{
          flex: 1,
          fontSize: 14,
          lineHeight: 2.0,
          resize: 'none',
          border: 'none',
          outline: 'none',
          padding: '12px 16px',
          color: 'var(--text-1)',
          background: isFinal ? 'var(--surface-2)' : 'var(--surface)',
        }}
        variant="borderless"
      />

      <FinalRecordModal open={finalModalOpen} onCancel={() => setFinalModalOpen(false)} />
    </div>
  )
}
