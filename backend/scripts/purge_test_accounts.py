# -*- coding: utf-8 -*-
"""开业前清场（第二步）：清掉测试/种子账号与测试科室，并核对默认密码。

**为什么需要它，而 purge_clinical_data.py 不够**：
  purge_clinical_data.py 按设计**只清临床数据、保留 users/departments 等 7 张配置表**
  （那里面躺着刚导入的 40 位真实医生，绝不能动）。但同一批保留表里，还混着联调
  与历次审计留下的**测试账号和测试科室**——它们不是临床数据，清库脚本碰不到，
  于是会**原封不动带进生产**。

  这为什么要命（第 13 轮审计实测，2026-08-17）：
    · 种子账号 `doctor01` 的密码是 `doctor123`——**这串明文就写在公开仓库的
      init_db.py 里**。实测 `POST /auth/login doctor01/doctor123` 在生产返回
      200 + 一个 role=doctor 的有效 token，拿它就能以「张医生」名义签发病历。
    · 测试医生 `zz`（zz/123456）、`e2e_doctor`、`叶主任测试1` 同理，都是
      **must_change_password=false 的活跃医生账号**，首登强改密这道闸门对它们
      不生效（它们不是批量开户建的）。
    · 管理员 `admin` 若仍是默认口令 `admin123456`（同样在仓库里、也在冒烟文档里），
      那就是一个**默认口令的超级管理员**——全院最高价值目标。

  一句话：开业当天，任何读过我们仓库的人都能登进来签病历/接管后台。清库救不了
  这一层，因为它按设计不碰账号。

**为什么单独一个脚本、而不是塞进 purge_clinical_data.py**：
  那个脚本的契约白纸黑字是「只清临床、账号一律保留」，把删账号塞进去会破坏它
  自己声明的 KEEP 清单，也让「清临床」这件事不再可单独安全执行。两件事分两个
  脚本，各自单一职责。

**执行时机**：在 purge_clinical_data.py --execute **之后**跑。那时临床表已空，
  测试账号名下不再有接诊/病历/审计外键，删除干净利落；若不慎在清库前跑，
  PG 外键会直接拦下（报错即安全，不会留半删状态）。

用法（默认只报告不删除）：
    python scripts/purge_test_accounts.py               # 干跑：列出将删的账号/科室 + 默认口令体检
    python scripts/purge_test_accounts.py --execute     # 真删（需逐字输入确认短语）

在生产服务器上（真删要带 tty，去掉 -T）：
    ssh -t root@47.116.166.70 "cd /app && docker compose exec backend \\
        python scripts/purge_test_accounts.py --execute"

⚠️ admin 的口令本脚本**只体检、不自动改**——自动改真实管理员口令风险太大，
   且新口令不该由脚本决定。体检提示「仍是默认口令」时，请人工用
   `POST /auth/change-password` 或后台改掉，再重启无关。
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.security import verify_password  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402

# ── 要清掉的测试/种子账号（按 username 精确匹配，闭集，绝不误伤真实医生）────────
# 之所以用显式白名单而不是「删掉所有非名单账号」这种聪明规则：后者一旦名单口径
# 有偏差就会连 admin 或真实医生一起误删，代价不可逆。这几个账号是第 13 轮审计在
# 生产库里逐行核对出来的确定测试数据，写死最稳。
TEST_USERNAMES = [
    "doctor01",        # init_db 种子医生，口令 doctor123 明文在仓库
    "zz",              # 测试医生 张测试（zz/123456）
    "e2e_doctor",      # E2E 测试医生
    "叶主任测试1",      # 早期联调测试账号
    "audit_deptadmin_023725",  # 审计留下的 dept_admin（已停用，一并清）
    # 质控员测试账号（2026-08-29 第六轮渗透审计补）：2026-08-21 质控复核台
    # 上线时在生产手工建的 qc_officer，**晚于本名单定稿（08-17）4 天**故此前
    # 漏列——它能只读全院已签发病历（PHI），带进开业生产等于留一个后门号。
    # 教训：每上线一个新角色的测试账号，必须同步补进本名单。
    "qctest",
]

# ── 要清掉的测试科室（按 code 精确匹配）──────────────────────────────────────
# 审计脚本建出来的垃圾科室，已停用但仍占着科室列表。
# 注意：`0101/全科` **不在此列**——它是 2026-08-15 联调叫号时 HIS 推送自动建的，
# 「全科」可能是医院真实科室，删错会让该科挂号的接诊落不到科室。交给人工确认。
TEST_DEPT_CODES = [
    "audittest021850",   # 审计测试科室021850
    "audit2022552",      # 审计验证科室022552
]

# admin 默认口令（init_db.py 的 SEED_ADMIN_PASSWORD 缺省值）——只用于体检比对
_ADMIN_DEFAULT_PWD = "admin123456"

CONFIRM_PHRASE = "确认清除测试账号"


async def _preview(db):
    """列出将删除的账号与科室（干跑与真删前都要看一眼）。"""
    users = (await db.execute(text("""
        SELECT username, real_name, role, is_active, must_change_password
        FROM users WHERE username = ANY(:names) ORDER BY username
    """), {"names": TEST_USERNAMES})).all()
    depts = (await db.execute(text("""
        SELECT code, name, is_active FROM departments
        WHERE code = ANY(:codes) ORDER BY code
    """), {"codes": TEST_DEPT_CODES})).all()
    return users, depts


async def _suspicious_leftover_check(db) -> None:
    """兜底扫描（2026-08-29 第六轮渗透审计）：名单是闭集，但测试账号可能在
    名单定稿**之后**才手工建（qctest 就是这么漏的——08-17 定名单、08-21 建号）。
    清完后按命名特征扫一遍库里剩下的疑似测试账号，打出来让操作者人工确认，
    不自动删（闭集原则不破：自动删有误伤真实账号的不可逆风险）。"""
    rows = (await db.execute(text("""
        SELECT username, real_name, role, is_active FROM users
        WHERE username != ALL(:names)
          AND (username ILIKE '%test%' OR username ILIKE '%demo%'
               OR username ILIKE 'e2e%' OR username ILIKE '%测试%'
               OR real_name ILIKE '%测试%')
        ORDER BY username
    """), {"names": TEST_USERNAMES})).all()
    print("\n【疑似测试账号扫描】（按命名特征，不在删除名单内，需人工确认）：")
    if not rows:
        print("    （未发现疑似测试账号）")
        return
    for username, real_name, role, is_active in rows:
        state = "在用" if is_active else "已停用"
        print(f"    🔶 {username:<24} {real_name or '':<12} {role:<12} {state}"
              " —— 若是测试号请加进 TEST_USERNAMES 后重跑")


async def _admin_password_check(db) -> None:
    """体检：管理员账号是否仍是仓库默认口令——开业前必须改掉。"""
    row = (await db.execute(text(
        "SELECT username, password_hash FROM users "
        "WHERE role = 'super_admin' AND is_active ORDER BY created_at"
    ))).all()
    print("\n【默认口令体检】超级管理员：")
    if not row:
        print("    （没有在用的超级管理员账号）")
        return
    for username, pwd_hash in row:
        weak = verify_password(_ADMIN_DEFAULT_PWD, pwd_hash)
        flag = "🔴 仍是默认口令 admin123456 —— 开业前必须人工改掉" if weak else "✅ 非默认口令"
        print(f"    {username:<16} {flag}")


async def main(execute: bool) -> int:
    async with AsyncSessionLocal() as db:
        users, depts = await _preview(db)

        print("=" * 66)
        print("开业前清场（第二步）· 测试账号与测试科室")
        print("=" * 66)
        print(f"\n将删除的测试账号（{len(users)} 个）：")
        if not users:
            print("    （库里已无这些测试账号）")
        for username, real_name, role, is_active, must_chg in users:
            state = "在用" if is_active else "已停用"
            print(f"    {username:<24} {real_name:<12} {role:<12} {state}")
        print(f"\n将删除的测试科室（{len(depts)} 个）：")
        if not depts:
            print("    （库里已无这些测试科室）")
        for code, name, is_active in depts:
            state = "在用" if is_active else "已停用"
            print(f"    {code:<20} {name:<20} {state}")

        # 默认口令体检独立于删除逻辑——即便测试账号已清干净，admin 口令照样要看
        await _admin_password_check(db)
        # 疑似漏网测试账号扫描（独立于删除逻辑，干跑也扫）
        await _suspicious_leftover_check(db)

        if not users and not depts:
            print("\n无测试账号/科室可删（仍请落实上方 admin 口令体检）。")
            if not execute:
                print("[干跑] 未做任何删除。")
            return 0

        if not execute:
            print("\n[干跑] 未做任何删除。确认无误后加 --execute 真正执行。")
            print("提示：本脚本应在 purge_clinical_data.py --execute 之后再跑。")
            return 0

        print("\n" + "!" * 66)
        print("即将永久删除上述测试账号与科室。执行前请确认：")
        print("  ① 已先跑过 purge_clinical_data.py --execute（临床表已空，无外键残留）")
        print("  ② 上方列出的账号确实都是测试数据，无一是真实医生")
        print("!" * 66)
        typed = input(f'\n请逐字输入「{CONFIRM_PHRASE}」以继续：').strip()
        if typed != CONFIRM_PHRASE:
            print("输入不匹配，已取消，未做任何删除。")
            return 1

        # 同一事务：中途任一步出错整体回滚，不留半删状态。
        # 先删 doctor_codes（外键指向 users），再删 users；科室最后删。
        # 若临床表未清空、账号名下仍有接诊/病历，DELETE 会撞外键直接抛错回滚——
        # 这正是我们要的保护：宁可报错也不静默留孤儿。
        if users:
            await db.execute(text(
                "DELETE FROM doctor_codes WHERE user_id IN "
                "(SELECT id FROM users WHERE username = ANY(:names))"
            ), {"names": TEST_USERNAMES})
            r = await db.execute(text(
                "DELETE FROM users WHERE username = ANY(:names)"
            ), {"names": TEST_USERNAMES})
            print(f"\n  已删除测试账号 {r.rowcount} 个")
        if depts:
            r = await db.execute(text(
                "DELETE FROM departments WHERE code = ANY(:codes)"
            ), {"codes": TEST_DEPT_CODES})
            print(f"  已删除测试科室 {r.rowcount} 个")
        await db.commit()

        print("\n清理完成。请再次落实上方 admin 默认口令体检的处置。")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="开业前清除测试/种子账号与测试科室（配套 purge_clinical_data.py）")
    ap.add_argument("--execute", action="store_true",
                    help="真正执行删除；不加此参数只报告不删除")
    sys.exit(asyncio.run(main(ap.parse_args().execute)))
