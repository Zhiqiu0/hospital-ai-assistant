/**
 * quick-start 非阻断警示弹框（门诊 / 住院工作台共用）
 *
 * 这里的两个提示都是「不拦路、只让医生知情」的设计：硬拦截会阻断真实业务
 * （值班交接、急诊副班接管都需要在别人的进行中接诊上继续），所以后端只返回
 * 列表，由前端弹框，医生自行决策。
 *
 * 2026-08-14 第七轮审计：本模块从 WorkbenchPage.tsx 与 encounterCreated.tsx
 * 抽出——两边原本各抄了一份 pending_encounters 弹框，新增的同名同生日提示
 * 要是再抄一遍就是三份；且 WorkbenchPage 加完新弹框后达到 426 行，超出本项目
 * 「页面 ≤400 行」的硬约束。
 */
import type { App } from 'antd'

/** App.useApp() 返回的 modal 实例类型（能 consume 主题 context，勿用 Modal.info 静态方法） */
export type ModalApi = ReturnType<typeof App.useApp>['modal']

/** 别的医生在该患者身上留下的进行中接诊 */
export type PendingEncounter = {
  doctor_name: string
  visit_type: string
  visited_at?: string
}

/** 同名同生日的已有档案（后端 find_weak_candidates 返回） */
export type SimilarPatient = {
  id: string
  name: string
  gender?: string | null
  patient_no?: string | null
  phone?: string | null
  id_card?: string | null
}

const VISIT_TYPE_TEXT: Record<string, string> = {
  emergency: '急诊',
  inpatient: '住院',
  outpatient: '门诊',
}

/**
 * 同名同生日档案提示。
 *
 * 后端此前会在「姓名+出生日期」这个弱键命中时**静默复用**已有档案，紧接着把
 * 那个人的过敏史/既往史预填进表单——医生看到"系统已有资料"通常不会逐条核对，
 * 按别人的过敏史开药可能致命，病历也写进了错误的档案。同名同生日在几万份档案
 * 里是必然会撞的。
 *
 * 现在后端一律新建档案，把候选人交回这里由医生人眼确认：
 * 重复档案可事后人工合并，把两个人误当成一个人不可逆。
 */
export function showSimilarPatientsWarning(list: SimilarPatient[], modal: ModalApi): void {
  if (!Array.isArray(list) || list.length === 0) return
  modal.warning({
    title: '系统中已有同名同生日的患者',
    width: 520,
    content: (
      <div style={{ marginTop: 8 }}>
        <div style={{ marginBottom: 10, color: 'var(--text-3)', fontSize: 13 }}>
          已为本次接诊<b>新建档案</b>。若下列某位就是同一人，请结束本次接诊，改从
          「患者搜索」选中已有档案再开始，避免病历分散在两份档案里：
        </div>
        <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, lineHeight: 2 }}>
          {list.map(p => (
            <li key={p.id}>
              <b>{p.name}</b>
              {p.gender ? ` ${p.gender}` : ''}
              {p.patient_no ? `　病案号 ${p.patient_no}` : ''}
              {/* 手机号/身份证只露尾号：够医生辨认，又不在弹窗里摊开完整 PHI */}
              {p.phone ? `　手机尾号 ${p.phone.slice(-4)}` : ''}
              {p.id_card ? `　证件尾号 ${p.id_card.slice(-4)}` : ''}
            </li>
          ))}
        </ul>
      </div>
    ),
    okText: '我已核对，继续接诊',
  })
}

/** 跨医生未完成接诊警示：让医生看到该患者还有别的医生留下的进行中接诊。 */
export function showPendingEncountersWarning(list: PendingEncounter[], modal: ModalApi): void {
  if (!Array.isArray(list) || list.length === 0) return
  modal.info({
    title: '该患者尚有未完成接诊',
    width: 480,
    content: (
      <div style={{ marginTop: 8 }}>
        <div style={{ marginBottom: 10, color: 'var(--text-3)', fontSize: 13 }}>
          建议联系下列医生处理后再继续，避免重复就诊：
        </div>
        <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, lineHeight: 2 }}>
          {list.map((e, i) => (
            <li key={i}>
              医生 <b>{e.doctor_name}</b>（{VISIT_TYPE_TEXT[e.visit_type] ?? '门诊'}
              {e.visited_at ? `，${new Date(e.visited_at).toLocaleString('zh-CN')}` : ''}）
            </li>
          ))}
        </ul>
      </div>
    ),
    okText: '我已知悉，继续接诊',
  })
}
