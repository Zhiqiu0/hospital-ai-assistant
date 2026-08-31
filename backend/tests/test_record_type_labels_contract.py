# -*- coding: utf-8 -*-
"""打印件标题表必须覆盖后端全部 record_type（2026-08-31 法规形式要件审计）。

背景：`frontend/src/utils/recordExport.ts` 的 RECORD_TYPE_LABEL 是手工维护的
中文标题表，取值写法是 `RECORD_TYPE_LABEL[recordType] || recordType`——缺一个键
不会报错，而是**把英文 key 直接印在法定文书的标题栏上**。本次审计就发现它漏了
`emergency`：急诊接诊由 activeEncounterStore 按 visitType 设成 'emergency'，于是
急诊病历打印出来标题是 "emergency"、导出文件名是 emergency_张*.doc，这份纸交给
患者转诊或提交医调委即形式要件不合格，而系统全程无任何报错。

这类"两份清单各自维护"的漂移只能靠契约测试发现，故在**后端**（枚举的权威方）
反向读前端文件来锁：任何一方加了类型忘了同步，CI 立刻红。
"""
import re
from pathlib import Path

from app.services.ai.record_prompts import NEW_ARCH_RECORD_TYPES

_EXPORT_TS = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "utils" / "recordExport.ts"
)


def _frontend_label_keys() -> dict[str, str]:
    """从 recordExport.ts 里抠出 RECORD_TYPE_LABEL 的键值对。"""
    src = _EXPORT_TS.read_text(encoding="utf-8")
    m = re.search(
        r"RECORD_TYPE_LABEL:\s*Record<string,\s*string>\s*=\s*\{(.*?)\n\}",
        src, re.S,
    )
    assert m, "没能在 recordExport.ts 里定位 RECORD_TYPE_LABEL——它可能被改名或重构了"
    return dict(re.findall(r"(\w+)\s*:\s*['\"](.+?)['\"]", m.group(1)))


def test_每个后端record_type都有中文打印标题():
    labels = _frontend_label_keys()
    missing = set(NEW_ARCH_RECORD_TYPES) - set(labels)
    assert not missing, (
        f"病历类型 {sorted(missing)} 在 recordExport.ts 的 RECORD_TYPE_LABEL 里没有"
        "中文标题——打印件和导出文件名会直接印出英文 key，法定文书形式要件不合格"
    )


def test_标题表里没有后端不存在的类型():
    """反向防漂移：清单里留着已废弃的 key，会让人误以为那种文书还在用。"""
    labels = _frontend_label_keys()
    ghost = set(labels) - set(NEW_ARCH_RECORD_TYPES)
    assert not ghost, f"RECORD_TYPE_LABEL 里的 {sorted(ghost)} 在后端枚举中不存在"


def test_标题必须是中文():
    """防止有人为了让测试通过而填 `emergency: 'emergency'` 这种假标题。"""
    for key, label in _frontend_label_keys().items():
        assert re.search(r"[一-鿿]", label), (
            f"{key} 的标题 {label!r} 不含中文——法定文书标题必须是规范中文名称"
        )
