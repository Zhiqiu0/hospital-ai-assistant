/**
 * QC 字段写入定位映射表（components/workbench/qcFieldConstants.ts）
 *
 * 2026-06-11 从 qcFieldMaps.ts（858 行超标）拆出，内容零改动。
 * 仅含两张声明式映射表：字段→章节、字段→章节内子行。
 * 对外 API 仍从 qcFieldMaps.ts re-export，调用方 import 路径不变。
 */

/** field_name → 病历中的章节标题（用于定位写入位置）
 *
 * 设计原则：
 *   - 每个 field_name 必须有对应条目，否则 writeSectionToRecord 静默跳过写入
 *   - 专项评估各子项独立成章节，避免写一项覆盖其他子项
 *   - content / onset_time 等非章节字段映射为 ''（跳过写入）
 */
export const FIELD_TO_SECTION: Record<string, string> = {
  // ── 通用必填 ──
  chief_complaint: '【主诉】',
  history_present_illness: '【现病史】',
  past_history: '【既往史】',
  allergy_history: '【过敏史】',
  personal_history: '【个人史】',
  physical_exam: '【体格检查】',
  // physical_exam_vitals 不在这里——它是【体格检查】下的子行（"T:..."），
  // 走 FIELD_TO_LINE_PREFIX 行级写入。否则章节级整段替换会冲掉同段的中医四诊行
  // （2026-04-29 用户报告 bug 的根因）。
  auxiliary_exam: '【辅助检查】',
  onset_time: '', // 时间戳字段，不对应独立章节
  content: '', // 全文类问题，不做章节替换

  // ── 诊断 ──
  initial_diagnosis: '【初步诊断】',
  initial_impression: '【初步诊断】',
  western_diagnosis: '【初步诊断】',
  tcm_diagnosis: '【中医诊断】',
  tcm_syndrome_diagnosis: '【中医诊断】',
  tcm_disease_diagnosis: '【中医诊断】',
  admission_diagnosis: '【入院诊断】',

  // ── 住院通用 ──
  marital_history: '【婚育史】',
  menstrual_history: '【月经史】',
  family_history: '【家族史】',

  // ── 中医四诊 ──
  // 注：望/闻/舌/脉 不写在这里——它们是【体格检查】下的子行，由 FIELD_TO_LINE_PREFIX 处理
  treatment_method: '【治则治法】',

  // ── 治疗意见 & 复诊 ──
  treatment_plan: '【处理意见】',
  followup_advice: '【复诊建议】',
  precautions: '【注意事项】',

  // ── 急诊 ──
  observation_notes: '【留观记录】',
  patient_disposition: '【患者去向】',

  // ── 住院元信息 ──
  history_informant: '【病史陈述者】',

  // ── 住院·首次病程记录章节（render_first_course_record 输出，治本 2026-05-19） ──
  病例特点: '【病例特点】',
  拟诊讨论: '【拟诊讨论】',
  诊疗计划: '【诊疗计划】',

  // ── 住院·出院记录章节（render_discharge_record 输出） ─────────────
  入院情况: '【入院情况】',
  诊疗经过: '【诊疗经过】',
  出院情况: '【出院情况】',
  出院诊断: '【出院诊断】',
  出院医嘱: '【出院医嘱】',

  // ── 住院·围手术期章节（render_pre_op_summary / op_record / post_op_record） ─
  手术指征: '【手术指征】',
  拟施手术名称及方式: '【拟施手术名称及方式】',
  手术经过: '【手术经过】',
  病情分析及术后恢复情况评估: '【病情分析及术后恢复情况评估】',

  // ── 住院专项评估 ──
  // 注：以下 7 项是【专项评估】下的子行（"· 疼痛评估：..."），由 FIELD_TO_LINE_PREFIX 处理
  // 不在这里映射成独立章节，否则会跟 LLM 一键生成的格式不一致 → 重复章节

  // ── 中文 field_name 别名（LLM 返回中文键时使用）──
  主诉: '【主诉】',
  现病史: '【现病史】',
  既往史: '【既往史】',
  过敏史: '【过敏史】',
  个人史: '【个人史】',
  '个人史/婚育史/月经史/家族史': '【个人史】',
  婚育史: '【婚育史】',
  月经史: '【月经史】',
  家族史: '【家族史】',
  体格检查: '【体格检查】',
  // 舌象/脉象/望诊/闻诊 走 FIELD_TO_LINE_PREFIX，不在这里映射
  治则治法: '【治则治法】',
  处理意见: '【处理意见】',
  // 2026-06-11 修复：原映射到【处理意见】——渲染器从不输出这个独立章节
  // （门诊模板只有【治疗意见及措施】+ 四个子行），导致 LLM 质量建议给出的
  // "治疗意见及措施"父段修复文本被静默丢弃（E2E 实测 chip 不出现的根因）。
  // 现在指向真实章节，由复合段结构化合并保证子行不被冲掉。
  治疗意见及措施: '【治疗意见及措施】',
  复诊建议: '【复诊建议】',
  随访建议: '【复诊建议】',
  注意事项: '【注意事项】',
  留观记录: '【留观记录】',
  患者去向: '【患者去向】',
  病史陈述者: '【病史陈述者】',
  初步诊断: '【初步诊断】',
  入院诊断: '【入院诊断】',
  诊断: '【入院诊断】',
  辅助检查: '【辅助检查】',
  '辅助检查（入院前）': '【辅助检查（入院前）】',
  专项评估: '【专项评估】',
  // 疼痛/VTE/营养/心理/康复/用药/宗教 走 FIELD_TO_LINE_PREFIX，不在这里映射
}

