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

# 输出字符串长度 hard cap，避免超过 patients.name_pinyin VARCHAR(512) 写入失败。
# 触发场景：长姓名（>=6 字）+ 多个多音字 + 含 ASCII 字符（"E2E回归_完整流程"）时，
# 即使 _MAX_COMBINATIONS=32 截断了，每个组合本身长度仍可累计到 800+ 字符。
# 安全余量取 480（< 512），按空格切片，避免切到组合中间产生半截拼音误匹配。
_FULL_TEXT_MAX_LEN = 480
_INITIALS_TEXT_MAX_LEN = 120  # name_pinyin_initials 是 VARCHAR(128)


def _join_with_cap(combos: list[str], cap: int) -> str:
    """按空格拼接组合列表，总长度 > cap 时按完整组合边界截断。"""
    out: list[str] = []
    total = 0
    for c in combos:
        added = len(c) + (1 if out else 0)
        if total + added > cap:
            break
        out.append(c)
        total += added
    return " ".join(out)


def _dedupe(items: Iterable[str]) -> list[str]:
    """保序去重——多音字组合可能产出相同字符串，去重压缩存储。"""
    return list(dict.fromkeys(items))


# 间隔号类字符（2026-08-31 姓名边界审计）：少数民族姓名「买买提·艾力」里的
# 分隔符有多种码点写法——U+00B7（GB18030 规定用法）、U+2027、U+30FB（日文）、
# U+FF65（半角片假名）、U+2022（项目符号，微信/OCR 粘贴常见）、U+0387。
# 算拼音前必须剔除：否则 pypinyin 把它当一个'字'原样保留，索引存成
# 'maimaiti·aili'，而查询侧的 is_ascii_alpha 闸门又把带点关键词挡在拼音列外
# ——全拼、首字母、带点三种输入全部 miss，这类患者只能用汉字搜。
SEPARATOR_CHARS = (
    chr(0x00B7) + chr(0x2027) + chr(0x30FB) + chr(0xFF65) + chr(0x2022) + chr(0x0387)
)


def strip_separators(name: str) -> str:
    """去掉姓名里的各种间隔号，供拼音索引与查重比对使用。"""
    if not name:
        return name
    for ch in SEPARATOR_CHARS:
        name = name.replace(ch, "")
    return name

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
        # 丢弃仍是非 ASCII 的读音（2026-08-31 姓名边界审计）：pypinyin 对
        # 无拼音数据的扩展区汉字（如 U+3402 㐂，"喜"的异体，真实姓氏用字）
        # 原样返回汉字本身，写进拼音列会污染索引、让该患者拼音搜索永远 miss。
        items = [x.lower() for x in g if x and x.isascii()]
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

    # 先剔除间隔号（见 SEPARATOR_CHARS 注释）：索引产出纯字母组合，
    # 医生输 maimaitiaili / mmtal / mmt·al 三种形态都能命中
    name = strip_separators(name)
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
        _join_with_cap(_dedupe(full_combos), _FULL_TEXT_MAX_LEN),
        _join_with_cap(_dedupe(initial_combos), _INITIALS_TEXT_MAX_LEN),
    )


def is_ascii_alpha(text: str) -> bool:
    """判断关键词是否为纯 ASCII 字母（含混合大小写），用于决定是否走拼音匹配。

    规则：非空、全部字符都是 ASCII 字母。汉字、数字、空格、标点一律返回 False，
    走原 name/patient_no ILIKE 路径，避免拼音列被误命中。
    """
    if not text:
        return False
    return all(c.isascii() and c.isalpha() for c in text)
