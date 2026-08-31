"""接诊推送业务处理（his_adapter/admit_service.py）

2026-08-11 业务联动冲刺：把 WS/HTTP 通道收到的接诊推送落成真实业务——
  1. 患者自动建档：先按 身份证 → 手机+姓名 → 姓名+生日 三级查重复用档案，
     查不到才新建（is_from_his=True 标记来源）
  2. 医生映射：doctor_code（HIS 工号）→ User.employee_no（批量开户时用户名=工号，
     所以再兜底匹配 username），映射不上返回业务错误 ack，厂商日志可见
  3. 接诊幂等：visit_id 为幂等键——同一就诊重复推送（医生在 HIS 反复打开患者）
     复用现存非取消接诊，不重复建档
  4. 工作台叫号：处理成功后向该医生的事件频道发布 admit 事件（SSE 推给浏览器）

调用方：api/v1/his_ws.py（方案 B 长连接）与 api/v1/his.py（方案 A HTTP）。
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime as _dt
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.his_adapter.event_bus import his_event_bus
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User

logger = logging.getLogger(__name__)

# 推送里的 visit_type 口径宽容映射（厂商可能给中文/英文/编码，统一收敛）
_VISIT_TYPE_MAP = {
    "outpatient": "outpatient", "门诊": "outpatient", "1": "outpatient",
    "emergency": "emergency", "急诊": "emergency", "2": "emergency",
    "inpatient": "inpatient", "住院": "inpatient", "3": "inpatient",
}
# 推送 gender（接口枚举 male/female/unknown）→ patients 表中文口径
_GENDER_MAP = {"male": "男", "female": "女", "unknown": "未知"}


class AdmitError(Exception):
    """接诊推送业务错误：code 用于 ack 回执（规范 2.4 错误码体系）。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AdmitResult:
    """接诊推送处理结果（ack data 与叫号事件的数据源）。"""

    encounter_id: str
    patient_id: str
    patient_name: str
    doctor_id: str
    reused: bool  # True=visit_id 已有接诊，本次为重复推送（幂等复用）


