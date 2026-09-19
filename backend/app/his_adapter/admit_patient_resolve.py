# -*- coding: utf-8 -*-
"""HIS 接诊推送·患者身份归并（his_adapter/admit_service.py 三拆之一，2026-09-19）。

纯机械搬移，零逻辑改动（862 行超服务上限 2.4 倍的拆分，联调前完成以便
联调验收的是最终形态）。本模块管"推送里的患者是谁"：出生日期多形态解析、
重推字段刷新、按 HIS 患者号/强弱键找档或建档（含脏档案两级降级兜底）。
被 admit_service.process_admit 调用；admit_service 保留同名 re-export，
既有测试与调用方 import 路径不变。

行数说明（335 行，超 250 上限但有意不再细拆）：五个函数是"患者是谁"
这一个问题的紧耦合链（解析→字段可用性→查重三级→建档两级降级→重推
刷新），拆散会让读者在文件间跳转追一条完整判定链——内聚优先于数字，
与 QC rubrics 数据表的豁免同理。
"""
import logging

from datetime import date
from typing import Optional
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.utils.text_clean import strip_invisible
from app.his_adapter.admit_types import AdmitError, AdmitResult  # noqa: F401

logger = logging.getLogger(__name__)

# 推送 gender（接口枚举 male/female/unknown）→ patients 表中文口径
_GENDER_MAP = {"male": "男", "female": "女", "unknown": "未知"}


def _parse_his_birth_date(raw: Optional[str], visit_id: str):
    """把 HIS 各种形态的出生日期解析成 date；解析不了返回 None 并留痕。

    2026-09-02 从 _find_or_create_patient 内联段抽出（纯搬移，行为逐字不变），
    供首次建档与重推补空两处共用——两边各写一份必然漂移。
    """
    if not raw:
        return None
    try:
        # 兼容 YYYYMMDD 紧凑写法：CSRQ 在 HIS 里常是 date/int 列，
        # 序列化出来就是 19680520。入参容错已让它不再被拒收，但若这里
        # 解析不了就等于静默丢掉出生日期——年龄影响用药与诊断判断，
        # 不能默默丢。补一次紧凑格式转换即可，不放宽其它规则。
        raw_bd = raw.strip()
        if len(raw_bd) == 8 and raw_bd.isdigit():
            raw_bd = f"{raw_bd[:4]}-{raw_bd[4:6]}-{raw_bd[6:]}"
        # 常见厂商形态归一（2026-08-29 第五轮 HIS 契约审计）：
        # "1968-05-20 00:00:00"（datetime 列序列化）→ 截前 10 位；
        # "1968/05/20"、"1968.5.20" → 分隔符归一；
        # "1968-5-20"（不补零）→ 拆段补零。fromisoformat 只认补零 ISO，
        # 这些形态原先全部静默丢弃且无日志，年龄空缺联调无痕。
        raw_bd = raw_bd[:10].strip().replace("/", "-").replace(".", "-").strip("-")
        parts = raw_bd.split("-")
        if len(parts) == 3 and all(x.isdigit() for x in parts):
            raw_bd = f"{parts[0]}-{parts[1]:0>2}-{parts[2]:0>2}"
        parsed = date.fromisoformat(raw_bd)
        # 未来出生日期丢弃留痕（2026-08-29 第七轮审计）：负年龄会进病案
        # 首页与回写，无合法场景；与解析失败同口径不拒收接诊
        if parsed > date.today():
            logger.warning(
                "his_admit.patient: birth_date 在未来已丢弃 raw=%r visit_id=%s",
                raw, visit_id)
            return None
        return parsed
    except ValueError:
        # 解析不了留空不阻塞建档，但必须留痕——年龄影响用药判断，不能默默丢
        logger.warning(
            "his_admit.patient: birth_date 解析失败已丢弃 raw=%r visit_id=%s",
            raw, visit_id,
        )
        return None


# 重推时可补空的患者字段：(payload 字段, Patient 列)。
# 只收「跨就诊认人」与「病历署名」真正要用的那几个，不做全量同步——
# 重推的语义是"同一次就诊又推了一遍"，不是"以 HIS 为准全量覆盖档案"。
_REPUSH_FILLABLE = (
    ("patient_no", "patient_no"),
    ("id_card", "id_card"),
    ("phone", "phone"),
    ("birth_date", "birth_date"),
)
# 建档降级时用的占位名，重推补齐真名时按"空"处理（见 _find_or_create_patient）
_PLACEHOLDER_NAME = "未知患者"


