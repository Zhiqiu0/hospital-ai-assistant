# -*- coding: utf-8 -*-
"""日志里的 PHI 脱敏（2026-09-02 可观测性专项）。

本项目的既定口径是**日志里用 ID 不用姓名**——审计日志的 detail 全部写 UUID，
正是为此。用 AST 扫了一遍全仓 logger 调用的参数，发现同名同生日查重那条把
患者全名写进了 app.log（保留 30 天）。
"""
from app.core.logging_config import mask_name


def test_保留首字其余打码():
    assert mask_name("张三") == "张*"
    assert mask_name("欧阳明月") == "欧***"


def test_单字姓名不越界():
    assert mask_name("李") == "李"


def test_空值给占位符():
    """姓名缺失是真实场景（急诊无名氏），不能让日志出现 'None'。"""
    assert mask_name(None) == "-"
    assert mask_name("") == "-"
    assert mask_name("   ") == "-"


def test_不泄露全名():
    """脱敏后原名不可从日志还原——这是这个函数存在的全部意义。"""
    for name in ("王大锤", "司马相如", "李建国"):
        masked = mask_name(name)
        assert name not in masked
        assert masked.startswith(name[0]) and len(masked) == len(name)
