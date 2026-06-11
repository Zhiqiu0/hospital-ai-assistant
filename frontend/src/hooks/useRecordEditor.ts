/**
 * 病历编辑器逻辑门面（hooks/useRecordEditor.ts）
 *
 * 从 RecordEditor 抽离的业务 hook：负责 AI 生成 / 润色 / 质控 / 补全四个动作
 * 和章节守卫、SSE 流处理。SSE 通用代码已抽到 services/streamSSE.ts。
 *
 * 2026-06-11 Round 5 重构：本文件超 300 行规范（约 500 行），按动作内聚性
 * 拆分到 hooks/recordEditor/ 子目录，本文件退化为门面（组合聚合）——
 *   - useRecordEditorShared.ts  共享基础设施（runSSE / payload 构造 / pull-forward）
 *   - useRecordGenerate.ts      AI 生成（含 pendingGenerate 自动触发）
 *   - useRecordPolish.ts        AI 润色（含【追问补充】区块保护）
 *   - useRecordQC.ts            AI 质控（SSE 多事件分发 + 评分提示）
 *   - useRecordSupplement.ts    AI 批量补全（行级写入 + 自动重新质控）
 * 对外 API（返回值结构）保持一字不改，消费方（RecordEditor.tsx）零改动。
 */
import { useState } from 'react'
import { useRecordStore } from '@/store/recordStore'
import { useQCStore } from '@/store/qcStore'
import { useCurrentPatient } from '@/store/activeEncounterStore'
import { useRecordEditorShared } from './recordEditor/useRecordEditorShared'
import { useRecordGenerate } from './recordEditor/useRecordGenerate'
import { useRecordPolish } from './recordEditor/useRecordPolish'
import { useRecordQC } from './recordEditor/useRecordQC'
import { useRecordSupplement } from './recordEditor/useRecordSupplement'

export function useRecordEditor() {
  // 各域字段从对应子 store 取（门面只保留返回值需要的切片）
  const {
    recordContent,
    recordType,
    isGenerating,
    isPolishing,
    setRecordContent,
    setRecordType,
    isFinal,
    finalizedAt,
  } = useRecordStore()
  const { isQCing, isQCStale, qcIssues, qcPass, gradeScore } = useQCStore()
  const currentPatient = useCurrentPatient()

  const [finalModalOpen, setFinalModalOpen] = useState(false)

  // 共享基础设施（runSSE / buildRecordTaskPayload / pull-forward / 卸载中止）
  const shared = useRecordEditorShared()

  // 四个动作 hook：纯组合注入，逻辑全在各自文件内
  const { handleGenerate } = useRecordGenerate(shared)
  const { handlePolish } = useRecordPolish(shared)
  const { handleQC } = useRecordQC(shared)
  // 补全完成后要自动重新质控，故把 handleQC 注入补全 hook
  const { isSupplementing, handleSupplement } = useRecordSupplement(shared, handleQC)

  const isBusy = isGenerating || isPolishing || isQCing || isSupplementing
  const busyText = isGenerating
    ? 'AI 生成中...'
    : isPolishing
      ? 'AI 润色中...'
      : isSupplementing
        ? 'AI 补全中...'
        : 'AI 质控中...'

  return {
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
  }
}
