/** AI 请求绑定发起时的接诊与文书；切走后永久失效，切回来也不能接续旧流。 */
import { useActiveEncounterStore } from '@/store/activeEncounterStore'
import { useRecordStore } from '@/store/recordStore'

export function createRecordTaskScope(onLeave: () => void = () => {}) {
  const encounterId = useActiveEncounterStore.getState().encounterId
  const recordType = useRecordStore.getState().recordType
  let current = true
  const check = () => {
    if (
      current &&
      (useActiveEncounterStore.getState().encounterId !== encounterId ||
        useRecordStore.getState().recordType !== recordType)
    ) {
      // 先失效再清理运行态，避免 store 回调重入。
      current = false
      onLeave()
    }
  }
  const unsubscribeEncounter = useActiveEncounterStore.subscribe(check)
  const unsubscribeRecord = useRecordStore.subscribe(check)
  return {
    isCurrent: () => current,
    dispose: () => {
      unsubscribeEncounter()
      unsubscribeRecord()
    },
  }
}
