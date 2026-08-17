"""
管理后台 service 单元测试：
  - app/services/admin_record_service.py   全院病历列表分页 / 管理员修订
  （prompt_template_service 的用例已随该模块删除——2026-08-18 撤掉后台
   Prompt 管理 / 模型配置两页，提示词与模型参数归代码维护）

覆盖范围：
  AdminRecordService：
    - list_all_records：空库 / 分页 total+切片 / 按医生筛选 / 只含已签发 /
      content 预览截断 / 患者 fallback 字段
    - revise_record：404 / 版本号递增 + 新 RecordVersion(source=admin_revise) /
      审计日志调用（含修订理由）/ snapshot 缓存失效调用 / 连续修订继续递增

mock 策略（最小化）：
  - DB 全部走内存 SQLite 真实 ORM。
  - log_action / invalidate_encounter_snapshot 用 monkeypatch 替换为
    "记录调用参数"的桩——它们分别写独立审计会话、删 Redis key，测试里只需
    断言"被正确调用"，真实现已有各自的测试/降级逻辑。
"""
from datetime import date, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services import admin_record_service as ars_mod
from app.services.admin_record_service import AdminRecordService


# ── 公共 fixtures ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seed(async_db):
    """造基础数据：1 患者 + 2 医生 + 各自接诊，供病历列表/修订用例复用。"""
    pat = Patient(
        id="pat-adm-1", name="病历患者", gender="女",
        birth_date=date(1985, 3, 15), phone="13700000001",
        id_card="330102198503150000",
    )
    doc_a = User(id="doc-a", username="doc_a", password_hash="x",
                 real_name="医生甲", role="doctor")
    doc_b = User(id="doc-b", username="doc_b", password_hash="x",
                 real_name="医生乙", role="doctor")
    enc_a = Encounter(id="enc-adm-a", patient_id=pat.id, doctor_id=doc_a.id,
                      visit_type="outpatient",
                      visited_at=datetime(2026, 6, 1, 9, 0))
    enc_b = Encounter(id="enc-adm-b", patient_id=pat.id, doctor_id=doc_b.id,
                      visit_type="inpatient",
                      visited_at=datetime(2026, 6, 2, 9, 0))
    async_db.add_all([pat, doc_a, doc_b, enc_a, enc_b])
    await async_db.commit()
    return SimpleNamespace(pat=pat, doc_a=doc_a, doc_b=doc_b,
                           enc_a=enc_a, enc_b=enc_b)


async def _mk_record(db, *, encounter_id, status="submitted",
                     submitted_at=None, content="病历全文内容", version_no=1):
    """直接落库一条病历 + 最新版本（list 查询只读，不需要走签发全流程）。"""
    rec = MedicalRecord(
        encounter_id=encounter_id, record_type="outpatient",
        status=status, current_version=version_no,
        submitted_at=submitted_at or datetime(2026, 6, 5, 10, 0),
    )
    db.add(rec)
    await db.flush()
    db.add(RecordVersion(
        medical_record_id=rec.id, version_no=version_no,
        content={"text": content}, source="manual",
    ))
    await db.commit()
    return rec


