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
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.storage_paths import UPLOADS_ROOT  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402

# 删除顺序 = 外键依赖的逆序（子表在前，父表在后）。
# 顺序错了 PG 会直接报外键冲突（不会静默留孤儿），但报错就得从头再来，
# 所以这里按依赖图排好，一次过。
PURGE_ORDER = [
    # 2026-08-28 全量体检补漏：qc_reviews/qc_reports/diagnoses 是 08-21 病案首页
    # 质控工程新增的表，本脚本（08-17 交付）没赶上——漏删会被外键直接拦住
    # medical_records/encounters 的删除，开业当天脚本必失败。已加表覆盖契约测试
    # （tests/test_purge_coverage.py）防再漏。
    ("qc_reviews", "质控员复核记录（依赖 medical_records / encounters）"),
    ("qc_reports", "质控评分报告（依赖 medical_records / encounters）"),
    ("qc_issues", "质控问题（依赖 ai_tasks / medical_records）"),
    ("ai_tasks", "AI 任务记录"),
    ("record_versions", "病历版本（正文全文在这里）"),
    ("medical_records", "病历主表"),
    ("inquiry_inputs", "问诊分字段录入"),
    ("vital_signs", "生命体征"),
    ("problem_list", "住院问题列表"),
    ("diagnoses", "诊断条目（依赖 encounters）"),
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
# qc_rules           医保/关键词质控规则配置
# revoked_tokens     登录态黑名单，与临床数据无关
# diagnosis_codes    医保 2.0 编码字典（4.8 万条配置资产，由迁移导入，绝不能清）
#
# ⚠️ 开业前第二步（2026-08-17 第 13 轮审计新增）：本脚本保留 users/departments，
#    但这两张表里还混着联调/审计留下的**测试账号与测试科室**（如种子 doctor01，
#    口令 doctor123 明文就在仓库里，实测能登生产签病历）。清库清不掉它们。
#    正式开业前，跑完本脚本 --execute 后，**再跑 purge_test_accounts.py --execute**
#    把测试账号/科室清掉，并按它的口令体检把 admin 默认口令改掉。
KEEP = ["users", "doctor_codes", "departments", "qc_rules", "revoked_tokens",
        "diagnosis_codes"]

# ── 磁盘上的 PHI 文件（2026-08-31 冷启动审计新增）────────────────────────────
# 本脚本此前**只清数据库**。但语音录音、检验单原图、DICOM 解压件是落在磁盘上
# 的独立文件（uploads 挂载卷），表清空后它们就成了没有任何 DB 记录指向的孤儿：
#   · 列表看不到、审计查不到，全仓也没有孤儿文件清理任务 → 没人会再发现它们；
#   · 却仍被 backup.sh 每日打包上传 OSS，按 180 天留存策略继续复制扩散。
# 医院跑完清库会认为「测试数据清干净了」，实际联调期患者的医患对话录音和
# 检验单原图原封不动留在生产卷里——**虚假的清洁感比不清更危险**。
# 子目录名与写入端一一对应：voice_records 见 api/v1/ai_voice_records.py，
# lab_reports 见 services/lab_reports_service.py，imaging 见 models/imaging.py。
# 新增任何写 uploads 的功能都必须在此登记（契约测试 test_purge_coverage.py 锁）。
STORAGE_DIRS = [
    ("voice_records", "语音录音（医患真实对话）"),
    ("lab_reports", "检验报告原图"),
    ("imaging", "影像文件（DICOM 解压件）"),
]

CONFIRM_PHRASE = "确认清空临床数据"


async def _counts(db) -> list[tuple[str, str, int]]:
    """统计每张表当前行数（干跑与真删前都要看一眼）。"""
    out = []
    for table, desc in PURGE_ORDER:
        n = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar() or 0
        out.append((table, desc, n))
    return out


def _storage_counts() -> list[tuple[str, str, int, int]]:
    """统计 uploads 下各类 PHI 文件的数量与占用字节（干跑与真删前都要看）。"""
    out = []
    for sub, desc in STORAGE_DIRS:
        d = UPLOADS_ROOT / sub
        files = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
        out.append((sub, desc, len(files), sum(p.stat().st_size for p in files)))
    return out


def _purge_storage() -> int:
    """删除 uploads 下三类 PHI 文件，返回删除的文件数。

    **为什么放在数据库提交之后**：文件删除不可回滚。若先删文件而 DB 事务随后
    回滚，会留下「DB 里有记录、磁盘上文件已消失」的坏状态（比不删难收拾得多）；
    反过来 DB 已清而文件没删掉，最坏只是孤儿文件仍在，重跑一次即可收拾。
    """
    removed = 0
    for sub, _desc, n, _size in _storage_counts():
        d = UPLOADS_ROOT / sub
        if not d.is_dir() or not n:
            continue
        # 只清目录内容、保留顶层子目录本身：写入端虽然都会 mkdir(parents=True)，
        # 但留着目录不会有坏处，也免得挂载卷上出现属主/权限差异。
        for child in d.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
        removed += n
        print(f"  已清空 uploads/{sub}（{n} 个文件）")
    return removed


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

        # 磁盘上的 PHI 文件与库表分开统计——它们不受任何 DELETE 影响，
        # 必须单独看一眼（见 STORAGE_DIRS 处的说明）。
        storage = _storage_counts()
        file_total = sum(n for _, _, n, _ in storage)
        print("\n开业前清场 · 将清空的磁盘文件（uploads 卷）")
        for sub, desc, n, size in storage:
            print(f"  uploads/{sub:<16} {n:>7} 个   {size / 1024:>8.1f} KB   {desc}")
        print(f"  {'合计':<24} {file_total:>7} 个")

        print(f"\n  保留不动：{', '.join(KEEP)}")
        # Orthanc 里的 DICOM 归 PACS 服务自己管，本脚本不越界直连外部服务，
        # 只把它点出来交给人工：漏了它等于把联调期影像连同患者姓名留在生产。
        print("  ⚠ Orthanc(PACS) 里的 DICOM 本脚本不碰，需人工确认："
              "docker compose exec orthanc curl -s http://localhost:8042/studies")

        if total == 0 and file_total == 0:
            print("\n库里没有临床数据、磁盘上也没有 PHI 文件，无需清理。")
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
        #
        # audit_logs 只追加触发器（2026-08-28 全量体检修复）：生产库上
        # trg_audit_logs_append_only 会对 DELETE 直接 RAISE EXCEPTION——
        # 原写法删到审计表必炸、整个清库回滚，脚本在生产从来跑不通
        # （交付时只干跑过，干跑不触发触发器）。这里在同一事务内临时禁用
        # 该触发器、删完立即恢复：ALTER TABLE 是事务性的，中途失败回滚时
        # 触发器状态也一并还原，不存在"禁用后忘了开"的窗口。
        # 这是唯一的合法删审计通道：仅限开业前清测试数据这一次性场景。
        for table, _desc, n in counts:
            if not n:
                continue
            if table == "audit_logs":
                await db.execute(text(
                    "ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only"))
                await db.execute(text("DELETE FROM audit_logs"))
                await db.execute(text(
                    "ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only"))
                print(f"  已清空 audit_logs（{n} 行，触发器已恢复）")
            else:
                await db.execute(text(f"DELETE FROM {table}"))
                print(f"  已清空 {table}（{n} 行）")
        await db.commit()

        # 数据库已提交，再动磁盘（顺序理由见 _purge_storage 的 docstring）
        if file_total:
            _purge_storage()

        left = sum(n for _, _, n in await _counts(db))
        left_files = sum(n for _, _, n, _ in _storage_counts())
        print(f"\n清理完成，临床数据剩余 {left} 行、磁盘 PHI 文件剩余 {left_files} 个。")
        print("账号、科室、提示词、质控规则均未改动，可直接投入使用。")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="开业前清空全部临床数据（保留账号与配置）")
    ap.add_argument("--execute", action="store_true",
                    help="真正执行删除；不加此参数只统计不删除")
    sys.exit(asyncio.run(main(ap.parse_args().execute)))
