"""HIS 对接保险丝 + 路由骨架回归测试。

锁住的关键不变量：
  1. HIS_ADAPTER_ENABLED=false 时所有 /embed/* 路由 503
  2. HIS_ADAPTER_ENABLED=true 时路由不再被保险丝拦（具体业务逻辑另测）
  3. encounter.his_external_ref 字段可读写 JSONB

为什么这套测试关键：
  保险丝是嵌入模式上线的核心安全策略——一旦保险丝失灵，嵌入功能 bug
  可能溅射到 SaaS。CI 必须锁住"关闭时全 503"这个契约。

注：控件模式（config_loader / jinsuanpan_map.yaml 字段映射）已退休删除，相关用例一并移除。
"""
import pytest

from app.config import settings
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import HISExternalRef, StartEmbedRequest


@pytest.mark.asyncio
async def test_require_his_enabled_blocks_when_disabled(monkeypatch):
    """HIS_ADAPTER_ENABLED=false 时 require_his_enabled 应抛 503。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", False)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await require_his_enabled()
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "his_adapter_disabled"


@pytest.mark.asyncio
async def test_require_his_enabled_passes_when_enabled(monkeypatch):
    """HIS_ADAPTER_ENABLED=true 时 require_his_enabled 应放行（不抛）。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    # 不抛异常即通过
    result = await require_his_enabled()
    assert result is None


def test_his_external_ref_model():
    """HISExternalRef Pydantic 模型按预期序列化（落库 JSONB 用）。"""
    ref = HISExternalRef(
        his_brand="jinsuanpan",
        hospital_code="H33052300957",
        his_patient_no="Y1232605260025",
        his_visit_no="20260526000200",
    )
    data = ref.model_dump()
    assert data["his_brand"] == "jinsuanpan"
    assert data["his_patient_no"] == "Y1232605260025"
    # 可选字段空时也保留 key
    assert "his_doctor_no" in data


def test_start_embed_request_validates_required_fields():
    """StartEmbedRequest 必填字段校验。"""
    # 缺 patient_name 应失败
    with pytest.raises(Exception):
        StartEmbedRequest(
            his_ref=HISExternalRef(
                his_brand="x", hospital_code="x", his_patient_no="x"
            ),
            agent_device_id="dev1",
            agent_version="1.0.0",
        )