async def process_admit(db: AsyncSession, payload: AdmitPushRequest) -> AdmitResult:
    """接诊推送 → 医生映射 + 患者建档 + 接诊创建（visit_id 幂等）。

    Raises:
        AdmitError: 医生工号缺失/未注册（code=40007），厂商 ack 可见
    """
    doctor = await _map_doctor(db, payload.doctor_code)

    # 并发幂等护栏（2026-08-13 复检修复）：下面的「先查后插」在并发下不安全——
    # 厂商超时重发（换新 nonce 绕过防重放）或 WS/HTTP 双通道同推一个 visit_id 时，
    # 两个请求都查不到既有接诊，各自建一条，同一次就诊出现重复接诊+重复患者档案。
    # 用事务级 advisory lock 把「同机构同就诊号」的处理串行化：同 key 的第二个请求
    # 阻塞到第一个提交后再查，就能查到既有接诊走复用分支。锁随事务结束自动释放。
    # 仅 PG 生效（SQLite 测试库无此函数，跳过——测试是单线程无并发）。
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"his_admit:{payload.hospital_code}:{payload.visit_id}"},
        )

    # 幂等：同一机构同 visit_id 已有非取消接诊 → 复用（医生在 HIS 反复打开患者会重推）。
    # 用 hospital_code + visit_id 双键（2026-08-11 审计修复）：visit_id 只在机构内唯一，
    # 且限定 source=admit_push，与历史其它链路数据的命名空间隔离，避免跨机构/跨链路撞号。
    # JSONB 字段的 source/hospital_code 过滤放 Python 侧做（SQLite 测试库不支持 .astext，
    # 命中 visit_no 后候选很少，内存过滤开销可忽略）。
    #
    # 2026-08-14 第七轮审计：这里原本写的是「生产 PG 用 GIN 索引命中 visit_no」——
    # 不成立。那个 GIN 索引建在 his_external_ref->'his_patient_no' 上，与本查询
    # 过滤的 visit_no 裸列毫无关系，visit_no 当时**没有任何索引**，
    # 每次患者叫号都在 advisory lock 里全表扫 encounters。
    # 已由迁移 j20260814hotidx 补上 idx_encounters_visit_no。
    # 行锁（2026-08-31 并发矩阵审计·中高）：上面的 advisory lock 只串行
    # "同一条推送"，挡不住医生侧签发。原实现读到 status='in_progress' 的
    # 旧快照后，医生 quick_save 拿 encounter 行锁置 completed 并提交，
    # 本请求的 UPDATE 解除阻塞后照样把已签发接诊改派给新医生——正是本
    # 函数下方注释宣称已堵住的"责任归属错乱"场景（守卫写了、锁没加）。
    # 附带损失：ref = dict(enc.his_external_ref) 用的是签发前的 JSONB 快照，
    # 会把签发钩子刚写进去的 writeback/writeback_records 整体抹掉。
    # 锁序与 quick_save 一致（encounter 在前），无死锁环。
    candidates = (await db.execute(
        select(Encounter).where(
            Encounter.visit_no == payload.visit_id,
            Encounter.status != "cancelled",
            Encounter.his_external_ref.isnot(None),
        ).order_by(Encounter.created_at.desc()).with_for_update()
    )).scalars().all()
    enc = next(
        (e for e in candidates
         if (e.his_external_ref or {}).get("source") == "admit_push"
         and (e.his_external_ref or {}).get("hospital_code") == payload.hospital_code),
        None,
    )
    if enc is not None:
        # 换医生接诊（2026-08-11 审计修复）：HIS 重推带了新 doctor_code（转接/交接）时，
        # 把接诊改派给新医生并更新科室，否则新医生工作台永远收不到叫号。
        #
        # 但**已结束的接诊不能改派**（2026-08-13 第五轮审计修复）：原先不看状态，
        # 门急诊签发后接诊已 completed、病历也已用原医生的名字签发并回写 HIS，
        # 此时 HIS 若重推一次（重试、补推、visit_id 复用），接诊就被划到另一位
        # 医生名下——他的"我的接诊"里凭空多出一个陌生病人，而那份病历署的是
        # 原医生的名字，责任归属直接错乱。改派只在接诊仍在进行中时才有意义。
        if enc.status in ("completed", "cancelled"):
            logger.info(
                "his.admit: 接诊已结束不改派 encounter_id=%s status=%s doctor_code=%s",
                enc.id, enc.status, payload.doctor_code,
            )
        elif enc.doctor_id != doctor.id:
            prev_doctor_id = enc.doctor_id
            enc.doctor_id = doctor.id
            # 科室同样以**挂号科室**为准（2026-08-31 审计 M4）：与下方新建
            # 分支的 2026-08-14 决策对齐（dept_code 是本次接诊的科室、不是
            # 医生编制科室）。原实现直接取医生编制科室，转科时会把接诊科室
            # 写成接手医生的编制科室（他可能编制在急诊科但坐诊外科），
            # 医生无科室时更会写成 NULL 落进"未挂科室"——病案首页科室、
            # 质控科室统计、复核队列过滤三处同时错。
            enc.department_id = await _resolve_department(
                db, payload.dept_code, payload.dept_name, doctor.department_id,
                visit_id=payload.visit_id,
            )
            ref = dict(enc.his_external_ref or {})
            ref["doctor_code"] = payload.doctor_code
            enc.his_external_ref = ref
            await db.commit()
            await db.refresh(enc)
            # 失效两位医生的接诊列表缓存（2026-08-13 第二轮审计修复）：改派后
            # 原医生的"我的接诊"仍缓存着这条、新医生的缓存里还没有，缓存过期前
            # 两边看到的都是错的——而改派的初衷正是让新医生立刻接手。
            # 接诊快照也一并失效（doctor_id 变了）。
            from app.services.encounter_cache import (
                invalidate_encounter_snapshot,
                invalidate_my_encounters,
            )
            await invalidate_my_encounters(prev_doctor_id)
            await invalidate_my_encounters(doctor.id)
            await invalidate_encounter_snapshot(enc.id)
            logger.info("his_admit.reassigned: visit_id=%s 改派医生 %s",
                        payload.visit_id, doctor.username)
        patient = await db.get(Patient, enc.patient_id)
        return AdmitResult(
            encounter_id=enc.id, patient_id=enc.patient_id,
            patient_name=patient.name if patient else payload.patient_name,
            doctor_id=enc.doctor_id, reused=True,
        )

    patient_id = await _find_or_create_patient(db, payload)

    # 科室以**挂号科室**为准（用户 2026-08-14 决策）：规范 3.1 明确 dept_code 是
    # 本次接诊/挂号的科室、非医生编制科室；医生跨科室坐班时两者不同。
    department_id = await _resolve_department(
        db, payload.dept_code, payload.dept_name, doctor.department_id,
        visit_id=payload.visit_id,
    )

    encounter = Encounter(
        patient_id=patient_id,
        doctor_id=doctor.id,
        department_id=department_id,
        # .lower()：厂商给 "Emergency" / "OUTPATIENT" 时原本会静默降级成门诊，
        # 而 visit_type 决定病历类型判定与住院多份文书的 record_no 递增分支，
        # 走错分支没有任何报错。与 _coerce_gender 的容错口径保持一致。
        visit_type=_VISIT_TYPE_MAP.get(
            (payload.visit_type or "").strip().lower(), "outpatient"
        ),
        visit_no=payload.visit_id,
        is_first_visit=payload.is_first_visit if payload.is_first_visit is not None else True,
        status="in_progress",
        # 回写与审计要用的 HIS 上下文全放 his_external_ref（JSONB 灵活适配）
        his_external_ref={
            "source": "admit_push",
            "hospital_code": payload.hospital_code,
            # 患者主索引号：跨就诊稳定，与 hospital_code 联合作查重强键。
            # 键名沿用 HISExternalRef 里早就定义好的 his_patient_no——生产
            # 那个 GIN 索引本来就建在这个键上，此前因为入参不收该字段一直空转。
            "his_patient_no": payload.patient_no,
            "his_visit_no": payload.visit_id,
            "dept_code": payload.dept_code,
            "dept_name": payload.dept_name,
            "doctor_code": payload.doctor_code,
            "agent_device_ip": payload.agent_device_ip,
        },
    )
    db.add(encounter)
    await db.commit()
    await db.refresh(encounter)
    # 选填体征/档案预填（2026-08-13 补接规范 3.1）：只在新建接诊时做，
    # 重复推送复用既有接诊时不碰——那时医生可能已经改过，不能被 HIS 覆盖。
    await _prefill_from_push(db, encounter.id, patient_id, payload)
    patient = await db.get(Patient, patient_id)
    # 日志不落患者姓名（2026-08-13 第二轮审计修复：PHI 不进日志文件）——
    # 排障靠 patient_id/visit_id 关联查库即可，姓名对定位问题没有增量价值。
    logger.info("his_admit.created: visit_id=%s encounter=%s doctor=%s patient_id=%s",
                payload.visit_id, encounter.id, doctor.username, patient_id)
    return AdmitResult(
        encounter_id=encounter.id, patient_id=patient_id,
        patient_name=patient.name if patient else payload.patient_name,
        doctor_id=doctor.id, reused=False,
    )


