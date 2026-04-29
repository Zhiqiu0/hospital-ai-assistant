"""
中文姓名拼音索引工具（utils/pinyin.py）

为患者搜索框提供市面常见的拼音/首字母/混拼匹配能力——医生敲 "zhang"、
"zs"、"zhangs"、"zsan" 都能搜到 "张三"。

设计要点：
  1. 单字粒度：每个汉字独立生成"全拼"和"首字母"两种形态。
  2. 笛卡尔积：每字两种形态自由组合，N 字姓名产生 2^N 个组合，覆盖：
       全拼      "zhangsan"  ← zhang+san
       全+首     "zhangs"    ← zhang+s
       首+全     "zsan"      ← z+san
       首字母    "zs"        ← z+s
  3. 多音字：用 pypinyin 的 heteronym=True 拿到所有读音
       （"查"=zha/cha、"单"=dan/shan、"翟"=zhai/di），与上面再做笛卡尔积。
  4. 组合数有上限（_MAX_COMBINATIONS）防止"3 个多音字 + 4 字名"时爆炸。
  5. 全部小写、空格分隔，供 SQL ILIKE %keyword% 查询。

返回两份字符串而非一个：
  full_text     : 含所有"每字 全拼/首字母 自由组合"，主战场，覆盖所有输入
  initials_text : 仅纯首字母组合，留作未来精排（首字母完全匹配优先于子串包含）
"""

from __future__ import annotations

from itertools import product
from typing import Iterable

from pypinyin import Style, pinyin

# 多音字 + 长姓名时组合数会爆炸（4 字 + 每字 2 读音 = 16×16=256），
# 这里截断到 32，覆盖 95% 真实姓名（最多 1-2 个多音字）。
_MAX_COMBINATIONS = 32


def _dedupe(items: Iterable[str]) -> list[str]:
    """保序去重——多音字组合可能产出相同字符串，去重压缩存储。"""
    return list(dict.fromkeys(items))


def _heteronym_lazy(name: str, style: Style) -> list[list[str]]:
    """对每个汉字按指定 style 取所有读音。

    pypinyin.pinyin(heteronym=True) 返回 list[list[str]]，每个汉字一组：
      "查" → [["zha", "cha"]]
      "李查" → [["li"], ["zha", "cha"]]
      非汉字字符（数字/英文）→ [[原字符]]
    （注：lazy_pinyin 不支持 heteronym，必须用 pinyin。）
    """
    groups = pinyin(name, style=style, heteronym=True)
    # 去重 + 小写，pypinyin 偶尔返回大写或空字符串，统一兜底
    cleaned: list[list[str]] = []
    for g in groups:
        items = [s.lower() for s in g if s]
        cleaned.append(_dedupe(items) or [""])
    return cleaned


def compute_pinyin(name: str) -> tuple[str, str]:
    """生成姓名的两份拼音索引串。

    Returns:
        (full_text, initials_text)
          - full_text     : 所有"每字 全拼/首字母 自由组合"用空格分隔
                            "张三" → "zhangsan zhangs zsan zs"
                            "查张三"（查多音字 zha/cha）→
                              "zhazhangsan zhazhangs zhazsan zhazs " +
                              "chazhangsan chazhangs chazsan chazs"
          - initials_text : 仅纯首字母的所有读音组合
                            "张三" → "zs"
                            "查张三" → "zzs czs"

    空姓名或纯非汉字（如英文名"Tom"）：
        full_text 仍是该字符串小写形态（"tom"），
        initials_text 取每段首字母（"t"）。这样英文姓名也能匹配。
    """
    if not name:
        return ("", "")

    # 全拼组（每字一组所有读音）和首字母组
    full_groups = _heteronym_lazy(name, Style.NORMAL)
    initial_groups = _heteronym_lazy(name, Style.FIRST_LETTER)

    char_count = len(full_groups)
    if char_count == 0:
        return ("", "")

    # 组合每个字时，可选"全拼"或"首字母"——先把每字的"候选集合"算出来
    # 候选 = 所有读音的全拼 ∪ 所有读音的首字母
    per_char_candidates: list[list[str]] = []
    for i in range(char_count):
        full_options = full_groups[i] if i < len(full_groups) else [""]
        init_options = initial_groups[i] if i < len(initial_groups) else [""]
        # 同字的全拼/首字母合并去重，例如纯英文字符 "T" 的全拼和首字母都是 "t"
        per_char_candidates.append(_dedupe(list(full_options) + list(init_options)))

    # 笛卡尔积：每字独立从候选集合选一个，连接成完整组合
    full_combos: list[str] = []
    for combo in product(*per_char_candidates):
        full_combos.append("".join(combo))
        if len(full_combos) >= _MAX_COMBINATIONS:
            break

    # 纯首字母组合（仅从 initial_groups 笛卡尔积，独立保留）
    initial_combos: list[str] = []
    for combo in product(*initial_groups):
        initial_combos.append("".join(combo))
        if len(initial_combos) >= _MAX_COMBINATIONS:
            break

    return (
        " ".join(_dedupe(full_combos)),
        " ".join(_dedupe(initial_combos)),
    )


def is_ascii_alpha(text: str) -> bool:
    """判断关键词是否为纯 ASCII 字母（含混合大小写），用于决定是否走拼音匹配。

    规则：非空、全部字符都是 ASCII 字母。汉字、数字、空格、标点一律返回 False，
    走原 name/patient_no ILIKE 路径，避免拼音列被误命中。
    """
    if not text:
        return False
    return all(c.isascii() and c.isalpha() for c in text)
