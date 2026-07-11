"""
病历模板渲染器（services/ai/record_renderer.py）

L3 治本路线核心组件——把 LLM 返回的字段 dict 按统一模板拼成展示文本。

为什么需要：
  之前 LLM 直接输出病历正文，自由发挥导致行格式偏离 prompt 契约
  （如把"切诊·脉象：xxx"写成"切诊：xxx"，把舌象塞进望诊行），
  导致 QC 规则和前端行级写入找不到对应字段误报"未填写"。

  新架构下 LLM 只填字段值（chat_json_stream 拿 JSON），由本模块
  按章节级 / 子行级模板严格拼装，输出 100% 符合：
    - 后端 _SECTION_LINE_PREFIXES 解析逻辑
    - 前端 FIELD_TO_LINE_PREFIX 行级写入逻辑
    - QC 完整性规则的 §章节名 匹配

结构（2026-07-11 拆分为多模块，本文件仅保留对外入口 + 路由表）：
  - _render_common.py：底层 helper + 2 个通用渲染器（叶子模块）
  - _render_visit.py：门诊 / 急诊 / 住院入院记录
  - _render_course.py：7 个病程 / 手术类渲染器
  对外导入面保持不变——历史符号仍从 app.services.ai.record_renderer 导出。

测试：tests/test_record_renderer.py 对每个 render_* 函数断言输出符合契约。
"""

from __future__ import annotations

# ─── re-export：拆分后保持对外导入面零改动 ───────────────────────────
# _merge_tcm_diagnosis 被 tests 直接导入；render_* 被 tests / 路由表引用。
from app.services.ai._render_common import _merge_tcm_diagnosis  # noqa: F401
from app.services.ai._render_visit import (
    render_admission_note,
    render_emergency,
    render_outpatient,
)
from app.services.ai._render_course import (
    render_course_record,
    render_discharge_record,
    render_first_course_record,
    render_op_record,
    render_post_op_record,
    render_pre_op_summary,
    render_senior_round,
)


# ─── 公共入口 ────────────────────────────────────────────────────────


# record_type → render 函数的路由表（注册式，新增 record_type 在这加一行即可）
_RENDERERS = {
    "outpatient": render_outpatient,
    "emergency": render_emergency,
    "admission_note": render_admission_note,
    "first_course_record": render_first_course_record,
    "course_record": render_course_record,
    "senior_round": render_senior_round,
    "discharge_record": render_discharge_record,
    "pre_op_summary": render_pre_op_summary,
    "op_record": render_op_record,
    "post_op_record": render_post_op_record,
}


def render_record(record_type: str, data: dict, **meta) -> str:
    """按 record_type 路由到对应渲染器。

    Args:
        record_type: 见 _RENDERERS 注册表
        data: LLM 返回的字段 dict（key 必须在对应 schema 内）
        **meta: 渲染器需要的请求层元数据（visit_time / onset_time / patient_gender 等，
                未被某个 renderer 用到的会被 **_extra 吃掉）

    Raises:
        NotImplementedError: record_type 不在注册表（路由层应用 NEW_ARCH_RECORD_TYPES 白名单过滤）。
    """
    renderer = _RENDERERS.get(record_type)
    if renderer is None:
        raise NotImplementedError(f"record_type={record_type!r} 未注册渲染器")
    return renderer(data, **meta)