_VITALS_KEYS = ("temperature", "pulse", "respiration", "bp_systolic",
                "bp_diastolic", "spo2", "height", "weight")


async def _prefill_from_push(
    db: AsyncSession, encounter_id: str, patient_id: str, payload: AdmitPushRequest
) -> None:
    """把推送里的选填体征/档案预填进工作台（规范 3.1，2026-08-13 补接）。

    落点分两处，与前端读取位置对齐：
      - vitals.*        → InquiryInput（工作台左侧「生命体征快速录入」直接显示）
      - allergy/past    → 患者档案 profile（PatientProfileCard 显示，纵向跟随患者）

    安全边界：
      - 档案**只填空缺**，绝不覆盖我方已有值——我们的档案是医生确认过的，
        HIS 推来的可能是陈旧数据，覆盖等于用旧值抹掉医生的确认。
      - 预填失败不影响接诊建立（体征是锦上添花，接诊本身是命门），只记 warning。
    """
    from app.models.encounter import InquiryInput

    vitals = payload.vitals
    vitals_data = {
        k: (getattr(vitals, k) or "").strip()
        for k in _VITALS_KEYS
    } if vitals else {}
    vitals_data = {k: v for k, v in vitals_data.items() if v}
    # 生理极限预检（2026-08-29 第七轮审计）：厂商推"体温 365"（漏小数点）、
    # 身高体重错位等出界值单独丢弃并留痕，其余字段照填——绝不因体征拒收
    # 接诊（与 birth_date 解析失败同哲学）。口径与问诊/住院路径共用 vital_limits。
    from app.services.vital_limits import parse_vital_number, vital_out_of_range
    dropped = [k for k, v in vitals_data.items() if vital_out_of_range(k, v)]
    for k in dropped:
        logger.warning(
            "his_admit.prefill_vitals: %s=%r 超生理极限已丢弃 encounter=%s",
            k, vitals_data.pop(k), encounter_id)
    # 血压交叉预检（2026-08-29 第八轮回归修复）：各自在界内但收缩≤舒张
    # （80/120 错位形态）若照填，医生此后每次整表保存都会撞后端交叉校验
    # 422 被卡死——预填口径必须与保存校验口径一致，错位对丢弃留痕
    _sys = parse_vital_number(vitals_data.get("bp_systolic"))
    _dia = parse_vital_number(vitals_data.get("bp_diastolic"))
    if _sys is not None and _dia is not None and _sys <= _dia:
        logger.warning(
            "his_admit.prefill_vitals: 血压 %s/%s 收缩≤舒张（疑似错位）已丢弃 encounter=%s",
            vitals_data.pop("bp_systolic"), vitals_data.pop("bp_diastolic"), encounter_id)

    try:
        if vitals_data:
            db.add(InquiryInput(encounter_id=encounter_id, version=1, **vitals_data))
            await db.commit()
            logger.info("his_admit.prefill_vitals: encounter=%s 字段=%s",
                        encounter_id, ",".join(sorted(vitals_data)))

        # 档案字段：我方为空 → 直接填；我方已有且不同 → 挂待处理提示，绝不覆盖
        profile_patch = {
            "allergy_history": (payload.allergy_history or "").strip(),
            "past_history": (payload.past_history or "").strip(),
        }
        profile_patch = {k: v for k, v in profile_patch.items() if v}
        if profile_patch:
            # 行锁（2026-08-14 第七轮审计 #20）：档案是「读 JSONB → Python 合并 →
            # 整体写回」。update_profile 早在第二轮就为此加了 with_for_update，
            # 唯独 HIS 预填这条路径漏了——医生正在档案卡上改过敏史时 HIS 推来一条
            # 接诊，两边各自读到旧快照、后提交的把先提交的抹掉，医生刚填的过敏史
            # 就这么没了。process_admit 顶上的 advisory lock 只按 visit_id 串行，
            # 挡不住"同一患者的不同就诊"或"医生手改 vs HIS 推送"。
            patient = (await db.execute(
                select(Patient).where(Patient.id == patient_id).with_for_update()
            )).scalar_one_or_none()
            if patient is not None:
                profile = dict(patient.profile or {})
                changed = False
                for field, value in profile_patch.items():
                    entry = dict(profile.get(field) or {})
                    existing = entry.get("value")
                    # ── 区分「从没填过」与「医生特意清空」（2026-08-14 审计 #19）──
                    #
                    # 原判断是 `if not existing`，而医生把过敏史清空时
                    # update_profile 写进去的是 {"value": "", updated_at, updated_by}
                    # ——一条**有医生署名**的空值，语义是"已核实，无"。
                    # 空字符串是假值，于是下面直接用 HIS 的陈旧值填了回去，
                    # 医生特意做的删除被无声撤销：他刚确认患者不对青霉素过敏，
                    # HIS 那条老记录又冒回来了。
                    # 只有**整条不存在**才算空缺；已有署名的空值走下面的差异提示。
                    doctor_cleared = bool(entry) and entry.get("updated_at") is not None
                    if not existing and not doctor_cleared:
                        # 我方空缺 → 直接填（复诊首次拿到 HIS 档案的常见情况）
                        profile[field] = {
                            "value": value,
                            "updated_at": _dt.now().isoformat(),
                            "updated_by": None,  # 来源是 HIS 推送，非某个医生手填
                        }
                        changed = True
                        continue
                    # existing 走到这里可能是 ""（医生特意清空）甚至 None，
                    # 统一兜一层，别让一条畸形档案把整个接诊预填打挂
                    if (existing or "").strip() == value:
                        # 两边一致：清掉可能残留的旧提示，不打扰医生
                        if entry.pop("his_pending", None) is not None:
                            profile[field] = entry
                            changed = True
                        continue
                    # 两边不一致（2026-08-13）：既不能用 HIS 陈旧值覆盖医生确认过的内容，
                    # 也不能默默丢弃 HIS 的更新——过敏史漏一项会出用药事故。
                    # 挂成待处理提示，由医生在档案卡上看到差异后自己决定采纳/忽略。
                    entry["his_pending"] = {
                        "value": value,
                        "pushed_at": _dt.now().isoformat(),
                    }
                    profile[field] = entry
                    changed = True
                if changed:
                    patient.profile = profile
                    flag_modified(patient, "profile")
                    await db.commit()
                    # 失效档案缓存（2026-08-13 第五轮审计修复）：档案有 5 分钟
                    # Redis 缓存，写完不失效的话 HIS 推来的过敏史/既往史更新
                    # 最长 5 分钟对医生不可见——他可能正好在这窗口里开药。
                    # 患者档案的所有其他写路径（update_profile/confirm/resolve_his）
                    # 都调了这个，唯独 HIS 预填这条漏了。
                    from app.services.patient_cache import _invalidate_patient_cache
                    await _invalidate_patient_cache(patient_id)
                    logger.info("his_admit.prefill_profile: patient=%s 字段=%s",
                                patient_id, ",".join(sorted(profile_patch)))
    except Exception:
        # 预填失败绝不能连累接诊建立（接诊在则医生还能自己录，接诊没了就啥都没了）
        logger.exception("his_admit.prefill_failed: encounter=%s", encounter_id)
        await db.rollback()


