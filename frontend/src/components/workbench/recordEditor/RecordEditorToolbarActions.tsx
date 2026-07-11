/**
 * 工具栏右侧动作按钮组：生成 / 润色 / 质控 / 补全 / 出具 / 导出 + HIS 自动填入
 * （components/workbench/recordEditor/RecordEditorToolbarActions.tsx）
 *
 * 2026-06-11 Round 5 拆分：从 RecordEditorToolbar.tsx 抽出（原文件 471 行超 300 行规范）。
 * 按钮渲染逻辑原样搬家，未做任何改动；
 * 嵌入模式（embedStore）/ 问诊数据（inquiryStore）/ 医生信息（authStore）订阅随按钮一起搬入。
 */
import { App, Button, Space } from 'antd'
import {
  EditOutlined,
  FileDoneOutlined,
  FileWordOutlined,
  MedicineBoxOutlined,
  SafetyOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { exportWordDoc } from '@/utils/recordExport'
import { useAuthStore } from '@/store/authStore'
import type { Patient, VisitType } from '@/domain/medical'

/** AI 质控评分徽章（只取分数字段） */
export interface QCBadge {
  /** 质控评分（百分制），null/undefined 表示未评分 */
  grade_score?: number | null
}

interface RecordEditorToolbarActionsProps {
  /** 病历正文内容（决定按钮可用态 / 导出与填入的数据源） */
  recordContent: string
  /** 当前病历类型（导出 Word 时决定文档模板） */
  recordType: string
  /** 病历是否已签发（签发后生成/润色/质控等编辑类按钮禁用） */
  isFinal: boolean
  /** 签发时间（导出 Word 写入病案首页） */
  finalizedAt: string | null
  /** 任一 AI 任务进行中（互斥锁，所有按钮统一禁用） */
  isBusy: boolean
  /** 一键生成进行中 */
  isGenerating: boolean
  /** 润色进行中 */
  isPolishing: boolean
  /** AI 质控进行中 */
  isQCing: boolean
  /** 质控结果已过期（病历改动后置 true，按钮变橙提示重新质控） */
  isQCStale: boolean
  /** 补全缺失项进行中 */
  isSupplementing: boolean
  /** 质控问题列表（非空且未签发时显示"补全缺失项"按钮） */
  qcIssues: unknown[]
  /** 结构检查是否通过（false 时拦截"出具最终病历"） */
  qcPass: boolean | null
  /** 质控评分徽章（出具按钮文案 / 拦截弹窗里展示分数） */
  gradeScore: QCBadge | null
  /** 当前患者（含病案首页字段），导出 Word 时一并写入顶部首页 */
  currentPatient: Patient | null
  /** 当前接诊类型（导出 Word 病案首页用） */
  visitType: VisitType
  /** 一键生成回调 */
  handleGenerate: () => void
  /** 润色回调 */
  handlePolish: () => void
  /** AI 质控回调 */
  handleQC: () => void
  /** 补全缺失项回调 */
  handleSupplement: () => void
  /** 打开"出具最终病历"确认弹窗 */
  setFinalModalOpen: (open: boolean) => void
}

export default function RecordEditorToolbarActions(props: RecordEditorToolbarActionsProps) {
  const {
    recordContent,
    recordType,
    isFinal,
    finalizedAt,
    isBusy,
    isGenerating,
    isPolishing,
    isQCing,
    isQCStale,
    isSupplementing,
    qcIssues,
    qcPass,
    gradeScore,
    currentPatient,
    visitType,
    handleGenerate,
    handlePolish,
    handleQC,
    handleSupplement,
    setFinalModalOpen,
  } = props

  // App.useApp() 拿到的 modal 实例能 consume 主题 context；
  // 不要用 Modal.warning/info/confirm 静态方法（会绕开 ConfigProvider 主题）。
  const { modal } = App.useApp()

  // 导出 Word 时拼"病案首页"用的接诊上下文：医生姓名/科室来自 authStore，
  // visit_type 来自 activeEncounterStore（由父组件传入）。编辑器场景没有 snapshot，传 null。
  const user = useAuthStore(s => s.user)
  const exportCtx = {
    visit_type: visitType,
    visit_time: finalizedAt,
    doctor_name: user?.real_name,
    department_name: user?.department_name,
  }

  return (
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
            modal.warning({
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
        onClick={() =>
          exportWordDoc(recordContent, currentPatient, recordType, finalizedAt, null, exportCtx)
        }
        style={{ borderRadius: 8, fontSize: 12, height: 30 }}
      >
        导出 Word
      </Button>
    </Space>
  )
}
