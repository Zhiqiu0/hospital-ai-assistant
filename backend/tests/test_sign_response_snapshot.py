"""签发响应直接携带冻结首页，避免前端再用可变患者/视图状态导出。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.v1.medical_records_write import QuickSaveRequest
from test_medical_record_quick_save import _make_encounter


async def test_quick_sign_returns_frozen_snapshot(async_db, monkeypatch):
    """走真实签发与快照生成，只隔离审计写入的独立连接。"""
    from app.api.v1 import medical_records_write as routes
    from app.config import settings
    monkeypatch.setattr(routes, 'log_action', AsyncMock())
    monkeypatch.setattr(settings, 'his_adapter_enabled', False)
    enc = await _make_encounter(async_db, encounter_id='sign-response-snapshot')
    result = await routes.quick_save_record(
        QuickSaveRequest(encounter_id=enc.id, record_type='outpatient', content='合成签发测试'),
        async_db, SimpleNamespace(id='doc-qs-1', role='doctor', username='test'),
    )
    assert result['patient_snapshot']['visit_type'] == 'outpatient'
    assert result['patient_snapshot']['name'] == f'患者-{enc.id}'
    assert result['submitted_at']
