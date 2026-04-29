/**
 * 病历场景 Tag 计算（patientHistory/sceneTag.ts）
 *
 * 按 visit_type + visit_sequence 双通道识别：
 *   门诊·初诊(蓝) / 门诊·复诊 N(绿) / 急诊(红) / 第 N 次住院(青)
 */
export function getSceneTag(
  visitType?: string,
  visitSequence?: number
): { text: string; color: string } {
  const seq = typeof visitSequence === 'number' && visitSequence >= 1 ? visitSequence : 1
  const suffix = seq === 1 ? '' : `·复诊 ${seq - 1}`
  if (visitType === 'inpatient') {
    return { text: seq === 1 ? '首次住院' : `第 ${seq} 次住院`, color: 'cyan' }
  }
  if (visitType === 'emergency') {
    return { text: `急诊${suffix}`, color: 'red' }
  }
  if (seq === 1) return { text: '门诊·初诊', color: 'blue' }
  return { text: `门诊·复诊 ${seq - 1}`, color: 'green' }
}