async def _resolve_department(
    db: AsyncSession, dept_code: Optional[str], dept_name: Optional[str],
    fallback_department_id: Optional[str], *, visit_id: str = "",
) -> Optional[str]:
    """把 HIS 推来的挂号科室解析成我方 department_id（2026-08-14 修复）。

    为什么必须用挂号科室而不是医生编制科室：
      规范 3.1 对 dept_code 的说明是「本次接诊/挂号的科室，**非医生编制科室**」，
      并要求厂商去科室表取「本地ID」列（如 1230024）推给我们。但代码原先
      直接用 doctor.department_id —— 恰恰是规范明确排除的那个。
      本院医生存在**跨科室坐班**的情况，那时病历上的科室就是错的。

    为什么按 code 自动建档而不是维护映射表：
      附录 B 已确认「无需提供科室字典——科室编码+名称随接诊推送成对下发」。
      既然每次推送都带着 code+name，再维护一张要人工同步的映射表只会引入
      「HIS 加了新科室但我方没同步」的故障点。第一次见到就落一条，之后按
      code 复用；科室名变了就跟着更新。

    Args:
        dept_code: HIS 科室编码（科室表「本地ID」列）
        dept_name: HIS 科室名称
        fallback_department_id: 解析不出时的兜底（医生编制科室）
        visit_id: 就诊流水号，仅用于告警日志定位是哪条推送没带科室

    Returns:
        我方 department_id；dept_code 为空时返回兜底值。
    """
    from app.models.user import Department

    code = (dept_code or "").strip()
    if not code:
        # 厂商没推科室：退回医生编制科室（总比没有强），并留痕便于联调排查。
        # visit_id 必须真带上（2026-08-15 第十轮审计修复）：原先这里硬编码空串，
        # 日志恒为 `visit_no=`，联调时知道"有推送没带科室"却查不到是哪一条。
        logger.warning(
            "his_admit.dept: 推送未带 dept_code，回退医生编制科室 visit_no=%s",
            visit_id,
        )
        return fallback_department_id

    # 列宽预检（2026-08-29 第五轮 HIS 契约审计）：Department.code String(50)/
    # name String(100)，超长直插会 DataError 打挂整条接诊（与已修的姓名超长
    # 同形态）。code 是匹配键，查找与落库用同一截断值保证自洽。
    if len(code) > 50:
        logger.warning("his_admit.dept: dept_code 超列宽截断 len=%d visit_no=%s",
                       len(code), visit_id)
        code = code[:50]

    dept = (await db.execute(
        select(Department).where(Department.code == code)
    )).scalar_one_or_none()

    name = (dept_name or "").strip() or f"HIS科室{code}"
    if len(name) > 100:
        logger.warning("his_admit.dept: dept_name 超列宽截断 len=%d visit_no=%s",
                       len(name), visit_id)
        name = name[:100]
    if dept is None:
        # 首次见到该科室：自动落一条（见上方"为什么不维护映射表"）
        dept = Department(name=name, code=code, is_active=True)
        db.add(dept)
        await db.flush()
        logger.info("his_admit.dept: 自动建科室 code=%s name=%s", code, name)
    elif dept_name and dept.name != name:
        # HIS 侧改了科室名，跟着更新（code 才是身份，name 只是展示）
        logger.info("his_admit.dept: 科室名更新 code=%s %s→%s", code, dept.name, name)
        dept.name = name
    return dept.id


