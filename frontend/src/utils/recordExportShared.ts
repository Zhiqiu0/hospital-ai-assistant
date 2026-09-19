/**
 * 病历导出·共享层（utils/recordExportShared.ts，2026-09-19 由 recordExport.ts 拆出）
 *
 * 纯机械搬移，零逻辑改动（465 行超工具文件合理规模的两拆）。本文件放
 * 类型、标签表（RECORD_TYPE_LABEL 有契约测试锁与后端枚举对齐）、
 * 纯格式化/脱敏/转义函数与病案首页 HTML 拼装；打印与 Word 导出的
 * 入口函数留在 recordExport.ts（它 re-export 本文件全部公共符号，
 * 调用方 import 路径不变）。
 * 注：原文件内私有的 esc/maskName/fmtDateTime 等在此导出仅供
 * recordExport.ts 使用——视为 internal，不要在业务组件里直接引用。
 */
export function maskName(name?: string | null): string {
  if (!name) return '患者'
  const chars = Array.from(name)
  if (chars.length <= 1) return name
  const keep = chars.length >= 3 ? 2 : 1
  return chars.slice(0, keep).join('') + '*'.repeat(chars.length - keep)
}
/**
 * 病历类型 → 打印/导出件标题。
 *
 * 键必须与后端 medical_records.record_type 枚举逐字一致（该值同时原样回写
 * HIS），缺键会让标题栏直接印出英文 key。2026-08-31 法规形式要件审计发现
 * 本表漏了 emergency——急诊接诊会由 activeEncounterStore 按 visitType 设成
 * 'emergency'，于是急诊病历打印出来标题赫然是 "emergency"、导出文件名也是
 * emergency_张*.doc，这份纸交给患者转诊或提交医调委即形式要件不合格。
 * 契约测试 recordExport.labels.test.ts 已锁住「与后端枚举一一对应」。
 */
export const RECORD_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊病历',
  emergency: '急诊病历',
  admission_note: '入院记录',
  first_course_record: '首次病程记录',
  course_record: '日常病程记录',
  senior_round: '上级查房记录',
  discharge_record: '出院记录',
  pre_op_summary: '术前小结',
  op_record: '手术记录',
  post_op_record: '术后病程记录',
}

/**
 * 病案首页所需患者最小形状（导出/打印场景）。
 * 全部 optional，避免上游 patient 字段缺失导致报错；缺字段在首页上显示为 "—"。
 */
export interface RecordExportPatient {
  name?: string | null
  gender?: string | null
  age?: number | null
  patient_no?: string | null
  birth_date?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
}

/**
 * 病案首页快照（与后端 medical_records.patient_snapshot JSONB 字段对齐）。
 * 优先于 RecordExportPatient 使用——首页字段先从这里取，缺失才落到 patient。
 */
export interface RecordExportSnapshot {
  name?: string | null
  gender?: string | null
  birth_date?: string | null
  patient_no?: string | null
  id_card?: string | null
  phone?: string | null
  address?: string | null
  ethnicity?: string | null
  marital_status?: string | null
  occupation?: string | null
  workplace?: string | null
  contact_name?: string | null
  contact_phone?: string | null
  contact_relation?: string | null
  blood_type?: string | null
  visit_type?: string | null
  visit_time?: string | null
  bed_no?: string | null
  doctor_name?: string | null
  department_name?: string | null
  /** 就诊号（2026-08-31 导出审计）：签发快照里补存，打印首页作定位键。
   *  存量快照没有该键，取值链会回落 ctx.visit_no。 */
  visit_no?: string | null
}

/** 接诊/医生上下文（不在 patient 表里，由调用方从 encounter/doctor 传入）。 */
export interface RecordExportContext {
  visit_type?: string | null // outpatient/emergency/inpatient
  visit_time?: string | null // ISO datetime 或后端任意时间字符串
  bed_no?: string | null
  doctor_name?: string | null
  department_name?: string | null
  /** 就诊号/住院号（HIS 流水号）——法定文书必需的定位键（2026-08-31 导出审计补） */
  visit_no?: string | null
  /** 签发医师：可能 !== 接诊医生（住院主管医生让管床医生代签发），
   *  两者同栏显示会让纸面认不出责任主体 */
  submitted_by_name?: string | null
  /** 文书版本号：>1 表示经管理员修订过，打印件必须注明（病历书写规范要求
   *  修改留痕、原记录清楚可辨；此前打印件把修订完全抹平，对外呈现为原始签发件） */
  version_no?: number | null
  /**
   * 管理员修订次数（source='admin_revise' 的版本数）。
   * 打印件的法定「经修订」标识只认这个——**不能用 version_no**：正常签发
   * 流程本身就会产生 3 个版本（AI 生成 → 医生编辑 → 签发），拿它判断会给
   * 每一份普通病历都印上「经修订」，标识随即失去意义。
   * 2026-09-01 打印件实测发现，当时一份从没改过的病历被印成「经修订（第 3 版）」。
   */
  revision_count?: number | null
  /**
   * 补记标注（2026-09-02 补）。《病历书写基本规范》：因抢救急危患者未能及时
   * 书写的，应在抢救结束后 6 小时内**据实补记，并加以注明**。「注明」的载体是
   * 归档病历本身——而归档进病案室、被法庭调阅的是打印件。此前补记徽标只在
   * 住院工作台的屏幕时间轴上，纸面一个字都没有：一份隔天补写的病程，打出来
   * 与当场书写的完全无法区分。
   */
  recorded_at?: string | null
  entered_at?: string | null
  is_late_entry?: boolean | null
}

