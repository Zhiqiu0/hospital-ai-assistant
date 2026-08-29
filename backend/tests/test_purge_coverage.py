# -*- coding: utf-8 -*-
"""开业前清库脚本的表覆盖契约测试（2026-08-28 全量体检）。

背景：purge_clinical_data.py 的 PURGE_ORDER 是手工清单，08-21 新增的
diagnoses/qc_reports/qc_reviews 三张表没登记——漏删会被外键拦住父表删除，
清库在开业当天直接失败。本测试把「模型里的每张表要么在删除清单、要么在
保留清单」定为契约：以后加新表忘了登记，CI 立刻红灯。
"""
from app.database import Base


def _all_model_tables() -> set[str]:
    # 遍历导入 models 包下全部模块：app.main 的导入链并不覆盖所有模型
    # （如 models/config.py 的 QCRule 只被 service 层局部引用），漏导入会让
    # 本契约测试漏表，与它要防的问题同款
    import importlib
    import pkgutil

    import app.models as models_pkg
    for m in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{m.name}")
    return set(Base.metadata.tables.keys())


def test_every_table_is_either_purged_or_kept():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from purge_clinical_data import KEEP, PURGE_ORDER

    purged = {t for t, _ in PURGE_ORDER}
    kept = set(KEEP)
    tables = _all_model_tables()

    missing = tables - purged - kept
    assert not missing, (
        f"新表 {sorted(missing)} 未登记进 purge_clinical_data.py 的 "
        "PURGE_ORDER（要清）或 KEEP（要留）——不登记清库会被外键拦住失败"
    )
    # 清单里也不许有模型里不存在的表（防拼写错/表改名后清单漂移）
    ghost = (purged | kept) - tables
    assert not ghost, f"清单里的表 {sorted(ghost)} 在模型里不存在"
    # 一张表不能同时既清又留
    both = purged & kept
    assert not both, f"表 {sorted(both)} 同时出现在 PURGE_ORDER 与 KEEP"


def test_known_test_accounts_in_purge_list():
    """已知测试账号必须在清号名单里（2026-08-29 第六轮渗透审计回归锁）。

    qctest（质控员测试号）建于名单定稿之后，漏列了 8 天无人报警——它能
    只读全院已签发病历。这里把**记忆/文档里已知的**测试账号钉进 CI：
    名单里少了任何一个，测试立刻红。新增角色的测试账号也要追加到这里。
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from purge_test_accounts import TEST_USERNAMES

    known = {"doctor01", "zz", "e2e_doctor", "qctest"}
    missing = known - set(TEST_USERNAMES)
    assert not missing, (
        f"已知测试账号 {sorted(missing)} 不在 purge_test_accounts.TEST_USERNAMES——"
        "开业清号会把它原样带进生产"
    )
