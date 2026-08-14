"""检验报告存储与卡死回收（2026-08-14 第八轮审计）。

两条都源自同一个模块：

  #落盘位置算错一层：lab_reports_service 在 app/services/ 下（距 backend 三层），
   却照抄了 app/api/v1/ 下四层文件的 parents[3]。容器里 WORKDIR=/app、代码铺在
   /app 下，于是原图写到容器根的 /uploads，而 compose 只挂了 /app/uploads：
   每次 deploy 重建容器全部消失，且 backup.sh 打包的是 /app/uploads——
   这些带患者姓名与全部检验结果的原图**一次都没被备份过**。
   路径穿越校验用的是同一个错误 root，所以自洽通过、不报任何错。

  #解析卡死：先落 analyzing → 最长 3 分钟外部调用 → 再落 done。
   部署重启（每次 deploy 必然发生）打断后第二次 commit 永不执行，
   记录永久停在 analyzing，医生看到空卡片且无重试入口。
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.storage_paths import BACKEND_ROOT, UPLOADS_ROOT, resolve_upload_path
from app.models.lab_report import LabReport
from app.services.lab_reports_service import reclaim_stale_analyzing


def test_uploads_root_指向backend下而非仓库根():
    """这就是那个差一层的 bug——落到仓库根就等于落在挂载卷之外。"""
    assert UPLOADS_ROOT == BACKEND_ROOT / "uploads"
    assert UPLOADS_ROOT.name == "uploads"
    assert UPLOADS_ROOT.parent.name == "backend"


def test_检验报告与语音用同一个uploads根():
    """两个模块在不同目录深度，各自数 parents 层数正是 bug 的来源。"""
    from app.api.v1 import ai_voice_records  # noqa: F401
    from app.services import lab_reports_service  # noqa: F401

    # 两边现在都从单一真源取，天然一致；这条测试锁住"不许再自己数层数"
    import inspect
    for mod in (ai_voice_records, lab_reports_service):
        src = inspect.getsource(mod)
        assert 'parents[3] / "uploads"' not in src, (
            f"{mod.__name__} 又在自己数 parents 层数了"
        )


def test_路径穿越被挡下():
    with pytest.raises(ValueError):
        resolve_upload_path("../../etc/passwd")


@pytest.mark.asyncio
async def test_卡死的解析被回收成可见的失败态(async_db):
    async_db.add(LabReport(
        id="lr-stale", doctor_id="doc-1", status="analyzing",
        file_path="lab_reports/e1/x.pdf",
        created_at=datetime.now() - timedelta(hours=1),
    ))
    await async_db.commit()

    n = await reclaim_stale_analyzing(async_db)
    assert n == 1

    row = (await async_db.execute(
        select(LabReport).where(LabReport.id == "lr-stale")
    )).scalar_one()
    assert row.status == "done", "仍卡在 analyzing，医生看到的还是空卡片"
    assert "中断" in (row.ocr_text or ""), "没有给医生任何可读的失败说明"


@pytest.mark.asyncio
async def test_正在跑的解析不会被误回收(async_db):
    """刚提交几秒的任务还在跑，不能被当成卡死的收掉。"""
    async_db.add(LabReport(
        id="lr-running", doctor_id="doc-1", status="analyzing",
        file_path="lab_reports/e1/y.pdf",
        created_at=datetime.now(),
    ))
    await async_db.commit()

    n = await reclaim_stale_analyzing(async_db)
    assert n == 0

    row = (await async_db.execute(
        select(LabReport).where(LabReport.id == "lr-running")
    )).scalar_one()
    assert row.status == "analyzing"


@pytest.mark.asyncio
async def test_删除报告会连磁盘原图一起删(async_db, tmp_path, monkeypatch):
    """file_path 是指向那个文件的唯一引用，行一删就再也找不到它了。"""
    import app.services.lab_reports_service as svc

    rel = "lab_reports/enc-1/photo.jpg"
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8fake-jpeg-with-PHI")
    assert target.exists()

    monkeypatch.setattr(svc, "resolve_upload_path", lambda p: tmp_path / p)

    report = LabReport(id="lr-del", doctor_id="doc-1", status="done", file_path=rel)
    async_db.add(report)
    await async_db.commit()

    await svc.delete_report(async_db, report)

    assert not target.exists(), "库里的行删了，带 PHI 的原图还留在服务器上"


@pytest.mark.asyncio
async def test_原图删不掉也不挡住删行(async_db, monkeypatch):
    """不能让医生连"删掉错误报告"都做不到。"""
    import app.services.lab_reports_service as svc

    def _boom(_p):
        raise OSError("permission denied")

    monkeypatch.setattr(svc, "resolve_upload_path", _boom)

    report = LabReport(id="lr-del2", doctor_id="doc-1", status="done",
                       file_path="lab_reports/e/z.jpg")
    async_db.add(report)
    await async_db.commit()

    await svc.delete_report(async_db, report)

    rows = (await async_db.execute(
        select(LabReport).where(LabReport.id == "lr-del2")
    )).scalars().all()
    assert rows == []