async def _map_doctor(db: AsyncSession, doctor_code: Optional[str]) -> User:
    """HIS 工号 → 系统医生账号。

    匹配顺序（2026-08-13 改为多工号）：
      1. doctor_codes 表——一位医生名下可挂多个工号（本人门诊/本人住院/助理），
         这是主通道。医院名单证实同一医生有 2~3 个工号，HIS 推任一个都要认得。
      2. users.employee_no——存量主工号（迁移已回填进 doctor_codes，这里兜底）
      3. users.username——批量开户约定「用户名=工号」时的兜底

    **助理工号命中的也是本人账号**，因此签发病历署名恒为本人（医院硬要求：
    病历上不能出现助理名字）。
    """
    from app.core.authz import RECORD_WRITE_ROLES
    from app.models.user import DoctorCode

    code = (doctor_code or "").strip()
    if not code:
        raise AdmitError(40007, "接诊推送缺少医生工号（doctor_code）")

    # 角色约束（2026-08-14 第八轮审计）：三条兜底查询原先都只过滤 is_active，
    # 不看 role。而医院给的人员名单**是全院名单不是医生名单**——里面混着
    # 自助机、护工、财务这类条目，批量开户时只要有一条角色判成了非临床角色，
    # HIS 推来对应工号，接诊就被静默派给它，doctor_id 落到一个不该署名的账号上，
    # 之后该账号对这条接诊的一切写操作都被 assert_encounter_access 放行。
    # 「谁能当接诊医生」这个不变量，quick-start 与 POST /encounters 都已用
    # assert_can_write_record 强制，这里是第三处、也是唯一的自动化入口。
    role_ok = User.role.in_(tuple(RECORD_WRITE_ROLES))

    # 归属先于状态（2026-08-31 权限状态变迁审计 H1·高危）：三级兜底原先
    # 全带 is_active 过滤，导致「A 离职→工号落到同名 username 的新人 B→
    # A 被重新启用→工号又跳回 A」——归属随一个与工号无关的开关来回翻转，
    # 接诊派错人、病历署错名。改为先不看状态定位归属：doctor_codes 里
    # 挂着谁就是谁，停用了就明确报错，绝不静默换人。
    owner = (await db.execute(
        select(User)
        .join(DoctorCode, DoctorCode.user_id == User.id)
        .where(DoctorCode.code == code)
    )).scalars().all()
    if len(owner) > 1:
        raise AdmitError(40007, f"工号 {code} 挂在多个账号下，请联系管理员清理后重试")
    if owner:
        _o = owner[0]
        if not _o.is_active:
            raise AdmitError(
                40007, f"工号 {code} 对应的账号已停用，请联系管理员改派或启用")
        if _o.role not in RECORD_WRITE_ROLES:
            raise AdmitError(
                40007, f"工号 {code} 对应的账号不是临床医生角色，请联系管理员核对")
        return _o

    doctor = None
    if doctor is None:
        # 多行命中显式报错（2026-08-28 完整性审计）：users.employee_no 无唯一
        # 约束（历史工号可能重复，不宜硬加 DB 约束），原 .first() 会按执行计划
        # 任意取一个——接诊派错人、病历署错名。兜底命中 >1 行时拒绝并让厂商
        # ack 可见，逼出数据治理而不是静默错派。
        rows = (await db.execute(
            select(User).where(
                User.employee_no == code, User.is_active.is_(True), role_ok
            )
        )).scalars().all()
        if len(rows) > 1:
            raise AdmitError(40007, f"工号 {code} 对应多个账号，请联系管理员清理后重试")
        doctor = rows[0] if rows else None
    if doctor is None:
        rows = (await db.execute(
            select(User).where(
                User.username == code, User.is_active.is_(True), role_ok
            )
        )).scalars().all()
        if len(rows) > 1:
            raise AdmitError(40007, f"工号 {code} 对应多个账号，请联系管理员清理后重试")
        doctor = rows[0] if rows else None
    if doctor is None:
        # 区分「查无此工号」与「工号对应的账号不是临床角色」——后者在联调现场
        # 光看 40007 会以为是没开户，实际是角色配错，能省下大量排查时间。
        exists_any = (await db.execute(
            select(User.id)
            .outerjoin(DoctorCode, DoctorCode.user_id == User.id)
            .where(
                (DoctorCode.code == code)
                | (User.employee_no == code)
                | (User.username == code)
            )
            .limit(1)
        )).scalar_one_or_none()
        if exists_any is not None:
            raise AdmitError(
                40007,
                f"工号 {code} 对应的账号不是可书写病历的角色（或已停用），"
                f"接诊不予派发——请核对该账号角色",
            )
        raise AdmitError(40007, f"医生工号 {code} 未在 MediScribe 注册或已停用")
    return doctor


