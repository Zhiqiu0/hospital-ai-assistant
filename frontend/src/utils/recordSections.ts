/**
 * 病历章节解析工具（utils/recordSections.ts）
 *
 * 用途：
 *   AI 生成 / 润色后，对 markdown 风格的病历文本（用【主诉】/【现病史】等
 *   标题分段）做两件事：
 *     1. 章节守卫：提取所有章节用于"润色后比对"，发现 LLM 误删章节时还原
 *     2. 反向同步：把生成结果按章节解析回左侧问诊字段，确保左右一致
 *
 * 抽出来的原因：useRecordEditor.ts 主要是 AI 工作流编排，把字符串解析放回
 * 工具层，hook 主体更聚焦。
 */

/**
 * 把生成的病历内容按章节反解为 inquiry 字段字典。
 *
 * 注意：
 *   既往/过敏/个人/月经史 不写回 inquiry——这些字段属于 PatientProfile，
 *   由 PatientProfileCard 单独维护，避免 AI 单次生成覆盖患者纵向档案。
 *
 *   体格检查段落需要分离"望诊/闻诊/切诊/舌脉象"等中医字段，与"其余阳性体征"
 *   合并写回 physical_exam，避免中医字段串到体检里。
 */
/** 模板空值不属于病史事实；整章和复合章节拆出的子字段使用同一判据。 */
const hasFieldContent = (text: string) =>
  !!text.trim() && !/^\[未填写[，,]\s*需补充\]$/.test(text.trim())

export function parseGeneratedSectionsToInquiry(content: string): Record<string, string> {
  const result: Record<string, string> = {}
  const pattern = /【([^】]+)】[^\S\n]*\n?([\s\S]*?)(?=\n【|$)/g
  let m: RegExpExecArray | null
  while ((m = pattern.exec(content)) !== null) {
    const text = m[2].trim()
    // 模板缺项提示不是患者病史，不能回填、更不能覆盖医生已录入的信息。
    if (!hasFieldContent(text)) continue
    switch (m[1]) {
      case '主诉':
        result.chief_complaint = text
        break
      case '现病史':
        result.history_present_illness = text
        break
      case '体格检查': {
        // 滤掉望/闻/切诊（含舌脉象）行，剩下的部分认为是普通体检文字。
        // 体征行（后端 normalize_vitals_line 保证以 "T:" 起头）也要滤——体温脉搏
        // 血压属于独立体征字段，不滤会把整行数值串进 physical_exam 造成重复
        // （2026-08-20 第三轮走查在生产 PUT 请求体里实锤）
        const filteredLines = text.split('\n').filter(line => {
          const trimmed = line.trim()
          return (
            !trimmed.match(/^(望诊|闻诊|切诊[··]?舌象|切诊[··]?脉象|舌象|脉象)[：:]/u) &&
            !trimmed.match(/^其余阳性体征[：:]/u) &&
            !trimmed.match(/^T[：:]/u)
          )
        })
        const physicalLine = text.split('\n').find(l => l.trim().match(/^其余阳性体征[：:]/u))
        const physicalContent = physicalLine
          ? physicalLine.replace(/^其余阳性体征[：:]\s*/u, '').trim()
          : ''
        // 复合章节整体不空，不代表普通体检有内容；过滤提取后的占位子行，
        // 没有实质体检时不返回该键，避免覆盖医生已经录入的体检。
        const physicalExam = [physicalContent, ...filteredLines]
          .map(line => line.trim())
          .filter(hasFieldContent)
          .join('\n')
        if (physicalExam) result.physical_exam = physicalExam
        break
      }
      case '辅助检查':
        result.auxiliary_exam = text
        break
      case '初步诊断':
        result.initial_impression = text
        break
    }
  }
  return result
}
