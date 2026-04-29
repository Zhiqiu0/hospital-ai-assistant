/**
 * 语音输入卡片（components/workbench/VoiceInputCard.tsx）
 * 业务逻辑已提取至 hooks/useVoiceInputCard.ts。
 * 子组件：SpeakerDialogueCard（对话角色分析）、VoiceStructurePreview（结构化预览）。
 */
import { Alert, Button, Card, Input, Space, Tag, Typography } from 'antd'
import {
  AudioOutlined,
  PauseCircleOutlined,
  RobotOutlined,
  DeleteOutlined,
  SaveOutlined,
} from '@ant-design/icons'
import { InquiryData } from '@/store/types'
import SpeakerDialogueCard from './SpeakerDialogueCard'
import VoiceStructurePreview from './VoiceStructurePreview'
import { useVoiceInputCard } from '@/hooks/useVoiceInputCard'

const { TextArea } = Input
const { Text } = Typography

type VoiceInputCardProps = {
  visitType: 'outpatient' | 'inpatient'
  getFormValues: () => Record<string, any>
  onApplyInquiry: (patch: Partial<InquiryData>) => void
  onApplyToRecord?: (patch: Partial<InquiryData>) => void
}

export default function VoiceInputCard(props: VoiceInputCardProps) {
  const {
    isRecordMode,
    recordingSupported,
    listening,
    uploadingAudio,
    structuring,
    pendingPatch,
    setPendingPatch,
    transcriptId,
    setTranscript,
    lastAnalyzedTranscript,
    setInterimText,
    summary,
    speakerDialogue,
    fullTranscript,
    audioToken,
    startListening,
    stopListening,
    handleContinueRecording,
    handleStructure,
    handleClearTranscript,
    handleApplyPatch,
  } = useVoiceInputCard(props)

  return (
    <Card
      size="small"
      style={{ marginBottom: 12, borderRadius: 10, background: '#f8fbff', borderColor: '#dbeafe' }}
      bodyStyle={{ padding: 12 }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <Space size={8}>
          <Tag color="blue" style={{ marginRight: 0 }}>
            语音录入
          </Tag>
          <Text style={{ fontSize: 12, color: 'var(--text-2)' }}>
            保存原始录音与转写，并让 AI 识别对话结构
          </Text>
        </Space>
        <Space size={6}>
          {uploadingAudio && <Tag color="purple">上传并转写中...</Tag>}
          {listening && <Tag color="red">录音中</Tag>}
        </Space>
      </div>

      {!recordingSupported && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 10 }}
          message="当前浏览器不支持录音，建议使用最新版 Chrome / Edge；仍可手动粘贴转写文本后点 AI 整理。"
        />
      )}

      <Space wrap style={{ marginBottom: 10 }}>
        {listening ? (
          <Button
            danger
            type="primary"
            icon={<PauseCircleOutlined />}
            onClick={stopListening}
            style={{ borderRadius: 6 }}
          >
            停止录音
          </Button>
        ) : fullTranscript ? (
          <>
            <Button
              icon={<AudioOutlined />}
              onClick={handleContinueRecording}
              style={{ borderRadius: 6 }}
            >
              继续录音
            </Button>
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={structuring}
              onClick={handleStructure}
              style={{
                borderRadius: 6,
                background: lastAnalyzedTranscript === fullTranscript ? '#0ea5e9' : '#7c3aed',
                borderColor: lastAnalyzedTranscript === fullTranscript ? '#0ea5e9' : '#7c3aed',
              }}
            >
              {lastAnalyzedTranscript === fullTranscript ? '重新分析' : 'AI分析并整理'}
            </Button>
            <Button
              icon={<DeleteOutlined />}
              onClick={handleClearTranscript}
              style={{ borderRadius: 6 }}
            >
              清空重录
            </Button>
          </>
        ) : (
          <Button
            type="primary"
            icon={<AudioOutlined />}
            onClick={startListening}
            style={{ borderRadius: 6 }}
          >
            开始录音
          </Button>
        )}
      </Space>

      <TextArea
        rows={6}
        value={fullTranscript}
        onChange={e => {
          setTranscript(e.target.value)
          setInterimText('')
        }}
        placeholder="这里会实时显示语音转写内容，也支持手动粘贴第三方 ASR 的转写文本"
        style={{ borderRadius: 8, marginBottom: 8 }}
      />

      {summary && (
        <Alert
          type="info"
          showIcon
          message="本段对话摘要"
          description={summary}
          style={{ marginBottom: 8 }}
        />
      )}

      <SpeakerDialogueCard items={speakerDialogue} />

      <Text style={{ fontSize: 12, color: 'var(--text-3)' }}>
        {isRecordMode
          ? '语音原文会在后台保存；AI整理后展示预览，确认无误后点击「插入病历」写入对应章节。'
          : '语音原文会在后台保存；AI整理后会自动回填问诊字段，点击「保存问诊信息」后同步到病历编辑区。'}
      </Text>

      {isRecordMode && pendingPatch && (
        <VoiceStructurePreview
          pendingPatch={pendingPatch}
          onApply={handleApplyPatch}
          onCancel={() => setPendingPatch(null)}
        />
      )}

      {transcriptId && (
        <div style={{ marginTop: 8 }}>
          <div
            style={{
              background: 'var(--border-subtle)',
              borderRadius: 8,
              padding: '8px 12px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <SaveOutlined style={{ color: 'var(--text-3)', fontSize: 13, flexShrink: 0 }} />
            <Text style={{ fontSize: 12, color: 'var(--text-2)', flexShrink: 0 }}>
              录音 #{transcriptId.slice(-6).toUpperCase()}
            </Text>
            {audioToken ? (
              <audio
                controls
                src={`/api/v1/ai/voice-records/${transcriptId}/audio?token=${audioToken}`}
                style={{ flex: 1, height: 32, minWidth: 0 }}
              />
            ) : (
              <Text style={{ fontSize: 12, color: 'var(--text-4)' }}>音频加载中...</Text>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
