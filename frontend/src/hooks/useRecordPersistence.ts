/** 编辑器的文书读取与自动保存编排：统一携带具体 ID，读取确认前禁止保存缓存。 */
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'
import { useAutoSaveDraft } from './useAutoSaveDraft'
import { useDraftByTypeLoader } from './useDraftByTypeLoader'

export function useRecordPersistence() {
  const encounterId = useActiveEncounterStore(s => s.encounterId)
  const { selectedRecordId, recordType, recordContent, isFinal, isGenerating, recordLoading } =
    useRecordStore()
  useAutoSaveDraft({
    encounterId,
    recordId: selectedRecordId,
    recordType,
    recordContent,
    isFinal,
    isGenerating,
  })
  useDraftByTypeLoader(encounterId, recordType)
  return recordLoading
}