def _field_acceptable(col: str, value) -> bool:
    """单字段是否通过建档校验——与 _find_or_create_patient 的逐字段试探同口径。"""
    if col not in ("id_card", "phone"):
        return True
    from app.schemas.patient import PatientCreate   # 与建档路径同一处局部导入
    try:
        PatientCreate(name="校验探针", gender="未知", **{col: value})
        return True
    except ValidationError:
        return False


async def _refresh_patient_from_repush(db, patient, payload, enc) -> None:
    """同 visit_id 重推时更新患者信息（2026-09-02 HIS 异常面演练补）。

    原实现在幂等复用分支里只处理医生改派，患者信息一个字段都不看——同一个
    visit_id 推来不同的姓名/身份证，静默忽略且无任何告警。两个现实后果：

      ① **急诊无名氏补不回来**。本模块明确写了"姓名不可清洗 → 占位名『未知
         患者』+ 告警"的降级路径（头号不变量是绝不因脏数据拒收接诊），而 HIS
         侧补齐姓名后重推同一 visit_id，正是最自然的补救方式——被忽略后那位
         患者永远叫"未知患者"，身份证也补不进来，于是跨就诊认人（靠 id_card /
         patient_no）也一并失效，他下次来还是新建档案。
      ② **挂错号纠正后我方不跟**。HIS 侧把张三改成李四重推，工作台仍显示张三，
         医生对着错的患者写病历，署名与病案首页全错。

    处理口径与档案合并（patient_merge_service）一致：**补空不覆盖**。
      · 我方为空（姓名为占位名也算空）而 HIS 有值 → 补上；
      · 两边都有值且不同 → **不静默覆盖**，记 warning + 在 his_external_ref
        里留痕。覆盖与否涉及"以谁为准"的业务口径，不该由这段代码替医院决定，
        但必须让人查得到"HIS 说是李四、我方记的是张三"。
    """
    filled: list[str] = []
    conflicts: list[str] = []

    # 姓名单独处理：占位名视为空
    new_name = (payload.patient_name or "").strip()
    if new_name and new_name != patient.name:
        if not patient.name or patient.name == _PLACEHOLDER_NAME:
            patient.name = new_name[:50]     # 与列宽对齐，超长截断不报错
            filled.append("name")
        else:
            conflicts.append(f"name:{patient.name}->{new_name}")

    for src, col in _REPUSH_FILLABLE:
        val = getattr(payload, src, None)
        val = val.strip() if isinstance(val, str) else val
        if not val:
            continue
        cur = getattr(patient, col, None)
        if not cur:
            # birth_date 是 Date 列，payload 里是字符串，复用建档时那套解析
            parsed = (_parse_his_birth_date(val, payload.visit_id)
                      if col == "birth_date" else val)
            # 走建档同一套字段校验（2026-09-02 自查补）：首次建档时 id_card /
            # phone 要过 PatientCreate（身份证含 GB 11643 校验位），不过就单独
            # 丢弃该字段。补空若直接 setattr 就绕过了这层——校验位错误的身份证
            # 会从重推这条路径溜进档案，而它正是跨就诊认人的强键，错的比没有更糟。
            if parsed and not _field_acceptable(col, parsed):
                logger.warning(
                    "his_admit.repush: %s 未通过校验，不补入档案 visit_id=%s",
                    col, payload.visit_id)
                continue
            if parsed:
                setattr(patient, col, parsed)
                filled.append(col)
        elif str(cur) != str(val):
            conflicts.append(f"{col}:{cur}->{val}")

    if conflicts:
        # 留痕进接诊的 HIS 引用，运维/医务科事后能查到这次冲突
        ref = dict(enc.his_external_ref or {})
        ref["patient_conflicts"] = conflicts
        enc.his_external_ref = ref
        flag_modified(enc, "his_external_ref")
        logger.warning(
            "his_admit.patient_conflict: visit_id=%s 重推的患者信息与本地不一致，"
            "未覆盖：%s", payload.visit_id, "; ".join(conflicts),
        )
    if filled or conflicts:
        await db.commit()
        from app.services.patient_cache import _invalidate_patient_cache
        await _invalidate_patient_cache(patient.id)
        if filled:
            logger.info("his_admit.patient_filled: visit_id=%s 补齐 %s",
                        payload.visit_id, ",".join(filled))



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
    cleaned_name = strip_invisible(payload.patient_name or "")  # 清单见 utils/text_clean
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

    birth_date = _parse_his_birth_date(payload.birth_date, payload.visit_id)

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


