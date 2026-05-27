"""qc_service.scan 端到端回归测试

核心目的：锁死 issue_type NOT NULL 不再炸（2026-05-18 commit d9c4861 引入的 bug）
  - 旧版规则引擎在 completeness_rules.py 里手填 issue_type="completeness"
  - 新版浙江省 PDF 1:1 重写时，qc_service.py 里手工构造 issue_data 漏了 issue_type
  - 导致 INSERT QCIssue 时 issue_type=NULL → NotNullViolationError → 500
  - 而新代码只测了纯函数（rubric / scorer / section），没有覆盖到落库路径

本测试覆盖：
  1. scan() 完整跑通不抛异常
  2. 所有持久化的 QCIssue 都有 issue_type
  3. 规则引擎产出的 issue source='rule' + issue_type='completeness'
"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from app.models.medical_record import MedicalRecord, RecordVersion, QCIssue
from app.services.ai.qc_service import QCService


@pytest.mark.asyncio
async def test_scan_persists_issues_with_issue_type(async_db):
    """空病历跑 qc_scan 必然命中"患者基础信息缺项"等多条规则，
    所有写入的 QCIssue 必须有 issue_type，否则 INSERT 会因 NOT NULL 约束失败。"""
    # 准备：建一个最小可扫描的病历 + 当前版本
    record = MedicalRecord(
        encounter_id="test-enc-1",
        record_type="outpatient",
        current_version=1,
        status="editing",
    )
    async_db.add(record)
    await async_db.flush()

    version = RecordVersion(
        medical_record_id=record.id,
        version_no=1,
        content={},  # 空内容 → 必然触发完整性规则
        source="doctor_edited",
        triggered_by="test-user",
    )
    async_db.add(version)
    await async_db.commit()

    # mock LLM 调用（避免真连阿里云 + 跑得快）
    fake_llm_resp = {"issues": []}
    with patch(
        "app.services.ai.qc_service.llm_client.chat_json_stream",
        new=AsyncMock(return_value=fake_llm_resp),
    ), patch(
        "app.services.ai.qc_service.get_model_options",
        new=AsyncMock(return_value={"temperature": 0, "max_tokens": 2000, "model_name": "test"}),
    ):
        service = QCService(async_db)
        result = await service.scan(record.id)

    # 断言：接口返回成功
    assert result["code"] == 0
    assert "task_id" in result["data"]

    # 断言：QCIssue 全部落库 + 全部有 issue_type（防回归核心点）
    issues = (await async_db.execute(
        select(QCIssue).where(QCIssue.medical_record_id == record.id)
    )).scalars().all()

    assert len(issues) > 0, "空病历应该至少命中一条完整性规则"
    for issue in issues:
        assert issue.issue_type is not None, (
            f"QCIssue.issue_type 不能为 NULL（这是 NOT NULL 列），"
            f"否则 PostgreSQL 会抛 NotNullViolationError 让整个 scan 接口 500。"
            f"问题 issue id={issue.id} field={issue.field_name}"
        )
        # 规则引擎产出的 issue 应该归类为 completeness（与旧版 check_completeness 同语义）
        if issue.source == "rule":
            assert issue.issue_type == "completeness", (
                f"规则引擎 issue 应统一 issue_type='completeness'，"
                f"实际 source={issue.source} issue_type={issue.issue_type}"
            )
