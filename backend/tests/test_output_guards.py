"""output_guards 数值真实性守卫单测（2026-06-11）

覆盖场景：E2E 实测中 LLM 补全编造 "T 36.5℃ P 72 BP 120/80" 等默认正常值，
守卫应剔除无出处数值、保留有出处数值与描述性文字。
"""

from app.services.ai.output_guards import strip_unsubstantiated_vitals


SOURCE_WITH_VITALS = "主诉：头晕3天。体格检查：T:36.8℃ P:88次/分 BP:135/85mmHg"
SOURCE_NO_VITALS = "主诉：咳嗽咳痰2天。现病史：受凉后咳嗽，自服止咳糖浆效果不佳。"


class TestStripUnsubstantiatedVitals:
    def test_编造的全套生命体征被剔除_描述文字保留(self):
        value = "T 36.5℃，P 72次/分，R 18次/分，BP 120/80mmHg。神志清，心肺腹未见明显异常。"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_NO_VITALS)
        assert "36.5" not in cleaned
        assert "120/80" not in cleaned
        assert "神志清" in cleaned
        assert "心肺腹未见明显异常" in cleaned

    def test_有出处的数值保留(self):
        value = "T:36.8℃ P:88次/分 BP:135/85mmHg，神清。"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_WITH_VITALS)
        assert "36.8" in cleaned
        assert "135/85" in cleaned
        assert "神清" in cleaned

    def test_混合场景_有出处保留_无出处剔除(self):
        # 体温有出处（36.8），血氧是编造的（98 不在 source 里）
        value = "T:36.8℃，SpO2 98%，查体合作。"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_WITH_VITALS)
        assert "36.8" in cleaned
        assert "98" not in cleaned
        assert "查体合作" in cleaned

    def test_纯描述文字不受影响(self):
        value = "神志清，查体合作，心肺腹未见明显异常。"
        assert strip_unsubstantiated_vitals(value, SOURCE_NO_VITALS) == value

    def test_非体征数值不误删(self):
        # "3天" "2片" 这类病程/用量数字不是体征 token，不应被动
        value = "病程3天，自服布洛芬2片效果不佳。"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_NO_VITALS)
        assert "3天" in cleaned
        assert "2片" in cleaned

    def test_全部内容被剔除时返回空串(self):
        value = "BP 130/85mmHg"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_NO_VITALS)
        assert cleaned == ""

    def test_空值直接返回(self):
        assert strip_unsubstantiated_vitals("", SOURCE_NO_VITALS) == ""

    def test_剔除后无悬空标点(self):
        value = "T 36.5℃，P 72次/分。神志清。"
        cleaned = strip_unsubstantiated_vitals(value, SOURCE_NO_VITALS)
        assert not cleaned.startswith("，")
        assert "，，" not in cleaned
        assert "，。" not in cleaned