/** 医院名称：打印件抬头（法定文书必需项）。
 *  可用 VITE_HOSPITAL_NAME 覆盖，默认落地医院。 */
export const HOSPITAL_NAME: string =
  (import.meta.env?.VITE_HOSPITAL_NAME as string) || '安吉濮氏中西医结合医院'

// ── 内部工具：把后端中英枚举/null 都翻成首页显示文本 ──────────────────────────
export const GENDER_LABEL: Record<string, string> = { male: '男', female: '女', unknown: '未知' }
export const VISIT_TYPE_LABEL: Record<string, string> = {
  outpatient: '门诊',
  emergency: '急诊',
  inpatient: '住院',
}

export function pickGender(v?: string | null): string {
  if (!v) return ''
  // 后端 patient.gender 直接存中文 "男/女/未知"；snapshot 也是原样存
  return GENDER_LABEL[v] || v
}

/**
 * 按**指定基准日**算年龄（缺省为今天）。
 *
 * 病案首页的年龄必须按"就诊那一天"算而不是打印当天（2026-08-14 第六轮审计修复）：
 * 病案首页的语义是签发瞬间冻结的一份档案，而原实现恒用 new Date()——
 * 签发时 40 岁的患者，两年后再打印同一份病历会显示 42 岁，
 * 同一份已签发病历打印两次得到不同内容，与"冻结"的设计直接矛盾。
 */
export function calcAgeFromBirth(birth?: string | null, asOf?: string | null): number | null {
  if (!birth) return null
  const d = new Date(birth)
  if (Number.isNaN(d.getTime())) return null
  const base = asOf ? new Date(asOf) : new Date()
  const now = Number.isNaN(base.getTime()) ? new Date() : base
  let age = now.getFullYear() - d.getFullYear()
  const m = now.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--
  return age >= 0 ? age : null
}

export function fmtDateTime(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN')
}

export function fmtDate(s?: string | null): string {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleDateString('zh-CN')
}

export function pickVisitType(v?: string | null): string {
  if (!v) return ''
  return VISIT_TYPE_LABEL[v] || v
}

/**
 * 病案首页拼接（HTML 形式，打印 / Word 公用）。
 *
 * 取值优先级：snapshot → patient → ctx，缺则不渲染该单元格。
 * 渲染样式：两列网格，灰色 label + 黑色 value。打印/导出都用同一段 HTML，
 * 保证查看、打印、导出三处首页一致。
 */
/**
 * HTML 转义（2026-08-14 第六轮审计修复）。
 *
 * 打印/导出把患者字段与病历正文原样拼进 HTML 再 document.write 到**同源**新窗口，
 * 任何一处含 `<script>` 都会在同源上下文执行，能直接读走 localStorage 里的登录
 * token —— 而患者姓名、主诉、现病史这些内容既可能由 HIS 推送带入，也可能由医生
 * 粘贴，属于典型的存储型 XSS 输入面。
 * 所有进 HTML 的值一律先过这里。
 */
