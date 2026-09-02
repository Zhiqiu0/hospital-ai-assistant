# -*- coding: utf-8 -*-
"""数据一致性体检（scripts/data_consistency_check.py，2026-09-03 新增）

**只读**：全程只跑 SELECT，不改一个字节。可以随时在生产上跑。

为什么需要：schema 层的漂移由 alembic 守着，但**数据层的逻辑一致性**没人查——
"已签发的病历挂在已取消的接诊下""同一接诊同类型出现两个 record_no=1""病历的
current_version 指向一个不存在的版本"这类组合，平时不报错，等到病历打不开、
统计对不上、HIS 回写幂等键撞车时才暴露，而那时已经是生产事故。

用法（容器内）：
    python scripts/data_consistency_check.py

退出码：发现 error 级问题返回 1，只有 warn 返回 0——可直接挂 CI 或 cron。
"""
import asyncio
import sys
from pathlib import Path

# 让脚本能直接 import app.*（与 cleanup_voice.py / smoke_pacs_orthanc.py 同一套路）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402

# (级别, 名称, 说明, SQL)
# SQL 必须返回一列 cnt 与可选的 sample（样例标识，便于人工核对）
CHECKS: list[tuple[str, str, str, str]] = [
    # ── 状态机非法组合 ───────────────────────────────────────────────
    ("error", "已签发病历挂在已取消接诊下",
     "签发时 encounter 必须是进行中；出现这种组合说明取消守卫被绕过，"
     "法定文书挂在一个'不存在的就诊'上，病案首页与统计都会错",
     """SELECT count(*) AS cnt, min(r.id) AS sample
        FROM medical_records r JOIN encounters e ON e.id = r.encounter_id
        WHERE r.status = 'submitted' AND e.status = 'cancelled'"""),

    ("error", "同一接诊同类型 record_no 重复",
     "record_no 是 HIS 回写幂等键 (visit_id, record_type, record_no) 的一部分，"
     "重复会让两份文书在 HIS 侧互相覆盖",
     """SELECT count(*) AS cnt, min(encounter_id) AS sample FROM (
            SELECT encounter_id, record_type, record_no
            FROM medical_records GROUP BY 1,2,3 HAVING count(*) > 1
        ) t"""),

    ("error", "current_version 指向不存在的版本",
     "病历正文读的就是这一版；指空会让病历打不开",
     """SELECT count(*) AS cnt, min(r.id) AS sample
        FROM medical_records r
        WHERE r.current_version > 0 AND NOT EXISTS (
            SELECT 1 FROM record_versions v
            WHERE v.medical_record_id = r.id AND v.version_no = r.current_version)"""),

    ("error", "已签发病历没有任何签发版本",
     "status=submitted 却查不到 source='doctor_signed' 的版本，"
     "签名链无从校验，法庭调阅时无法自证",
     """SELECT count(*) AS cnt, min(r.id) AS sample
        FROM medical_records r
        WHERE r.status = 'submitted' AND NOT EXISTS (
            SELECT 1 FROM record_versions v
            WHERE v.medical_record_id = r.id AND v.source = 'doctor_signed')"""),

    # ── 孤儿引用 ─────────────────────────────────────────────────────
    ("error", "接诊指向不存在的患者",
     "外键理论上挡得住，查它是为了发现历史脏数据或绕过 ORM 的写入",
     """SELECT count(*) AS cnt, min(e.id) AS sample
        FROM encounters e
        WHERE NOT EXISTS (SELECT 1 FROM patients p WHERE p.id = e.patient_id)"""),

    ("error", "病历指向不存在的接诊",
     "同上",
     """SELECT count(*) AS cnt, min(r.id) AS sample
        FROM medical_records r
        WHERE NOT EXISTS (SELECT 1 FROM encounters e WHERE e.id = r.encounter_id)"""),

    ("warn", "接诊挂在已被合并掉的患者名下",
     "档案合并会把接诊搬到 target；还挂在 source 上说明那次合并没搬干净，"
     "医生在 target 档案下看不到这次就诊",
     """SELECT count(*) AS cnt, min(e.id) AS sample
        FROM encounters e JOIN patients p ON p.id = e.patient_id
        WHERE p.is_deleted = true AND p.merged_into IS NOT NULL"""),

    ("warn", "合并去向指向一个也被删掉的档案",
     "链式合并（A→B，B 又被合并到 C）会让 A 的去向断在 B，追溯时跳不到 C",
     """SELECT count(*) AS cnt, min(p.id) AS sample
        FROM patients p JOIN patients t ON t.id = p.merged_into
        WHERE p.merged_into IS NOT NULL AND t.is_deleted = true"""),

    # ── 法定要素缺失 ─────────────────────────────────────────────────
    ("warn", "已签发病历缺病案首页快照",
     "patient_snapshot 是签发瞬间冻结、进了 sign_hash 的法定署名来源；"
     "缺失的多为签名链上线（2026-08-12）之前的历史数据",
     """SELECT count(*) AS cnt, min(id) AS sample
        FROM medical_records
        WHERE status = 'submitted' AND patient_snapshot IS NULL"""),

    # 判据刻意用"最近 24 小时"而不是硬编码修复上线的日期：
    #   ① 存量历史数据（服务端兜底 2026-09-02 上线之前建的）不会长期刷红，
    #      刷红的报告没人看，等于没有报告；
    #   ② 一旦有新的写入路径漏配 recorded_at，24 小时内就会被报出来。
    # 第一版写成 `created_at >= DATE '2026-09-02'` 误报了 2 条——那两条建于
    # 当天 00:24，而修复实际生效是 00:42。**体检脚本的判据本身也要经得起推敲**，
    # 假警报和漏报一样会让人不再相信这份报告。
    ("error", "近 24 小时新建的病历缺记录时间",
     "recorded_at 为空会让补记判定整条链路空转（见 #246）。还在新产生说明"
     "有写入路径漏配了服务端兜底",
     """SELECT count(*) AS cnt, min(id) AS sample
        FROM medical_records
        WHERE recorded_at IS NULL AND created_at >= now() - interval '24 hours'"""),

    ("warn", "更早的存量病历缺记录时间",
     "补记判定对它们永远返回 False。开业前清库会一并清掉；若清库后仍有，"
     "说明混进了真实病历，需要人工确认是否回填为创建时间",
     """SELECT count(*) AS cnt, min(id) AS sample
        FROM medical_records
        WHERE recorded_at IS NULL AND created_at < now() - interval '24 hours'"""),

    ("warn", "住院已出院但缺出院记录且已过 24 小时",
     "法定时限是出院后 24 小时内完成；超期未写的要提醒医务科",
     """SELECT count(*) AS cnt, min(e.id) AS sample
        FROM encounters e
        WHERE e.visit_type = 'inpatient' AND e.status = 'completed'
          AND e.completed_at IS NOT NULL
          AND e.completed_at < now() - interval '24 hours'
          AND NOT EXISTS (
              SELECT 1 FROM medical_records r
              WHERE r.encounter_id = e.id AND r.record_type = 'discharge_record'
                AND r.status = 'submitted')"""),

    # ── 账号与工号 ───────────────────────────────────────────────────
    ("error", "工号挂在不存在或已停用的账号下",
     "HIS 按工号派医生，挂空会让推送 ack 40007、患者进不了工作台",
     """SELECT count(*) AS cnt, min(dc.code) AS sample
        FROM doctor_codes dc
        WHERE NOT EXISTS (
            SELECT 1 FROM users u WHERE u.id = dc.user_id AND u.is_active = true)"""),

    ("error", "同一工号绑在多个账号下",
     "admit_service 遇到这种会直接 40007 拒收接诊",
     """SELECT count(*) AS cnt, min(code) AS sample FROM (
            SELECT code FROM doctor_codes GROUP BY code HAVING count(*) > 1
        ) t"""),
]


async def main() -> int:
    failed = 0
    warned = 0
    print("=== 数据一致性体检（只读）===\n")
    async with AsyncSessionLocal() as db:
        for level, name, why, sql in CHECKS:
            try:
                row = (await db.execute(text(sql))).mappings().first()
            except Exception as exc:                      # 表缺失等
                print(f"  [跳过] {name}：{type(exc).__name__} {exc}"[:160])
                continue
            cnt = int(row["cnt"] or 0)
            if cnt == 0:
                print(f"  ✓ {name}")
                continue
            mark = "✗" if level == "error" else "!"
            print(f"  {mark} {name}：{cnt} 条  样例={row.get('sample')}")
            print(f"      {why}")
            if level == "error":
                failed += 1
            else:
                warned += 1
    print(f"\n=== 结论：error {failed} 项 / warn {warned} 项 ===")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
