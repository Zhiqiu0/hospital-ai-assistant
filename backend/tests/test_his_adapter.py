"""HIS 对接保险丝 + 路由骨架回归测试。

锁住的关键不变量：
  1. HIS_ADAPTER_ENABLED=false 时所有 /embed/* /desktop/* 路由 503
  2. HIS_ADAPTER_ENABLED=true 时路由不再被保险丝拦（具体业务逻辑另测）
  3. encounter.his_external_ref 字段可读写 JSONB
  4. config_loader 能加载 jinsuanpan_map.yaml

为什么这套测试关键：
  保险丝是嵌入模式上线的核心安全策略——一旦保险丝失灵，嵌入功能 bug
  可能溅射到 SaaS。CI 必须锁住"关闭时全 503"这个契约。
"""
import pytest

from app.config import settings
from app.his_adapter import config_loader
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


def test_config_loader_loads_jinsuanpan_map():
    """加载金算盘字段映射 YAML。"""
    mapping = config_loader.get_map("H33052300957")
    assert mapping is not None, "金算盘 YAML 必须能按 hospital code 找到"
    assert mapping["hospital"]["his_brand"] == "jinsuanpan"
    # 关键字段必须存在（保证 Agent 不会因 YAML 残缺崩）
    assert "intake_dialog" in mapping
    assert "record_page" in mapping
    assert "diagnosis_panel" in mapping
    assert "vital_signs" in mapping


def test_config_loader_returns_none_for_unknown_hospital():
    """未配置的医院应返回 None，让 Agent 走 fallback。"""
    mapping = config_loader.get_map("UNKNOWN_HOSPITAL_CODE")
    assert mapping is None


def test_supported_hospitals_list():
    """支持的医院列表至少包含金算盘那一家。"""
    hospitals = config_loader.list_supported_hospitals()
    assert len(hospitals) >= 1
    codes = {h["code"] for h in hospitals}
    assert "H33052300957" in codes


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
