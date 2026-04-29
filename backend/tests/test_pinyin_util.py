"""
姓名拼音索引工具单元测试（utils.pinyin）

覆盖：
  - 单字 / 多字 全拼生成
  - 首字母生成
  - 全拼/首字母 混拼组合（市面搜索框标准体验）
  - 多音字（heteronym）展开
  - 空串、英文姓名、含数字姓名等边界
  - is_ascii_alpha 判定逻辑
"""
import pytest

from app.utils.pinyin import compute_pinyin, is_ascii_alpha


def _tokens(text: str) -> set[str]:
    """工具：把 compute_pinyin 返回的空格分隔串拆成集合，便于 set 包含断言。"""
    return set(text.split()) if text else set()


def test_single_char_full_and_initials():
    """单字：全拼+首字母 同字段都给。"""
    full, init = compute_pinyin("张")
    assert "zhang" in _tokens(full)
    assert "z" in _tokens(full)         # 首字母也在 full 里（混拼覆盖）
    assert _tokens(init) == {"z"}


def test_two_chars_covers_all_mix_combos():
    """两字"张三"：full 里要同时含 zhangsan / zhangs / zsan / zs 四种组合。"""
    full, init = compute_pinyin("张三")
    full_set = _tokens(full)
    assert "zhangsan" in full_set      # 全拼
    assert "zhangs" in full_set        # 全+首
    assert "zsan" in full_set          # 首+全
    assert "zs" in full_set            # 纯首字母
    assert _tokens(init) == {"zs"}


def test_heteronym_expands_all_readings():
    """多音字"查"=zha/cha：full 中两种读音的全拼/首字母组合都要在。"""
    full, init = compute_pinyin("查张三")
    full_set = _tokens(full)
    # 两种读音的纯全拼
    assert "zhazhangsan" in full_set
    assert "chazhangsan" in full_set
    # 两种读音的首字母组合
    init_set = _tokens(init)
    assert "zzs" in init_set
    assert "czs" in init_set


def test_empty_returns_empty_strings():
    """空姓名直接返回空串，不抛异常。"""
    full, init = compute_pinyin("")
    assert full == ""
    assert init == ""


def test_non_chinese_name_lowercased():
    """英文姓名也能进索引，全部小写。"""
    full, init = compute_pinyin("Tom")
    # pypinyin 对英文逐字符返回，组合后每字符就是它自己
    full_set = _tokens(full)
    assert "tom" in full_set
    init_set = _tokens(init)
    assert "tom" in init_set


def test_combinations_capped():
    """组合数有上限，不会因长姓名+多音字爆炸到几百条。"""
    full, _ = compute_pinyin("查单翟曾重")  # 5 个常见多音字
    # 上限 32，最终输出 token 数应不超过该值
    assert len(_tokens(full)) <= 32


def test_is_ascii_alpha_true_cases():
    assert is_ascii_alpha("zhang") is True
    assert is_ascii_alpha("ZS") is True
    assert is_ascii_alpha("Tom") is True


def test_is_ascii_alpha_false_cases():
    assert is_ascii_alpha("") is False              # 空串不算
    assert is_ascii_alpha("张三") is False          # 汉字
    assert is_ascii_alpha("zhang3") is False        # 含数字
    assert is_ascii_alpha("zh ang") is False        # 含空格
    assert is_ascii_alpha("zhang-san") is False     # 含连字符