/**
 * 章节"子行"写入映射：fieldName → { 所在章节, 行前缀 }
 *
 * 设计背景：
 *   LLM 一键生成时，部分字段不是独立章节，而是**章节内的一行**（如【体格检查】下的
 *   "切诊·舌象：xxx"）。如果走 FIELD_TO_SECTION 章节级写入，会在病历末尾另起独立
 *   【舌象】章节，导致重复 + 视觉割裂——这是 04-17 commit 引入的"配置漂移"bug。
 *
 * 此表统一管理所有"章节子行"字段，writeSectionToRecord 入口优先匹配本表，
 * 命中则走行级替换，不在则退化到章节级逻辑（兜底）。
 *
 * 与后端 prompt 契约一致性：
 *   本表行前缀必须跟 backend/app/services/ai/prompts_generation.py 里
 *   OUTPATIENT_GENERATE_PROMPT / ADMISSION_NOTE_PROMPT 一致。
 *   后端 test_prompt_contract.py 会反向断言 prompt 字符串里包含这些前缀。
 */
export const FIELD_TO_LINE_PREFIX: Record<
  string,
  {
    section: string
    prefix: string
    /**
     * 行替换模式：
     *   'value'（默认）：替换前缀后的内容，保留前缀。
     *     例：「望诊：[未填写]」+ value="神清" → 「望诊：神清」
     *   'whole_line'：fix_text 自带前缀，整行替换为 fix_text。
     *     例：「T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg」整行替换。
     *     用于生命体征——它的内容含多个 T:/P:/R:/BP: 标记，无法用单一前缀切分。
     */
    mode?: 'value' | 'whole_line'
  }
