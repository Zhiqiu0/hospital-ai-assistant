# -*- coding: utf-8 -*-
"""开业前清场：清空全部临床数据，保留账号与配置。

**用途只有一个**：HIS 联调结束、医院正式启用**之前**，把联调与冒烟产生的
测试病历一次性清干净。这是我方在《HIS 接口规范》第 6 章对厂商的承诺——
「联调期间产生的测试病历，由我方在医院正式启用前统一清理」。

为什么需要这个脚本而不是当天手搓 SQL：
  · 已签发的病历产品**不允许作废**（病历安全设计，接诊也取消不了），
    所以清理只能在库里做；
  · 临床数据横跨 14 张表且有外键依赖，删错顺序会留下孤儿行；
  · 那天是联调刚成功、准备开业的时点，最不适合临时写删库语句。

⚠️ 唯一的硬前提：**医院任何一位医生开始真实接诊之前**执行。
   一旦有真实患者进来，这个脚本删的就是真实病案，不可恢复。

用法（默认只统计不删除）：
    python scripts/purge_clinical_data.py                    # 干跑，列出将删除的行数
    python scripts/purge_clinical_data.py --execute          # 真删（还需按提示输入确认短语）

在生产服务器上执行——**两条命令的 -T 不一样，别抄错**：
    # 干跑（非交互即可）
    ssh root@47.116.166.70 "cd /app && docker compose exec -T backend \\
        python scripts/purge_clinical_data.py"
    # 真删：确认短语要从键盘输入，**必须去掉 -T**，且要用带 tty 的 ssh（ssh -t）
    ssh -t root@47.116.166.70 "cd /app && docker compose exec backend \\
        python scripts/purge_clinical_data.py --execute"
带着 -T 跑 --execute 会在读确认短语时直接 EOF 失败——那天手忙脚乱最容易踩这个。
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402

# 删除顺序 = 外键依赖的逆序（子表在前，父表在后）。
# 顺序错了 PG 会直接报外键冲突（不会静默留孤儿），但报错就得从头再来，
# 所以这里按依赖图排好，一次过。
PURGE_ORDER = [
    ("qc_issues", "质控问题（依赖 ai_tasks / medical_records）"),
    ("ai_tasks", "AI 任务记录"),
    ("record_versions", "病历版本（正文全文在这里）"),
    ("medical_records", "病历主表"),
    ("inquiry_inputs", "问诊分字段录入"),
    ("vital_signs", "生命体征"),
    ("problem_list", "住院问题列表"),
    ("ai_suggestion_feedback", "AI 建议采纳反馈"),
    ("lab_reports", "检验报告"),
    ("imaging_reports", "影像报告（依赖 imaging_studies）"),
    ("imaging_studies", "影像检查"),
    ("voice_records", "语音记录"),
    ("encounters", "接诊"),
    ("patients", "患者档案"),
    ("audit_logs", "审计日志（记的都是上述测试操作，一并清）"),
]

# 明确**不删**的表，写在这里是为了让"没删什么"同样一目了然：
# users / doctor_codes 医生账号与工号绑定（联调时刚开的户，删了要重来）
# departments        科室（含 HIS 推送自动建的）
# model_configs / prompt_templates / qc_rules  模型、提示词、质控规则配置
# revoked_tokens     登录态黑名单，与临床数据无关
#
# ⚠️ 开业前第二步（2026-08-17 第 13 轮审计新增）：本脚本保留 users/departments，
#    但这两张表里还混着联调/审计留下的**测试账号与测试科室**（如种子 doctor01，
#    口令 doctor123 明文就在仓库里，实测能登生产签病历）。清库清不掉它们。
#    正式开业前，跑完本脚本 --execute 后，**再跑 purge_test_accounts.py --execute**
#    把测试账号/科室清掉，并按它的口令体检把 admin 默认口令改掉。
KEEP = ["users", "doctor_codes", "departments", "model_configs",
        "prompt_templates", "qc_rules", "revoked_tokens"]

CONFIRM_PHRASE = "确认清空临床数据"


async def _counts(db) -> list[tuple[str, str, int]]:
    """统计每张表当前行数（干跑与真删前都要看一眼）。"""
    out = []
    for table, desc in PURGE_ORDER:
        n = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar() or 0
        out.append((table, desc, n))
    return out


async def _sanity_report(db) -> None:
    """把"这批数据是谁在什么时候产生的"打出来——这是执行前最后一道人眼防线。

    如果这里出现你不认识的医生、或者时间跨度不像联调期，就说明有人已经在
    真实使用了，**立刻停手**。
    """
    rows = (await db.execute(text("""
        SELECT COALESCE(u.real_name, u.username, '(无)') AS doctor,
               COUNT(*) AS n,
               MIN(e.visited_at)::date AS first_day,
               MAX(e.visited_at)::date AS last_day
        FROM encounters e LEFT JOIN users u ON u.id = e.doctor_id
        GROUP BY 1 ORDER BY n DESC LIMIT 20
    """))).all()
    print("\n【执行前人眼核对】接诊按医生分布：")
    if not rows:
        print("    （库里没有接诊数据）")
    for doctor, n, first_day, last_day in rows:
        print(f"    {doctor:<12} {n:>5} 条    {first_day} ~ {last_day}")
    print("    ↑ 出现不认识的医生、或时间跨度不像联调期 → 说明已有真实使用，立刻停手")


async def main(execute: bool) -> int:
    async with AsyncSessionLocal() as db:
        counts = await _counts(db)
        total = sum(n for _, _, n in counts)

        print("=" * 66)
        print("开业前清场 · 将清空的临床数据")
        print("=" * 66)
        for table, desc, n in counts:
            print(f"  {table:<24} {n:>7} 行   {desc}")
        print(f"  {'合计':<24} {total:>7} 行")
        print(f"\n  保留不动：{', '.join(KEEP)}")

        if total == 0:
            print("\n库里没有临床数据，无需清理。")
            return 0

        await _sanity_report(db)

        if not execute:
            print("\n[干跑] 未做任何删除。确认无误后加 --execute 真正执行。")
            return 0

        print("\n" + "!" * 66)
        print("即将永久删除上述数据，**不可恢复**。执行前请确认：")
        print("  ① 医院尚无任何医生真实接诊（这是本脚本唯一的适用前提）")
        print("  ② 已有当日数据库备份（服务器每日 03:00 自动备份）")
        print("!" * 66)
        typed = input(f'\n请逐字输入「{CONFIRM_PHRASE}」以继续：').strip()
        if typed != CONFIRM_PHRASE:
            print("输入不匹配，已取消，未做任何删除。")
            return 1

        # 全部删除放在**同一个事务**里：中途任何一张表出错就整体回滚，
        # 不会留下"删了一半"的库（那比不删更难收拾）。
        for table, _desc, n in counts:
            if n:
                await db.execute(text(f"DELETE FROM {table}"))
                print(f"  已清空 {table}（{n} 行）")
        await db.commit()

        left = sum(n for _, _, n in await _counts(db))
        print(f"\n清理完成，临床数据剩余 {left} 行。")
        print("账号、科室、提示词、质控规则均未改动，可直接投入使用。")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="开业前清空全部临床数据（保留账号与配置）")
    ap.add_argument("--execute", action="store_true",
                    help="真正执行删除；不加此参数只统计不删除")
    sys.exit(asyncio.run(main(ap.parse_args().execute)))
