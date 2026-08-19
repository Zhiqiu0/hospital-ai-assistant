# -*- coding: utf-8 -*-
"""主诉 AI 改写回归评测（scripts/eval_cc_rewrite.py）

背景（2026-08-19）：主诉从"严格照抄"放开为"仅用词规范化"（真实性约束 3a），
本脚本用 18 个口语/挖坑主诉走**真实生成链路**（build_record_prompt → LLM →
render_record），抽出【主诉】对照检查，防止将来改提示词时该规则悄悄劣化。

不是单元测试（要调 LLM、花钱、有随机性），改动生成提示词后手动跑：
    cd backend && venv/Scripts/python scripts/eval_cc_rewrite.py

检查器只做保守的机械断言（时间数字不得凭空出现、侧别不得凭空出现、
禁用词包含检查），措辞好坏仍需人眼扫一遍输出。
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.ai_request import QuickGenerateRequest  # noqa: E402
from app.services.ai.llm_client import llm_client  # noqa: E402
from app.services.ai.model_options import get_model_options  # noqa: E402
from app.services.ai.record_prompts import build_record_prompt  # noqa: E402
from app.services.ai.record_renderer import render_record  # noqa: E402

# (口语主诉, 输出中禁止出现的串, 输出中必须出现的串)
# 禁止串用于抓"编精确数/加侧别/保留诊断名"；必须串用于抓"丢核心症状"
CASES: list[tuple[str, list[str], list[str]]] = [
    ("左边胸口肋骨痛10来天", ["10天，", "整10天"], ["左", "痛", "10天余"]),
    ("腰痛，弯不下腰，三四天了", ["3天", "4天半"], ["腰", "3-4天"]),
    ("头晕好几天了", ["3天", "5天", "7天"], ["头晕", "数天"]),
    ("拉肚子两天，一天七八次", [], ["腹泻", "2天", "7-8"]),
    ("老毛病又犯了，胃痛", ["天", "周", "月"], ["胃痛"]),
    ("摔了一跤，手腕肿痛2小时", ["左", "右"], ["腕", "肿", "2小时"]),
    ("咳嗽有痰一个礼拜，晚上厉害", [], ["咳", "痰", "1周"]),
    ("心口闷，喘不上气半天", [], ["闷", "半天"]),
    ("小孩发烧39度2天", ["38", "40"], ["39", "2天"]),
    ("肚子疼", ["天", "小时", "周"], ["腹痛"]),
    ("脖子落枕两天", ["落枕"], ["颈", "2天"]),
    ("膝盖痛，上下楼梯更痛，有大半年了", [], ["膝", "楼梯", "半年"]),
    ("被开水烫到右手背，起水泡，1小时", ["左手"], ["右手背", "烫", "1小时"]),
    ("感冒了三天，流鼻涕打喷嚏", ["感冒"], ["3天"]),
    ("肩膀酸痛，抬不起来，个把月", ["1个月，", "整月"], ["肩", "月余"]),
    ("眼睛红，有眼屎，昨天开始的", [], ["眼", "红"]),
    # 复诊：诊断名主诉必须原样保留
    ("高血压复诊", [], ["高血压复诊"]),
    ("糖尿病配药", [], ["糖尿病"]),
]


def extract_cc(record_text: str) -> str:
    """从渲染后的病历抽【主诉】正文。"""
    m = re.search(r"【主诉】\n([^\n【]+)", record_text)
    return m.group(1).strip() if m else "(抽取失败)"


async def run_case(cc: str, banned: list[str], required: list[str]) -> bool:
    req = QuickGenerateRequest(
        record_type="outpatient", patient_name="患者", patient_gender="男",
        patient_age="50", is_first_visit=not cc.endswith(("复诊", "配药")),
        chief_complaint=cc,
        history_present_illness="（本评测只看主诉，现病史从简）患者不适来诊。",
    )
    prompt = build_record_prompt("outpatient", req)
    opts = get_model_options("generate")
    result = await llm_client.chat_json_stream(
        [{"role": "user", "content": prompt}],
        temperature=opts["temperature"], max_tokens=opts["max_tokens"],
        model_name=opts["model_name"],
    )
    out = extract_cc(render_record("outpatient", result))
    problems = [f"出现禁止串'{b}'" for b in banned if b in out]
    problems += [f"缺必须串'{r}'" for r in required if r not in out]
    flag = "✓" if not problems else "✗ " + "；".join(problems)
    print(f"{flag}  {cc}  →  {out}")
    return not problems


async def main() -> None:
    results = []
    for cc, banned, required in CASES:
        results.append(await run_case(cc, banned, required))
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} 通过")
    sys.exit(0 if n_ok == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
