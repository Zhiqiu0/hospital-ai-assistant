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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.his_adapter.event_bus import his_event_bus
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient

logger = logging.getLogger(__name__)

# 推送里的 visit_type 口径宽容映射（厂商可能给中文/英文/编码，统一收敛）
_VISIT_TYPE_MAP = {
    "outpatient": "outpatient", "门诊": "outpatient", "1": "outpatient",
    "emergency": "emergency", "急诊": "emergency", "2": "emergency",
    "inpatient": "inpatient", "住院": "inpatient", "3": "inpatient",
}




# ── 三拆兼容层（2026-09-19）────────────────────────────────────────────
# 患者身份归并与科室/医生映射已按职责拆出（见各模块头注）。此处 re-export
# 保持 `from app.his_adapter.admit_service import X` 与 monkeypatch
# `admit_service._map_doctor` 等既有用法全部不变——process_admit 引用的
# 就是本模块命名空间里的这些名字，patch 它们依旧生效。
from app.his_adapter.admit_patient_resolve import (  # noqa: F401,E402
    _field_acceptable,
    _find_or_create_patient,
    _find_patient_by_his_no,
    _parse_his_birth_date,
    _refresh_patient_from_repush,
)
from app.his_adapter.admit_org_map import (  # noqa: F401,E402
    _map_doctor,
    _resolve_department,
)
from app.his_adapter.admit_prefill import _prefill_from_push  # noqa: F401,E402
from app.his_adapter.admit_types import (  # noqa: F401,E402
    AdmitError,
    AdmitResult,
)


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
        if patient is not None:
            await _refresh_patient_from_repush(db, patient, payload, enc)
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
