/**
 * 患者档案字段的常用句式（components/workbench/patientProfile/profilePhrases.ts）
 *
 * 为什么要有它（2026-08-18，对照濮氏医院甲级病历）：
 *   甲级病历的既往史/个人史/家族史/婚育史都带一整套标准否认句式
 *   （"否认肝炎史、结核史、疟疾史等传染病史……否认输血史……"），
 *   而 AI 按真实性红线**不能替医生补**这些否认项，医生口述时又不会一句句念。
 *   所以把标准句式做成一键插入的小标签：医生点一下、看一眼、确认，
 *   既保证不编造（是医生自己确认的），又省得逐字敲。
 *
 * 句式文本按医院病历原文整理，与浙江省病历书写规范一致。
 * key 与 PROFILE_FIELDS 的 key 一致；没配的字段就不显示标签。
 *
 * INQUIRY_PHRASES（2026-08-19 对照濮氏门诊病历补）：问诊字段（现病史）的常用句式，
 * 机制同上——医院门诊模板现病史末尾固定带流行病学筛查句和一般情况句，
 * 属医生须确认的事实，AI 不能自动写，故同样做成一键插入。
 */

/** 单条常用句式：label 是标签上的短名，text 是插入正文的完整句子 */
export interface ProfilePhrase {
  label: string
  text: string
}

export const PROFILE_PHRASES: Record<string, ProfilePhrase[]> = {
  past_history: [
    {
      label: '标准否认句',
      text:
        '既往体质可，否认"肝炎史、结核史、疟疾史"等传染病史，否认"糖尿病、冠状动脉粥样硬化性心脏病"等慢性疾病史，' +
        '否认"心、脑、血管、肝、肾、肺、内分泌"等重大器官系统疾病史，否认输血史，否认中毒史，预防接种史不详。',
    },
    { label: '否认外伤手术史', text: '否认外伤史、手术史。' },
    { label: '否认长期用药', text: '否认长期用药史。' },
  ],
  allergy_history: [{ label: '否认过敏', text: '否认食物、药物过敏史。' }],
  personal_history: [
    {
      label: '标准否认句',
      text:
        '否认长期外地居住史，否认疫区、疫情、疫水接触史，否认牧区、矿山、高氟区、低碘区居住史，' +
        '否认化学性物质、粉尘、放射性物质、有毒物质接触史。',
    },
    { label: '不烟不酒', text: '否认嗜酒史、吸烟史。' },
  ],
  family_history: [
    {
      label: '父母健在',
      text: '父母均健在，兄弟姐妹体健，否认家族性遗传疾病、传染病史，否认两系三代内肿瘤病史。',
    },
    {
      label: '父母已故',
      text: '父母已故（死因不详），兄弟姐妹体健，否认家族性遗传疾病、传染病史，否认两系三代内肿瘤病史。',
    },
  ],
  marital_history: [
    { label: '已婚子女体健', text: '适龄结婚，否认近亲结婚，配偶及子女均体健，家庭关系和睦。' },
    { label: '未婚', text: '未婚未育。' },
  ],
}

/** 问诊字段（每次接诊重填）的常用句式：现病史 */
export const INQUIRY_PHRASES: Record<string, ProfilePhrase[]> = {
  history_present_illness: [
    { label: '否认发热接触', text: '否认"发热患者"接触史。' },
    {
      label: '一般情况可',
      text: '自发病以来，神志清，精神可，纳食可，睡眠可，二便调。',
    },
  ],
}

/** 复诊专用的现病史句式（2026-08-20 对照濮氏真实复诊病历）：
 * 医院复诊现病史的高频写法就是"病史同前"+变化一句，仅复诊时显示。 */
export const REVISIT_HPI_PHRASES: ProfilePhrase[] = [
  { label: '病史同前', text: '病史同前。' },
  { label: '较前好转', text: '经治疗后症状较前好转。' },
  { label: '无明显变化', text: '经治疗后症状无明显变化。' },
  { label: '较前加重', text: '症状较前加重。' },
]

/**
 * 把句式追加到现有内容后面：空则直接用；已有内容且末尾没标点则先补"，"再接。
 * 已包含同一句式时原样返回（防重复点击叠加）。
 */
export function appendPhrase(current: string, phrase: string): string {
  const base = (current || '').trimEnd()
  if (base.includes(phrase)) return current
  if (!base) return phrase
  const endsWithPunct = /[。；，,;.！!？?]$/.test(base)
  return base + (endsWithPunct ? '' : '，') + phrase
}