async def _find_patient_by_his_no(
    db: AsyncSession, hospital_code: str, patient_no: Optional[str]
) -> Optional[str]:
    """按「机构编码 + HIS 患者主索引号」找该患者既往就诊，命中则返回其档案 id。

    用 ->> 取标量再等值比对：PG 生成 `his_external_ref ->> 'his_patient_no' = $1`
    走 idx_encounters_his_patient_no（btree 函数索引），SQLite 测试库生成
    JSON_EXTRACT，两边语义一致，不需要分方言写两套。

    只认非取消的接诊——取消接诊时患者档案可能已被一并清掉，把它捞回来等于
    让医生在新接诊里继续用一个底层已软删的档案。
    """
    if not patient_no:
        return None
    row = (await db.execute(
        select(Encounter.patient_id).where(
            Encounter.his_external_ref["his_patient_no"].as_string() == patient_no,
            Encounter.his_external_ref["hospital_code"].as_string() == hospital_code,
            Encounter.status != "cancelled",
            Encounter.patient_id.isnot(None),
        ).order_by(Encounter.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not row:
        return None
    # 档案可能在上次接诊取消时被软删，复用前确认还活着
    patient = await db.get(Patient, row)
    if patient is None or patient.is_deleted:
        return None
    return str(row)


async def _find_or_create_patient(db: AsyncSession, payload: AdmitPushRequest) -> str:
    """三级查重复用患者档案，查不到新建（is_from_his=True）。

    HIS 推来的身份证/手机号可能不过我方严格校验（历史脏数据），
    校验失败时丢弃该字段继续建档，绝不因脏数据拒收接诊。
    """
    from app.schemas.patient import PatientCreate
    from app.services.patient_service import PatientService

    # 姓名宽容清洗（2026-08-28 极端字符审计，与 _coerce_gender 同哲学：
    # 绝不因脏数据拒收接诊）：剥零宽/BOM/NUL、压平换行、超过列宽 50 截断——
    # 不清洗的话零宽字符会让该患者拼音/汉字搜索双双 miss（医生重复建档），
    # 超长则打穿到 PG DataError 落 ack 50000，该患者每次复诊都推不进来。
    cleaned_name = payload.patient_name or ""
    for _ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\x00"):
        cleaned_name = cleaned_name.replace(_ch, "")
    cleaned_name = (cleaned_name.replace("\n", " ").replace("\r", " ")
                    .replace("\t", " ").strip())
    # 清洗后为空（纯零宽/纯空白姓名）用占位名，绝不回退未清洗原值——
    # 原值会在 PatientCreate 校验器处炸掉整条接诊（2026-08-29 对抗复核修正）
    if not cleaned_name:
        logger.warning("his_admit.patient: 姓名不可清洗，使用占位名 visit_id=%s",
                       payload.visit_id)
        cleaned_name = "未知患者"
    # 间隔号归一（2026-08-31 姓名边界审计）：与 PatientCreate._clean_name 同口径，
    # 否则厂商推 U+30FB 而我方存 U+00B7，跨就诊查重的姓名比对必 miss → 重复建档
    from app.utils.pinyin import SEPARATOR_CHARS
    for _sep in SEPARATOR_CHARS:
        if _sep != chr(0x00B7):
            cleaned_name = cleaned_name.replace(_sep, chr(0x00B7))
    if len(cleaned_name) > 50:
        logger.warning("his_admit.patient: 姓名超列宽截断 len=%d", len(cleaned_name))
        cleaned_name = cleaned_name[:50]
    payload = payload.model_copy(update={"patient_name": cleaned_name})

    birth_date: Optional[date] = None
    if payload.birth_date:
        try:
            # 兼容 YYYYMMDD 紧凑写法：CSRQ 在 HIS 里常是 date/int 列，
            # 序列化出来就是 19680520。入参容错已让它不再被拒收，但若这里
            # 解析不了就等于静默丢掉出生日期——年龄影响用药与诊断判断，
            # 不能默默丢。补一次紧凑格式转换即可，不放宽其它规则。
            raw_bd = payload.birth_date.strip()
            if len(raw_bd) == 8 and raw_bd.isdigit():
                raw_bd = f"{raw_bd[:4]}-{raw_bd[4:6]}-{raw_bd[6:]}"
            # 常见厂商形态归一（2026-08-29 第五轮 HIS 契约审计）：
            # "1968-05-20 00:00:00"（datetime 列序列化）→ 截前 10 位；
            # "1968/05/20"、"1968.5.20" → 分隔符归一；
            # "1968-5-20"（不补零）→ 拆段补零。fromisoformat 只认补零 ISO，
            # 这些形态原先全部静默丢弃且无日志，年龄空缺联调无痕。
            raw_bd = raw_bd[:10].strip().replace("/", "-").replace(".", "-").strip("-")
            parts = raw_bd.split("-")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                raw_bd = f"{parts[0]}-{parts[1]:0>2}-{parts[2]:0>2}"
            birth_date = date.fromisoformat(raw_bd)
            # 未来出生日期丢弃留痕（2026-08-29 第七轮审计）：负年龄会进病案
            # 首页与回写，无合法场景；与解析失败同口径不拒收接诊
            if birth_date > date.today():
                logger.warning(
                    "his_admit.patient: birth_date 在未来已丢弃 raw=%r visit_id=%s",
                    payload.birth_date, payload.visit_id)
                birth_date = None
        except ValueError:
            # 解析不了留空不阻塞建档，但必须留痕——年龄影响用药判断，不能默默丢
            logger.warning(
                "his_admit.patient: birth_date 解析失败已丢弃 raw=%r visit_id=%s",
                payload.birth_date, payload.visit_id,
            )

    service = PatientService(db)
    # ── 三级查重，顺序：身份证 → patient_no → 手机号+姓名 ────────────────────
    #
    # 顺序必须与规范 3.1 及两份厂商参考实现写的完全一致（2026-08-15 修正）：
    # 此前是整块调 find_existing（内部依次试身份证、手机号+姓名），**只有它全部
    # 落空才轮到 patient_no**，于是病案号实际排在手机号后面，与对外文档相反。
    # 本函数原注释写的是「把原本掉到手机号弱匹配的患者接住」——可见当初意图
    # 就是让 patient_no 排在手机号之前，是整块调用把顺序吃掉了。
    #
    # 为什么 patient_no 该排在手机号+姓名之前：手机号会被回收、儿童常留家长
    # 号码、诊室还爱填占位号，「手机号+姓名」是三个强键里最不可靠的一个；
    # 而 patient_no 是医院自己的患者主索引，同一个人恒定、不同人不重。
    #
    # allow_weak_match=False：HIS 全自动链路禁用「姓名+生日」弱键匹配，
    # 避免同名同生日的不同患者被误合并成一份档案（跨人病历污染是临床事故）。
    # 三级强键都不中就新建（可事后人工合并）。
    found = await service.find_existing(
        id_card=payload.id_card or None,
        allow_weak_match=False,
    )
    if not found:
        # 院内患者主索引号必须与 hospital_code 联合——院内编号只在本院唯一，
        # 跨院会撞号。
        pid = await _find_patient_by_his_no(
            db, payload.hospital_code, payload.patient_no
        )
        if pid:
            return pid
        found = await service.find_existing(
            phone=payload.phone or None,
            name=payload.patient_name,
            birth_date=birth_date,
            allow_weak_match=False,
        )
    if found:
        return found["id"]

    fields = {
        "name": payload.patient_name,
        "gender": _GENDER_MAP.get(payload.gender, "未知"),
        "birth_date": birth_date,
        "id_card": payload.id_card or None,
        "phone": payload.phone or None,
    }
    try:
        create_data = PatientCreate(**fields)
    except ValidationError:
        # ── 脏数据降级：逐字段丢弃，不再一次性清空两个 ────────────────────────
        #
        # 2026-08-14 第七轮审计修复：原实现是「任一字段校验不过 → id_card 和
        # phone 一起置 None」。可 HIS 侧最常见的脏数据是**手机号**（留的座机、
        # 空号、7 位老号码），身份证本身好好的。一起丢的后果是这份档案落库时
        # **一个强键都没有**，于是下次复诊 find_existing 三级查重全 miss
        # （HIS 链路还禁用了弱键）→ 每来一次门诊就新建一份档案。
        # 同一个人在系统里散成十几份，病历分散在各档案下，医生查不全既往史。
        # 现在：只丢掉真正校验不过的那个字段，能留的强键必须留住。
        for field in ("id_card", "phone"):
            if fields[field] is None:
                continue
            # 单独试探这一个字段：另一个先摘掉，免得被对方的错误连累
            probe = {**fields, "id_card": None, "phone": None, field: fields[field]}
            try:
                PatientCreate(**probe)
            except ValidationError:
                logger.warning(
                    "his_admit: HIS 推送的 %s 未通过校验，仅丢弃该字段建档 "
                    "visit_no=%s", field, payload.visit_id,
                )
                fields[field] = None

        try:
            create_data = PatientCreate(**fields)
        except ValidationError:
            # 走到这里说明不合格的不是这两个字段（如姓名/生日），退回原策略兜底
            fields["id_card"] = None
            fields["phone"] = None
            try:
                create_data = PatientCreate(**fields)
            except ValidationError:
                # 最终兜底（2026-08-29 对抗复核）："绝不因脏数据拒收接诊"是本
                # 函数的头号不变量——姓名等仍不过校验时降级到占位名+最小字段，
                # 医生在工作台里能看到接诊并手工更正档案，好过整条接诊被拒
                logger.warning(
                    "his_admit.patient: 档案字段全面降级为占位建档 visit_id=%s",
                    payload.visit_id,
                )
                create_data = PatientCreate(name="未知患者")

    # commit=False：建患者与建接诊合并为同一事务，接诊失败不留孤儿档案
    created = await service.create(create_data, commit=False)
    patient = await db.get(Patient, created["id"])
    patient.is_from_his = True  # 标记 HIS 来源，与手动录入档案区分
    return created["id"]


async def publish_admit_event(result: AdmitResult, payload: AdmitPushRequest) -> None:
    """向医生工作台事件频道发布叫号事件（SSE 端点订阅同一频道）。

    事件带齐队列条目所需字段，前端可直接插入队列不必回查。
    """
    await his_event_bus.publish(f"his:doctor:{result.doctor_id}", {
        "type": "admit",
        "encounter_id": result.encounter_id,
        "visit_no": payload.visit_id,
        "patient_id": result.patient_id,
        "patient_name": result.patient_name,
        "gender": payload.gender,
        "birth_date": payload.birth_date,
        "dept_name": payload.dept_name,
        "is_first_visit": payload.is_first_visit,
        "reused": result.reused,
    })


async def handle_admit(payload: AdmitPushRequest) -> AdmitResult:
    """通道层入口：自管 DB 会话，处理推送并发布叫号事件。

    WS 消息循环没有 FastAPI 依赖注入，这里直接用全局会话工厂；
    单测通过 monkeypatch 本函数（或 process_admit）隔离 DB。
    """
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await process_admit(db, payload)
    await publish_admit_event(result, payload)
    # 失效该医生「进行中接诊」列表缓存（2026-08-11 审计修复）：新建/改派接诊后
    # /encounters/my 有 30s 缓存，不失效则续接诊面板最多滞后 30 秒才见到新病人。
    if not result.reused:
        try:
            from app.services.encounter_service import invalidate_my_encounters
            await invalidate_my_encounters(result.doctor_id)
        except Exception:
            logger.warning("his_admit: 失效 my_encounters 缓存失败 doctor=%s", result.doctor_id)
    return result
