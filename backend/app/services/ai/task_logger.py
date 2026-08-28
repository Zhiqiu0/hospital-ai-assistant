"""
AI 任务日志工具（Task Logger）

职责：
  将 AI 调用结果异步持久化到数据库，与主请求事务解耦。
  提供三个纯工具函数，供 AI 路由层调用：

  - log_ai_task     : 写 AITask 记录（独立 DB 会话，不阻塞主事务）
  - save_qc_issues  : 持久化质控问题列表到 qc_issues 表

L3 治本（2026-05-18）：
  旧 calc_grade_score 已删——评分由 qc_engine.scorer.score() 驱动，
  按浙江省卫健委 PDF 1:1 标准计算，不再用本模块自创的扣分规则。

设计说明：
  使用独立 AsyncSessionLocal 会话而非主请求的 db 参数，目的是让日志写入
  不受主事务的回滚/提交影响——即使主业务失败，日志记录仍可尝试保存。
"""

import logging
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import generate_uuid
from app.models.medical_record import AITask, MedicalRecord, QCIssue
from app.services.ai.llm_client import llm_client

logger = logging.getLogger(__name__)


async def log_ai_task(
    task_type: str,
    token_input: Optional[int] = None,
    token_output: Optional[int] = None,
    output_result: Optional[dict] = None,
    model_name: Optional[str] = None,
    prompt_version: Optional[str] = None,
) -> str:
    """将一次 AI 调用写入 ai_tasks 表，使用独立 DB 会话避免污染主事务。

    encounter_id / medical_record_id 从 RequestContext contextvar 自动读取
    （路由层在调 AI service 前必须先 bind_encounter_context），调用方不再
    需要层层传参。这是合规底线：每条 AI 任务都能追溯到具体接诊。

    Args:
        task_type:     任务类型，如 "qc"、"generate"、"polish" 等。
        token_input:   本次调用消耗的输入 token 数；无法获取时传 None 落 NULL
                       （2026-08-29 对抗复核：原约定传 0，会把"供应商没回
                       usage"伪装成"零消耗"，token 报表悄悄少计还查不出来；
                       NULL 让缺数据可见，聚合时天然被 SUM 跳过）。
        token_output:  本次调用消耗的输出 token 数；无法获取时传 None，同上。
        output_result: LLM 返回的 JSON 结果。snapshot 恢复时能拿回前端，
                       让医生 logout 重登后追问/检查/诊断建议都还在。

    Args 补充（2026-08-14 第七轮审计 #7）：
        model_name: 本次实际使用的模型名。不传则回落全局默认——但凡调用方
            拿过 get_model_options，就应该把里面的 model_name 传进来，
            否则这条日志记的模型是假的。
        prompt_version: 提示词版本号；当前提示词全部代码内置、无版本概念，
            调用方一律不传（列保留为 NULL，2026-08-18 撤 DB 自定义模板后）。

    Returns:
        新建 AITask 记录的 UUID，供后续 save_qc_issues 关联使用。
    """
    # 从请求 context 读接诊维度——若路由层未 bind，则字段为 NULL（少数
    # 内部调用场景如 admin 后台批量任务可接受，业务路径必须 bind）
    from app.core.request_context import get_encounter_id, get_medical_record_id
    encounter_id = get_encounter_id()
    medical_record_id = get_medical_record_id()

    # 可观测（2026-08-29）：usage 缺失说明供应商响应异常或流式中断，
    # 打点便于在日志里统计缺失率——大面积缺失时成本核算已不可信
    if token_input is None or token_output is None:
        logger.warning("ai_task.usage_missing: task_type=%s 本次调用未取到 usage，"
                       "token 计数落 NULL", task_type)

    task_id = generate_uuid()
    async with AsyncSessionLocal() as db:
        task = AITask(
            id=task_id,
            task_type=task_type,
            status="done",
            token_input=token_input,
            token_output=token_output,
            # 实际用到的模型（2026-08-14 第七轮审计 #7）：
            # 原先这里写死 llm_client.model —— 全局默认值；调用方应把
            # get_model_options 返回的 model_name 传进来，这样日后按场景差异化
            # 模型时（现归代码维护），ai_tasks 记的仍是真正跑的那个模型。
            # 调用方传什么就记什么，没传才回落默认。
            model_name=model_name or llm_client.model,
            # 提示词版本：当前提示词全部代码内置，保持 NULL。
            prompt_version=prompt_version,
            encounter_id=encounter_id,
            medical_record_id=medical_record_id,
            output_result=output_result,
        )
        db.add(task)
        try:
            await db.commit()
        except Exception as exc:
            # 日志写入失败不影响主流程，仅记录错误供排查
            logger.error("ai_task.log: commit_failed err=%s", exc)
    return task_id