export function esc(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 换行归一：把 CRLF/CR 统一成 LF，避免残留 \r 在 pre-wrap 下多出空行 */
export function normalizeEol(text: string): string {
  return text.replace(/\r\n?/g, chrLf())
}
export function chrLf(): string {
  return String.fromCharCode(10)
}

export function buildPatientHeaderHtml(
  patient: RecordExportPatient | null | undefined,
  snapshot: RecordExportSnapshot | null | undefined,
  ctx: RecordExportContext | null | undefined
): string {
  // 工具：snapshot 优先，没有再回落 patient/ctx
  const s = snapshot || {}
  const p = patient || {}
  const c = ctx || {}
  const pick = <T>(...vs: (T | null | undefined)[]): T | null =>
    vs.find(v => v !== null && v !== undefined && v !== '') ?? null

  const name = pick(s.name, p.name) || '—'
  const gender = pickGender(pick(s.gender, p.gender)) || '—'
  const birth = pick(s.birth_date, p.birth_date)
  // 优先按就诊时间算（快照里冻结的那个），拿不到才回落 patient.age 实时值。
  // 注意顺序：原先是 p.age 优先，等于永远用实时年龄、快照形同虚设。
  const visitAt = pick(s.visit_time, c.visit_time)
  const age = calcAgeFromBirth(birth, visitAt) ?? p.age ?? null
  const ageText = age != null ? `${age}岁` : '—'
  const patientNo = pick(s.patient_no, p.patient_no) || '—'
  const idCard = pick(s.id_card, p.id_card) || '—'
  const phone = pick(s.phone, p.phone) || '—'
  const address = pick(s.address, p.address) || '—'
  const ethnicity = pick(s.ethnicity, p.ethnicity) || '—'
  const marital = pick(s.marital_status, p.marital_status) || '—'
  const occupation = pick(s.occupation, p.occupation) || '—'
  const workplace = pick(s.workplace, p.workplace) || '—'
  const contactName = pick(s.contact_name, p.contact_name) || '—'
  const contactPhone = pick(s.contact_phone, p.contact_phone) || '—'
  const contactRelation = pick(s.contact_relation, p.contact_relation) || '—'
  const bloodType = pick(s.blood_type, p.blood_type) || '—'

  const visitType = pickVisitType(pick(s.visit_type, c.visit_type)) || '—'
  const visitTime = fmtDateTime(pick(s.visit_time, c.visit_time)) || '—'
  const bedNo = pick(s.bed_no, c.bed_no) || '—'
  const doctorName = pick(s.doctor_name, c.doctor_name) || '—'
  const deptName = pick(s.department_name, c.department_name) || '—'
  const birthText = fmtDate(birth) || '—'
  // 就诊号与签发医师（2026-08-31 导出产物审计）：前者是法定文书的定位键，
  // 后者在代签发场景下与接诊医生不是同一人——同栏显示会让纸面认不出责任主体
  const visitNo = pick(s.visit_no, c.visit_no) || '—'
  const signedBy = pick(c.submitted_by_name, s.doctor_name, c.doctor_name) || '—'

  // 两列对齐的首页表格——简单 table 兼容 Word/打印渲染最稳
  const row = (a: string, av: string, b: string, bv: string) =>
    `<tr>
      <td class="hk">${esc(a)}</td><td class="hv">${esc(av)}</td>
      <td class="hk">${esc(b)}</td><td class="hv">${esc(bv)}</td>
    </tr>`

  return `
<table class="patient-header">
  ${row('姓名', name, '性别', gender)}
  ${row('年龄', ageText, '出生日期', birthText)}
  ${row('民族', ethnicity, '血型', bloodType)}
  ${row('婚姻', marital, '职业', occupation)}
  ${row('身份证号', idCard, '联系电话', phone)}
  ${row('家庭住址', address, '工作单位', workplace)}
  ${row('紧急联系人', contactName, '联系人电话', contactPhone)}
  ${row('与患者关系', contactRelation, '患者编号', patientNo)}
  ${row('就诊类型', visitType, '床位号', bedNo)}
  ${row('就诊号', visitNo, '所属科室', deptName)}
  ${row('接诊医生', doctorName, '签发医师', signedBy)}
  ${row('就诊时间', visitTime, '', '')}
</table>`
}

// 首页公用 CSS（打印 + Word 都嵌入）
export const HEADER_CSS = `
  .patient-header { width: 100%; border-collapse: collapse; margin: 0 0 18px; font-size: 12pt; }
  .patient-header td { border: 1px solid #cbd5e1; padding: 6px 10px; vertical-align: top; }
  .patient-header .hk { background: #f1f5f9; color: #475569; width: 14%; white-space: nowrap; }
  .patient-header .hv { color: #1e293b; width: 36%; word-break: normal; overflow-wrap: anywhere; }
`

/** 打印页码（2026-08-31 导出审计）：法定病历要求每页页码，住院入院记录
 *  常有两三页。此前完全没有 @page 规则，靠浏览器默认页眉页脚（内容是
 *  about:blank + 打印当天日期），不成立。 */
export const PAGE_CSS = `
  @page {
    /* 显式声明 A4（2026-09-01 真机打印实测补）：此前只写了 margin，纸张交给
       浏览器默认——Chromium 的默认是**美制 Letter（216×279mm）**。实测导出的
       PDF 就是 Letter，且因为 Letter 比 A4 矮，同一份门诊病历被多挤出一页
       （3 页 vs 2 页），分页位置也跟着错。
       中国的病历文书与病案室归档一律用 A4，不能靠"打印机默认恰好是 A4"兜底：
       导出 PDF 归档这条路径根本不经过打印机设置。 */
    size: A4;
    margin: 1.6cm 1.4cm;
    @bottom-center { content: "第 " counter(page) " 页 / 共 " counter(pages) " 页"; font-size: 10pt; color: #64748b; }
  }
`