# ── AdminRecordService.list_all_records ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_records_empty(async_db):
    """空库：total=0，items 为空列表。"""
    result = await AdminRecordService(async_db).list_all_records(page=1, page_size=10)
    assert result == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_list_records_pagination(async_db, seed):
    """3 条已签发病历，page_size=2：第一页 2 条、第二页 1 条，total 恒为 3。"""
    for i in range(3):
        await _mk_record(async_db, encounter_id=seed.enc_a.id,
                         submitted_at=datetime(2026, 6, 5, 10, i))
    svc = AdminRecordService(async_db)
    page1 = await svc.list_all_records(page=1, page_size=2)
    page2 = await svc.list_all_records(page=2, page_size=2)
    assert page1["total"] == page2["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    # 按签发时间倒序：第一页第一条是最晚签发的（10:02）
    assert page1["items"][0]["submitted_at"] == datetime(2026, 6, 5, 10, 2)


@pytest.mark.asyncio
async def test_list_records_filter_by_doctor(async_db, seed):
    """doctor_id 筛选：只返回该医生接诊的病历。"""
    await _mk_record(async_db, encounter_id=seed.enc_a.id)  # 医生甲
    await _mk_record(async_db, encounter_id=seed.enc_b.id)  # 医生乙
    svc = AdminRecordService(async_db)
    result = await svc.list_all_records(page=1, page_size=10, doctor_id="doc-b")
    assert result["total"] == 1
    assert result["items"][0]["doctor_name"] == "医生乙"


@pytest.mark.asyncio
async def test_list_records_excludes_drafts(async_db, seed):
    """草稿病历不出现在管理列表（只看已签发的）。"""
    await _mk_record(async_db, encounter_id=seed.enc_a.id, status="draft")
    result = await AdminRecordService(async_db).list_all_records(page=1, page_size=10)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_list_records_preview_truncation(async_db, seed):
    """正文超 100 字：content_preview 截断加省略号，content 仍是全文。"""
    long_text = "长" * 150
    await _mk_record(async_db, encounter_id=seed.enc_a.id, content=long_text)
    item = (await AdminRecordService(async_db).list_all_records(
        page=1, page_size=10))["items"][0]
    assert item["content_preview"] == "长" * 100 + "..."
    assert item["content"] == long_text


@pytest.mark.asyncio
async def test_list_records_patient_fallback_fields(async_db, seed):
    """item 带患者 fallback 字段与接诊信息（病案首页渲染依赖）。"""
    await _mk_record(async_db, encounter_id=seed.enc_a.id)
    item = (await AdminRecordService(async_db).list_all_records(
        page=1, page_size=10))["items"][0]
    assert item["patient_name"] == "病历患者"
    assert item["patient_phone"] == "13700000001"
    assert item["patient_birth_date"] == "1985-03-15"
    assert item["visit_type"] == "outpatient"
    assert item["visit_time"] == "2026-06-01T09:00:00"
    # 医生未挂科室（department_id=None）：outerjoin 不丢数据，科室名为 None
    assert item["department_name"] is None


# ── AdminRecordService.revise_record ─────────────────────────────────────────


@pytest.fixture
def capture_revise_side_effects(monkeypatch):
    """把审计与缓存失效替换成记录桩，返回调用记录容器。

    log_action 真实现写独立 AsyncSessionLocal（指向另一个内存库，无表，
    会静默失败）；invalidate_encounter_snapshot 删 Redis key。两者都不是
    本测试的验证对象本体，但"是否被正确调用 + 参数"是合规关键路径，必须断言。
    """
    calls = SimpleNamespace(audits=[], invalidated=[])

    async def _fake_log_action(**kwargs):
        calls.audits.append(kwargs)

    async def _fake_invalidate(encounter_id):
        calls.invalidated.append(encounter_id)

    monkeypatch.setattr(ars_mod, "log_action", _fake_log_action)
    monkeypatch.setattr(ars_mod, "invalidate_encounter_snapshot", _fake_invalidate)
    return calls


@pytest.mark.asyncio
async def test_revise_missing_record_404(async_db, capture_revise_side_effects):
    """修订不存在的病历 → 404，且不产生审计/缓存副作用。"""
    admin = SimpleNamespace(id="admin-1", real_name="管理员", username="admin", role="super_admin")
    with pytest.raises(HTTPException) as exc:
        await AdminRecordService(async_db).revise_record(
            "no-such-record", "新内容", "修正错别字", admin)
    assert exc.value.status_code == 404
    assert capture_revise_side_effects.audits == []
    assert capture_revise_side_effects.invalidated == []


@pytest.mark.asyncio
async def test_revise_increments_version_and_audits(async_db, seed, capture_revise_side_effects):
    """修订主路径：版本 +1、新版本 source=admin_revise、审计含理由、失效 snapshot。"""
    rec = await _mk_record(async_db, encounter_id=seed.enc_a.id, version_no=1)
    admin = SimpleNamespace(id="admin-1", real_name="管理员", username="admin", role="super_admin")

    result = await AdminRecordService(async_db).revise_record(
        rec.id, "修订后的完整正文", "患者姓名录入错误", admin)

    # 返回值与主表版本指针
    assert result["ok"] is True
    assert result["new_version_no"] == 2
    assert (await async_db.get(MedicalRecord, rec.id)).current_version == 2

    # 新 RecordVersion：旧版本保留，新版本结构正确
    versions = (await async_db.execute(
        select(RecordVersion)
        .where(RecordVersion.medical_record_id == rec.id)
        .order_by(RecordVersion.version_no)
    )).scalars().all()
    assert [v.version_no for v in versions] == [1, 2]
    assert versions[1].source == "admin_revise"
    assert versions[1].content == {"text": "修订后的完整正文"}
    assert versions[1].triggered_by == "admin-1"

    # 审计日志：动作 + 理由留痕 + 管理员署名
    assert len(capture_revise_side_effects.audits) == 1
    audit = capture_revise_side_effects.audits[0]
    assert audit["action"] == "revise_record"
    assert audit["resource_id"] == rec.id
    assert "患者姓名录入错误" in audit["detail"]
    assert audit["user_id"] == "admin-1"

    # snapshot 缓存失效：医生工作台下次打开拿到最新版
    assert capture_revise_side_effects.invalidated == [seed.enc_a.id]


@pytest.mark.asyncio
async def test_revise_twice_keeps_incrementing(async_db, seed, capture_revise_side_effects):
    """连续修订两次：版本号 2 → 3 连续递增，历史版本全部保留。"""
    rec = await _mk_record(async_db, encounter_id=seed.enc_a.id, version_no=1)
    admin = SimpleNamespace(id="admin-1", real_name="管理员", username="admin", role="super_admin")
    svc = AdminRecordService(async_db)
    await svc.revise_record(rec.id, "第一次修订", "理由1", admin)
    result = await svc.revise_record(rec.id, "第二次修订", "理由2", admin)
    assert result["new_version_no"] == 3
    count = len((await async_db.execute(
        select(RecordVersion).where(RecordVersion.medical_record_id == rec.id)
    )).scalars().all())
    assert count == 3  # 初始 1 版 + 修订 2 版，旧版永久保留