async def _locate_medical_record(
    db, encounter_id: Optional[str], record_type: Optional[str]
) -> Optional[str]:
    """按 (接诊, 文书类型) 定位实际被质控的那份病历 id（找不到返回 None）。

    ── 定位到**实际被质控的那一份**（2026-08-14 第八轮审计修复）────────
    原先只按 encounter_id 取「最近创建的那份病历」。门急诊一次接诊一份病历时
    这恰好总是对的，住院一律错：住院第 20 天医生把编辑器切回入院记录跑质控，
    落库时却取到最近新建的第 15 份日常病程——入院记录的质控问题被写进了
    病程记录。调用方本来就有 record_type（_select_rubric 用它选评分表），
    按类型定位即可。2026-08-21 阶段0 抽成共享函数供 save_qc_issues /
    save_qc_report 复用。
    """
    if not encounter_id:
        return None
    stmt = select(MedicalRecord).where(MedicalRecord.encounter_id == encounter_id)
    if record_type:
        stmt = stmt.where(MedicalRecord.record_type == record_type)
    # 同类型有多份时取最近更新的那份（医生正在写的就是它）
    rec = (await db.execute(
        stmt.order_by(MedicalRecord.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if rec is None and record_type:
        # 该类型还没建过病历行（纯草稿态跑质控）：退回原口径兜底，
        # 总比完全不关联强
        rec = (await db.execute(
            select(MedicalRecord)
            .where(MedicalRecord.encounter_id == encounter_id)
            .order_by(MedicalRecord.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    return rec.id if rec else None


async def save_qc_report(
    report_dict: dict,
    deductions: list[dict],
    rubric_key: str,
    encounter_id: Optional[str] = None,
    record_type: Optional[str] = None,
) -> None:
    """把一次法定评分的权威结果落 qc_reports 表（2026-08-21 阶段0 新增）。

    在规则引擎评分完成的瞬间调用——不等 LLM、与 LLM 成败无关，
    治掉"LLM 一挂整次质控零痕迹 + 评分从不落库"两个缺陷。

    Args:
        report_dict: ScoreReport.to_dict() 的结果（取 score/grade/passed）。
        deductions:  法定扣分明细快照 [{rule_code,item_name,target_field,points,is_veto,description}]。
        rubric_key:  评分标准标识（如 "zj_inpatient_2021"）。
        encounter_id / record_type: 定位接诊与文书；同时用于冗余科室/医生快照。
    """
    from app.models.encounter import Encounter
    from app.models.medical_record import QCReport

    async with AsyncSessionLocal() as db:
        medical_record_id = await _locate_medical_record(db, encounter_id, record_type)
        department_id: Optional[str] = None
        doctor_id: Optional[str] = None
        if encounter_id:
            enc = (await db.execute(
                select(Encounter.department_id, Encounter.doctor_id)
                .where(Encounter.id == encounter_id)
            )).first()
            if enc:
                department_id, doctor_id = enc.department_id, enc.doctor_id

        db.add(QCReport(
            encounter_id=encounter_id,
            medical_record_id=medical_record_id,
            record_type=record_type or "outpatient",
            rubric_key=rubric_key,
            score=float(report_dict.get("score") or 0),
            grade=str(report_dict.get("grade") or ""),
            passed=bool(report_dict.get("passed")),
            deductions=deductions,
            department_id=department_id,
            doctor_id=doctor_id,
        ))
        try:
            await db.commit()
        except Exception as exc:
            # 落库失败不影响前端实时展示（SSE 已把结果推给医生）
            logger.error("qc_report.save: commit_failed err=%s", exc)


async def save_qc_issues(
    task_id: str,
    issues: list[dict],
    encounter_id: Optional[str] = None,
    record_type: Optional[str] = None,
) -> None:
    """将质控问题列表持久化到 qc_issues 表。

    Args:
        task_id:      关联的 AITask.id，用于追溯本次 AI 调用。
        issues:       质控问题字典列表，每项应包含：
                        - source        : "rule"（规则引擎）或 "llm"（AI 建议）
                        - issue_type    : "completeness"/"insurance"/"format" 等
                        - risk_level    : "high"/"medium"/"low"
                        - field_name    : 对应的病历字段名
                        - issue_description: 问题描述
                        - suggestion    : 修复建议
        encounter_id: 可选接诊 ID，用于关联最新的 MedicalRecord 记录。

    注意：
        issue 字典中的 source 字段由调用方在构造问题时已明确标注
        （规则引擎问题标 "rule"，LLM 问题标 "llm"），此处直接使用，
        不再重新推断，避免覆盖正确值。
    """
    if not issues:
        return

    async with AsyncSessionLocal() as db:
        # 尝试通过 encounter_id 找到最新病历，建立关联（可选，找不到不阻塞）
        medical_record_id = await _locate_medical_record(db, encounter_id, record_type)

        for issue in issues:
            # BUG FIX: 原代码用 issue_type 是否存在来推断 source，
            # 导致有 issue_type 的 LLM 问题被错存为 "rule"。
            # 正确做法：直接使用调用方已设置的 source 字段。
            source = issue.get("source") or "rule"

            qc = QCIssue(
                ai_task_id=task_id,
                medical_record_id=medical_record_id,
                # 法定规则扣分默认归 "rubric" 类（2026-08-21 阶段0）：此前不带
                # issue_type 的规则扣分全兜底成 "quality"，与 LLM 质量建议混桶，
                # admin 统计的"问题类型分布"因此失真
                issue_type=issue.get("issue_type") or ("rubric" if source == "rule" else "quality"),
                risk_level=issue.get("risk_level") or "medium",
                field_name=issue.get("field_name"),
                issue_description=issue.get("issue_description") or "",
                suggestion=issue.get("suggestion"),
                source=source,
                # 法定扣分条款代码（LLM 建议无此值）——统计"最高频扣分条款"用
                rule_code=issue.get("rule_code"),
            )
            db.add(qc)

        try:
            await db.commit()
        except Exception as exc:
            # 持久化失败不影响前端实时展示（前端通过 SSE 已收到结果）
            logger.error("qc_issues.save: commit_failed err=%s", exc)


# L3 治本路线（2026-05-18）：
#   评分由 qc_engine.scorer.score() 驱动（浙江省 PDF 1:1 法定标准）。
#   原 calc_grade_score 用了"自创扣分规则"（risk_level 浮点扣分 + 75/90 阈值），
#   不符合 PDF 注 5 / 备注 8 的法定阈值。整函数已删除——所有调用方切到
#   qc_engine 的 ScoreReport 模型。