> = {
  // ── 生命体征：在【体格检查】下，整行替换 ──
  // 行匹配锚点 "T:"（按 prompt 契约，体格检查段第一行必须以 T: 起头）。
  // mode='whole_line' 把整行换成 fix_text（fix_text 自带 "T:..." 前缀），
  // 避免章节级整段替换冲掉同段的中医四诊行（2026-04-29 治本 fix）。
  physical_exam_vitals: { section: '【体格检查】', prefix: 'T:', mode: 'whole_line' },
  生命体征: { section: '【体格检查】', prefix: 'T:', mode: 'whole_line' },

  // ── 中医四诊：在【体格检查】下 ──
  tcm_inspection: { section: '【体格检查】', prefix: '望诊：' },
  tcm_auscultation: { section: '【体格检查】', prefix: '闻诊：' },
  tongue_coating: { section: '【体格检查】', prefix: '切诊·舌象：' },
  pulse_condition: { section: '【体格检查】', prefix: '切诊·脉象：' },
  望诊: { section: '【体格检查】', prefix: '望诊：' },
  闻诊: { section: '【体格检查】', prefix: '闻诊：' },
  舌象: { section: '【体格检查】', prefix: '切诊·舌象：' },
  脉象: { section: '【体格检查】', prefix: '切诊·脉象：' },

  // ── 治疗意见及措施：【治疗意见及措施】合并章节下 4 个子行 ──
  // 病历模板（record_renderer.py render_outpatient）输出：
  //   【治疗意见及措施】
  //   治则治法：xxx
  //   处理意见：xxx
  //   复诊建议：xxx
  //   注意事项：xxx (可选)
  // 后端 QC 规则 target_field 用中文键，前端按行前缀精准替换占位符，
  // 治治本"逐条修复时全段冲掉同章节其他子行"反复 bug 的根因（2026-05-19）。
  治则治法: { section: '【治疗意见及措施】', prefix: '治则治法：' },
  处理意见: { section: '【治疗意见及措施】', prefix: '处理意见：' },
  复诊建议: { section: '【治疗意见及措施】', prefix: '复诊建议：' },
  注意事项: { section: '【治疗意见及措施】', prefix: '注意事项：' },
  // 2026-06-11：英文键补齐行级映射——renderer 模板里它们都是【治疗意见及措施】
  // 下的子行（见 record_renderer.py render_outpatient），原先只有 FIELD_TO_SECTION
  // 里指向不存在的独立章节（【治则治法】等），写入会被静默跳过
  treatment_method: { section: '【治疗意见及措施】', prefix: '治则治法：' },
  treatment_plan: { section: '【治疗意见及措施】', prefix: '处理意见：' },
  followup_advice: { section: '【治疗意见及措施】', prefix: '复诊建议：' },
  precautions: { section: '【治疗意见及措施】', prefix: '注意事项：' },
  随访建议: { section: '【治疗意见及措施】', prefix: '复诊建议：' },

  // ── 诊断：【诊断】合并章节下 2 个子行（中医诊断为合并行 "X — Y"） ──
  中医诊断: { section: '【诊断】', prefix: '中医诊断：' },
  西医诊断: { section: '【诊断】', prefix: '西医诊断：' },

  // ── 住院专项评估 7 项：在【专项评估】下 ──
  pain_assessment: { section: '【专项评估】', prefix: '· 疼痛评估' },
  vte_risk: { section: '【专项评估】', prefix: '· VTE风险' },
  nutrition_assessment: { section: '【专项评估】', prefix: '· 营养风险' },
  psychology_assessment: { section: '【专项评估】', prefix: '· 心理状态' },
  rehabilitation_assessment: { section: '【专项评估】', prefix: '· 康复需求' },
  current_medications: { section: '【专项评估】', prefix: '· 当前用药' },
  religion_belief: { section: '【专项评估】', prefix: '· 宗教信仰' },
  疼痛评估: { section: '【专项评估】', prefix: '· 疼痛评估' },
  VTE风险评估: { section: '【专项评估】', prefix: '· VTE风险' },
  营养评估: { section: '【专项评估】', prefix: '· 营养风险' },
  心理评估: { section: '【专项评估】', prefix: '· 心理状态' },
  康复评估: { section: '【专项评估】', prefix: '· 康复需求' },
  当前用药: { section: '【专项评估】', prefix: '· 当前用药' },
  宗教信仰: { section: '【专项评估】', prefix: '· 宗教信仰' },
}
